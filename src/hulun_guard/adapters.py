from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .constants import VALID_EVENT_PHASES
from .privacy import TRACE_TEXT_KEYS, fingerprint_text, redact_list, redact_refs, redact_text, safe_summary_from_trace
from .util import parse_time, tokens

Observation = dict[str, Any]

MAX_TRACE_BYTES = 5 * 1024 * 1024


FAIL_MARKERS = [
    "error",
    "exception",
    "fail",
    "failed",
    "failure",
    "traceback",
    "timeout",
    "permission denied",
    "not found",
]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _first_text(item: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = item.get(key)
        text = _as_text(value).strip()
        if text:
            return text
    return ""


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _attr_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ["stringValue", "intValue", "doubleValue", "boolValue", "bytesValue"]:
        if key in value:
            return value[key]
    if "arrayValue" in value:
        raw_values = value.get("arrayValue", {}).get("values", [])
        return [_attr_value(item) for item in raw_values]
    if "kvlistValue" in value:
        values = value.get("kvlistValue", {}).get("values", [])
        return {item.get("key", ""): _attr_value(item.get("value")) for item in values if item.get("key")}
    return value


def _span_attributes(span: dict[str, Any]) -> dict[str, Any]:
    raw = span.get("attributes", {})
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        attrs: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("key"):
                attrs[str(item["key"])] = _attr_value(item.get("value"))
        return attrs
    return {}


def _first_attr(attrs: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = attrs.get(key)
        if value not in (None, ""):
            return value
    return None


def _path_value(item: dict[str, Any], path: list[str]) -> Any:
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_path(item: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        value = _path_value(item, path)
        if value not in (None, ""):
            return value
    return None


def _list_from_value(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _explicit_result(value: Any) -> str | None:
    result = _as_text(value).strip().lower()
    return result if result in {"pass", "fail", "unknown"} else None


def _explicit_action_key(value: Any, *, include_sensitive: bool) -> str | None:
    text = _as_text(value).strip()
    if not text:
        return None
    return redact_text(text, include_sensitive=include_sensitive)


def _span_status(span: dict[str, Any], attrs: dict[str, Any]) -> str:
    explicit = _explicit_result(_first_attr(attrs, ["hulun.event.result", "hulun.result"]))
    if explicit:
        return explicit
    status = span.get("status") or {}
    code = _as_text(status.get("code") if isinstance(status, dict) else status).lower()
    text = " ".join([code, _as_text(status.get("message") if isinstance(status, dict) else ""), _as_text(attrs.get("error.type"))])
    if any(marker in text.lower() for marker in FAIL_MARKERS) or "status_code_error" in code or code == "error":
        return "fail"
    label = _as_text(_first_attr(attrs, ["gen_ai.evaluation.score.label", "eval.label", "evaluation.score.label"])).lower()
    if label in {"fail", "failed", "incorrect", "not_relevant", "not relevant"}:
        return "fail"
    return "pass"


def _duration_ms(span: dict[str, Any]) -> int | None:
    start = _coerce_int(span.get("startTimeUnixNano") or span.get("start_time_unix_nano"))
    end = _coerce_int(span.get("endTimeUnixNano") or span.get("end_time_unix_nano"))
    if start is not None and end is not None and end >= start:
        return int((end - start) / 1_000_000)
    return None


def _span_ref(source: str, span: dict[str, Any]) -> list[str]:
    refs = []
    trace_id = _as_text(span.get("traceId") or span.get("trace_id")).strip()
    span_id = _as_text(span.get("spanId") or span.get("span_id")).strip()
    if trace_id:
        refs.append(f"{source}:trace:{trace_id}")
    if span_id:
        refs.append(f"{source}:span:{span_id}")
    return refs


def _span_action_key(source: str, span: dict[str, Any], attrs: dict[str, Any], *, include_sensitive: bool) -> str:
    explicit = _explicit_action_key(_first_attr(attrs, ["hulun.action_key", "hulun.event.action_key"]), include_sensitive=include_sensitive)
    if explicit:
        return explicit
    key = _first_attr(attrs, ["gen_ai.tool.call.id", "tool.call.id", "tool_call.id"])
    if key:
        return f"{source}:{redact_text(key, include_sensitive=include_sensitive)}"
    span_id = _as_text(span.get("spanId") or span.get("span_id")).strip()
    if span_id:
        return f"{source}:{span_id}"
    seed = f"{span.get('traceId') or span.get('trace_id')}:{span.get('name')}:{json.dumps(attrs, ensure_ascii=False, sort_keys=True)}"
    return fingerprint_text(seed, prefix=source)


def _telemetry_summary(source_label: str, span: dict[str, Any], attrs: dict[str, Any], *, include_sensitive: bool) -> str:
    hulun_summary = _first_attr(attrs, ["hulun.event.summary", "hulun.summary"])
    if hulun_summary not in (None, ""):
        return redact_text(hulun_summary, include_sensitive=include_sensitive)

    if include_sensitive:
        raw = _first_attr(
            attrs,
            [
                "gen_ai.input.messages",
                "gen_ai.output.messages",
                "gen_ai.system_instructions",
                "gen_ai.tool.call.arguments",
                "gen_ai.tool.call.result",
                "input.value",
                "output.value",
                "tool.parameters",
            ],
        )
        if raw not in (None, ""):
            return redact_text(raw, include_sensitive=True)

    operation = _as_text(_first_attr(attrs, ["gen_ai.operation.name", "openinference.span.kind"])).strip()
    model = _as_text(_first_attr(attrs, ["gen_ai.request.model", "gen_ai.response.model", "llm.model_name"])).strip()
    tool_name = _as_text(_first_attr(attrs, ["gen_ai.tool.name", "tool.name"])).strip()
    parts = [f"{source_label} span"]
    if operation:
        parts.append(operation)
    if tool_name:
        parts.append(f"tool={redact_text(tool_name)}")
    if model:
        parts.append(f"model={redact_text(model)}")
    name = _as_text(span.get("name")).strip()
    if name:
        parts.append(f"name={redact_text(name)}")
    return "; ".join(parts)


def _telemetry_kind(attrs: dict[str, Any]) -> str:
    return _as_text(_first_attr(attrs, ["openinference.span.kind", "gen_ai.operation.name", "span.kind"])).strip().lower()


def _telemetry_type_and_phase(attrs: dict[str, Any], *, result: str) -> tuple[str, str | None]:
    kind = _telemetry_kind(attrs)
    explicit_type = _as_text(_first_attr(attrs, ["hulun.event.type", "hulun.type"])).strip()
    explicit_phase = _normalize_phase(_first_attr(attrs, ["hulun.event.phase", "hulun.phase"]), kind)
    if explicit_type:
        return explicit_type, explicit_phase
    if any(key in attrs for key in ["gen_ai.tool.name", "gen_ai.tool.call.id", "gen_ai.tool.call.arguments", "tool.name", "tool.parameters"]):
        return "tool_result", explicit_phase or ("recover" if result == "fail" else "orchestrate")
    if "retriever" in kind or "retrieval" in kind or any(key.startswith("gen_ai.retrieval") for key in attrs):
        return "source", explicit_phase or "explore"
    if "eval" in kind or any(key.startswith("gen_ai.evaluation") for key in attrs):
        return "verification", explicit_phase or "verify"
    if result == "fail":
        return "agent_error", explicit_phase or "recover"
    if "llm" in kind or kind in {"chat", "text_completion", "generate_content"} or any(key.startswith("gen_ai.") for key in attrs):
        return "llm_call", explicit_phase or "orchestrate"
    if "chain" in kind or "agent" in kind:
        return "command", explicit_phase or "orchestrate"
    return "observation", explicit_phase


def normalize_opentelemetry(span: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    attrs = _span_attributes(span)
    result = _span_status(span, attrs)
    event_type, phase = _telemetry_type_and_phase(attrs, result=result)
    prompt_tokens = _coerce_int(_first_attr(attrs, ["gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt"]))
    completion_tokens = _coerce_int(
        _first_attr(attrs, ["gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion"])
    )
    return {
        "type": event_type,
        "summary": _telemetry_summary("OpenTelemetry GenAI", span, attrs, include_sensitive=include_sensitive),
        "result": result,
        "phase": phase,
        "claims": redact_list(_list_from_value(_first_attr(attrs, ["hulun.claims", "hulun.event.claims"])), include_sensitive=include_sensitive),
        "evidence": _list_from_value(_first_attr(attrs, ["hulun.evidence.ids", "hulun.event.evidence", "hulun.evidence"])),
        "refs": redact_refs(
            _span_ref("otel", span) + _list_from_value(_first_attr(attrs, ["hulun.refs", "hulun.event.refs", "hulun.ref"])),
            include_sensitive=include_sensitive,
        ),
        "resolved": None,
        "source_platform": "opentelemetry",
        "action_key": _span_action_key("otel", span, attrs, include_sensitive=include_sensitive),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": _coerce_float(_first_attr(attrs, ["hulun.cost", "gen_ai.usage.cost", "llm.cost.total", "cost.total"])),
        "latency_ms": _coerce_int(_first_attr(attrs, ["hulun.latency_ms", "gen_ai.latency_ms"])) or _duration_ms(span),
        "model": _as_text(_first_attr(attrs, ["gen_ai.request.model", "gen_ai.response.model", "llm.model_name"])).strip() or None,
    }


def normalize_openinference(span: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    attrs = _span_attributes(span)
    result = _span_status(span, attrs)
    event_type, phase = _telemetry_type_and_phase(attrs, result=result)
    observation = normalize_opentelemetry(span, include_sensitive=include_sensitive)
    observation.update(
        {
            "type": event_type,
            "summary": _telemetry_summary("OpenInference", span, attrs, include_sensitive=include_sensitive),
            "phase": phase,
            "source_platform": "openinference",
            "action_key": _span_action_key("openinference", span, attrs, include_sensitive=include_sensitive),
            "refs": redact_refs(
                _span_ref("openinference", span) + _list_from_value(_first_attr(attrs, ["hulun.refs", "hulun.event.refs", "hulun.ref"])),
                include_sensitive=include_sensitive,
            ),
        }
    )
    return observation


def normalize_langfuse(span: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    observation = normalize_opentelemetry(span, include_sensitive=include_sensitive)
    observation["source_platform"] = "langfuse"
    return observation


def normalize_phoenix(span: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    observation = normalize_openinference(span, include_sensitive=include_sensitive)
    observation["source_platform"] = "phoenix"
    return observation


def _result_from_text(text: str, default: str = "pass") -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in FAIL_MARKERS):
        return "fail"
    return default


def _phase_from_text(text: str, fallback: str | None = None) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ["pytest", "test", "verify", "validation", "lint"]):
        return "verify"
    if any(word in lowered for word in ["patch", "edit", "write", "modify", "apply"]):
        return "implement"
    if any(word in lowered for word in ["search", "read", "inspect", "open", "grep", "rg"]):
        return "explore"
    if any(word in lowered for word in ["summary", "final", "conclusion"]):
        return "summarize"
    return fallback


def _stable_action_key(text: str, fallback: str) -> str:
    parts = sorted(tokens(text))
    if not parts:
        return fallback
    return " ".join(parts[:8])


def _read_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                items.append(value)
        return items

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ["events", "steps", "trajectory", "messages", "observations"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _iter_items(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value
        return

    yield from _read_items(path)


def _iter_spans_from_payload(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_spans_from_payload(item)
        return
    if not isinstance(payload, dict):
        return
    if "resourceSpans" in payload:
        for resource_span in payload.get("resourceSpans") or []:
            yield from _iter_spans_from_payload(resource_span)
        return
    if "scopeSpans" in payload:
        for scope_span in payload.get("scopeSpans") or []:
            yield from _iter_spans_from_payload(scope_span)
        return
    if "spans" in payload and isinstance(payload.get("spans"), list):
        for span in payload["spans"]:
            if isinstance(span, dict):
                yield span
        return
    if "trace" in payload:
        yield from _iter_spans_from_payload(payload["trace"])
        return
    if "traces" in payload:
        yield from _iter_spans_from_payload(payload["traces"])
        return
    if "attributes" in payload or "spanId" in payload or "span_id" in payload:
        yield payload


def _iter_telemetry_spans(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    yield from _iter_spans_from_payload(json.loads(line))
        return
    yield from _iter_spans_from_payload(json.loads(path.read_text(encoding="utf-8-sig")))


def _normalize_phase(value: Any, text: str) -> str | None:
    phase = _as_text(value).strip().lower().replace("-", "_")
    aliases = {
        "coding": "implement",
        "execute": "implement",
        "execution": "implement",
        "reflection": "summarize",
        "review": "verify",
        "testing": "verify",
    }
    phase = aliases.get(phase, phase)
    if phase in VALID_EVENT_PHASES:
        return phase
    return _phase_from_text(text)


def normalize_generic(item: dict[str, Any], *, source_platform: str = "generic", include_sensitive: bool = False) -> Observation:
    raw_text = _first_text(item, ["summary", *TRACE_TEXT_KEYS])
    text = safe_summary_from_trace(item, include_sensitive=include_sensitive)
    event_type = _as_text(item.get("type") or item.get("event_type") or "observation").strip() or "observation"
    claims = item.get("claims", item.get("claim", []))
    if isinstance(claims, str):
        claims = [claims]
    if not isinstance(claims, list):
        claims = []
    evidence = item.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []
    refs = item.get("refs", item.get("ref", []))
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list):
        refs = []

    result = _as_text(item.get("result") or "").strip().lower()
    if result not in {"pass", "fail", "unknown"}:
        result = _result_from_text(raw_text or text, default="unknown")
    action_key = _as_text(item.get("action_key") or "").strip()
    if not action_key and raw_text and not include_sensitive:
        action_key = fingerprint_text(raw_text, prefix=source_platform)

    return {
        "type": event_type,
        "summary": text,
        "result": result,
        "phase": _normalize_phase(item.get("phase"), raw_text or text),
        "claims": [redact_text(claim, include_sensitive=include_sensitive) for claim in claims if str(claim).strip()],
        "evidence": [str(eid).strip() for eid in evidence if str(eid).strip()],
        "refs": redact_refs([str(ref).strip() for ref in refs if str(ref).strip()], include_sensitive=include_sensitive),
        "resolved": bool(item.get("resolved")) if "resolved" in item else None,
        "source_platform": _as_text(item.get("source_platform") or source_platform),
        "action_key": redact_text(action_key, include_sensitive=include_sensitive) or None,
        "prompt_tokens": _coerce_int(item.get("prompt_tokens")),
        "completion_tokens": _coerce_int(item.get("completion_tokens")),
        "cost": _coerce_float(item.get("cost")),
        "latency_ms": _coerce_int(item.get("latency_ms")),
        "model": _as_text(item.get("model") or "").strip() or None,
    }


def normalize_openhands(item: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    raw_type = _first_text(item, ["type", "event_type", "class", "name"]).lower()
    text = _first_text(item, ["message", "error", "observation", "content", "thought", "action"]) or raw_type or "OpenHands event."
    explicit_result = _explicit_result(item.get("result"))
    explicit_phase = _normalize_phase(item.get("phase"), text)
    explicit_action_key = _explicit_action_key(item.get("action_key"), include_sensitive=include_sensitive)

    if "error" in raw_type:
        event_type = "conversation_error" if "conversation" in raw_type else "agent_error"
        result = explicit_result or "fail"
        phase = explicit_phase or "recover"
    elif "condensation" in raw_type or "summary" in raw_type:
        event_type = "summary"
        result = explicit_result or "pass"
        phase = explicit_phase or "summarize"
    elif "observation" in raw_type:
        event_type = "tool_result"
        result = explicit_result or _result_from_text(text)
        phase = explicit_phase or _phase_from_text(text, "orchestrate")
    elif "action" in raw_type:
        event_type = "command"
        result = explicit_result or "unknown"
        phase = explicit_phase or _phase_from_text(text, "orchestrate")
    else:
        return normalize_generic(item, source_platform="openhands", include_sensitive=include_sensitive)

    action_key = explicit_action_key or (_stable_action_key(text, raw_type or event_type) if include_sensitive else fingerprint_text(text, prefix="openhands"))
    return {
        **normalize_generic(item, source_platform="openhands", include_sensitive=include_sensitive),
        "type": event_type,
        "summary": redact_text(text, include_sensitive=True) if include_sensitive else safe_summary_from_trace(item, fallback=f"Imported {event_type} observation; sensitive payload withheld."),
        "result": result,
        "phase": phase,
        "action_key": action_key,
    }


def normalize_swe_agent(item: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    action = _first_text(item, ["action", "command", "tool_call"])
    observation = _first_text(item, ["observation", "result", "tool_result", "output"])
    thought = _first_text(item, ["thought", "response", "message"])
    text = " | ".join(part for part in [action, observation, thought] if part).strip() or "SWE-agent trajectory step."
    explicit_result = _explicit_result(item.get("result"))
    result = explicit_result or _result_from_text(observation or text, default="pass" if observation else "unknown")
    event_type = "tool_result" if observation else "command"
    explicit_action_key = _explicit_action_key(item.get("action_key"), include_sensitive=include_sensitive)
    action_key = explicit_action_key or (_stable_action_key(action or text, "swe-agent-step") if include_sensitive else fingerprint_text(action or text, prefix="swe-agent"))
    return {
        **normalize_generic(item, source_platform="swe-agent", include_sensitive=include_sensitive),
        "type": event_type,
        "summary": redact_text(text, include_sensitive=True) if include_sensitive else safe_summary_from_trace(item, fallback=f"Imported {event_type} observation; sensitive payload withheld."),
        "result": result,
        "phase": _normalize_phase(item.get("phase"), text) or _phase_from_text(text, "orchestrate"),
        "action_key": action_key,
    }


def normalize_langgraph(item: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    stream_type = _first_text(item, ["type", "stream_mode", "event"]).lower()
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    data_text = safe_summary_from_trace(data, include_sensitive=include_sensitive, fallback="")
    raw_text = _first_text(item, ["summary", "message", "content", "text", "status"]) or data_text or stream_type or "LangGraph stream part."
    base = normalize_generic(item, source_platform="langgraph", include_sensitive=include_sensitive)
    explicit_type = _as_text(item.get("event_type") or item.get("hulun_type") or "").strip()
    if explicit_type:
        event_type = explicit_type
    elif stream_type == "messages":
        event_type = "llm_call"
    elif stream_type == "tasks":
        event_type = "tool_result" if base["result"] != "unknown" else "command"
    elif stream_type == "checkpoints":
        event_type = "checkpoint"
    elif stream_type == "debug":
        event_type = "observation"
    elif stream_type in {"updates", "values", "custom"}:
        event_type = "observation"
    else:
        event_type = base["type"]
    action_key = base.get("action_key") or fingerprint_text(raw_text, prefix="langgraph")
    summary = redact_text(raw_text, include_sensitive=True) if include_sensitive else safe_summary_from_trace(item, fallback=f"Imported LangGraph {event_type} observation; sensitive payload withheld.")
    return {
        **base,
        "type": event_type,
        "summary": summary,
        "phase": base.get("phase") or _phase_from_text(raw_text, "orchestrate"),
        "action_key": action_key,
    }


def normalize_langsmith(item: dict[str, Any], *, include_sensitive: bool = False) -> Observation:
    run_type = _as_text(item.get("run_type") or item.get("type") or item.get("serialized", {}).get("name")).strip().lower()
    name = _first_text(item, ["name", "display_name", "dotted_order"]) or run_type or "LangSmith run"
    error = _first_text(item, ["error"])
    base = normalize_generic(item, source_platform="langsmith", include_sensitive=include_sensitive)
    if error:
        result = "fail"
    else:
        result = base["result"] if base["result"] != "unknown" else "pass"
    if run_type in {"llm", "chat_model"}:
        event_type = "llm_call"
    elif run_type == "tool":
        event_type = "tool_result"
    elif run_type == "retriever":
        event_type = "source"
    elif result == "fail":
        event_type = "agent_error"
    else:
        event_type = "command"
    refs = list(base.get("refs") or [])
    run_id = _as_text(item.get("id") or item.get("run_id")).strip()
    trace_id = _as_text(item.get("trace_id") or item.get("traceId")).strip()
    if run_id:
        refs.append(f"langsmith:run:{run_id}")
    if trace_id:
        refs.append(f"langsmith:trace:{trace_id}")
    prompt_tokens = base.get("prompt_tokens") or _coerce_int(_first_path(item, [["usage_metadata", "input_tokens"], ["usage", "prompt_tokens"], ["extra", "usage", "prompt_tokens"]]))
    completion_tokens = base.get("completion_tokens") or _coerce_int(
        _first_path(item, [["usage_metadata", "output_tokens"], ["usage", "completion_tokens"], ["extra", "usage", "completion_tokens"]])
    )
    latency_ms = base.get("latency_ms") or _coerce_int(item.get("latency_ms"))
    model = base.get("model") or _as_text(_first_path(item, [["invocation_params", "model"], ["extra", "invocation_params", "model"], ["metadata", "model"]])).strip() or None
    summary_source = error or _first_text(item, ["summary"]) or name
    summary = redact_text(summary_source, include_sensitive=True) if include_sensitive else redact_text(summary_source, include_sensitive=False)
    return {
        **base,
        "type": event_type,
        "summary": summary,
        "result": result,
        "phase": base.get("phase") or _phase_from_text(" ".join([run_type, name, error]), "orchestrate"),
        "refs": redact_refs(refs, include_sensitive=include_sensitive),
        "action_key": base.get("action_key") or (f"langsmith:{run_id}" if run_id else fingerprint_text(name, prefix="langsmith")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "model": model,
    }


def validate_trace_file(path: str | Path, *, max_trace_bytes: int = MAX_TRACE_BYTES) -> Path:
    trace_path = Path(path)
    if not trace_path.exists():
        raise SystemExit(f"Trace file does not exist: {trace_path}")
    if not trace_path.is_file():
        raise SystemExit(f"Trace path is not a file: {trace_path}")
    try:
        size = trace_path.stat().st_size
    except OSError as exc:
        raise SystemExit(f"Cannot inspect trace file: {trace_path}: {exc}") from exc
    limit = max(1, int(max_trace_bytes))
    if size > limit:
        raise SystemExit(f"Trace file is too large: {trace_path} is {size} bytes, limit is {limit} bytes.")
    return trace_path


def load_observations(path: str | Path, source_format: str = "auto", *, include_sensitive: bool = False, max_trace_bytes: int = MAX_TRACE_BYTES) -> list[Observation]:
    return list(iter_observations(path, source_format, include_sensitive=include_sensitive, max_trace_bytes=max_trace_bytes))


def iter_observations(
    path: str | Path,
    source_format: str = "auto",
    *,
    include_sensitive: bool = False,
    max_trace_bytes: int = MAX_TRACE_BYTES,
) -> Iterator[Observation]:
    trace_path = validate_trace_file(path, max_trace_bytes=max_trace_bytes)
    fmt = source_format.lower()
    if fmt == "auto":
        lowered = trace_path.name.lower()
        if "langgraph" in lowered:
            fmt = "langgraph"
        elif "langsmith" in lowered:
            fmt = "langsmith"
        elif "langfuse" in lowered:
            fmt = "langfuse"
        elif "phoenix" in lowered:
            fmt = "phoenix"
        elif "openinference" in lowered:
            fmt = "openinference"
        elif "opentelemetry" in lowered or "otel" in lowered or "otlp" in lowered:
            fmt = "opentelemetry"
        elif "openhands" in lowered:
            fmt = "openhands"
        elif "swe" in lowered or "traj" in lowered:
            fmt = "swe-agent"
        else:
            fmt = "generic"

    normalizers = {
        "generic": normalize_generic,
        "openhands": normalize_openhands,
        "opentelemetry": normalize_opentelemetry,
        "openinference": normalize_openinference,
        "swe-agent": normalize_swe_agent,
        "langgraph": normalize_langgraph,
        "langsmith": normalize_langsmith,
        "langfuse": normalize_langfuse,
        "phoenix": normalize_phoenix,
    }
    if fmt not in normalizers:
        raise SystemExit(f"Unsupported trace format: {source_format}")
    normalizer = normalizers[fmt]
    if fmt in {"opentelemetry", "openinference", "langfuse", "phoenix"}:
        for span in _iter_telemetry_spans(trace_path):
            yield normalizer(span, include_sensitive=include_sensitive)
        return
    for item in _iter_items(trace_path):
        yield normalizer(item, include_sensitive=include_sensitive)


def _hex_id(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:length]


def _otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_otlp_value(item) for item in value]}}
    if isinstance(value, dict):
        return {"kvlistValue": {"values": [{"key": str(key), "value": _otlp_value(val)} for key, val in value.items()]}}
    return {"stringValue": "" if value is None else str(value)}


def _otlp_attr(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": _otlp_value(value)}


def _event_time_nanos(event: dict[str, Any]) -> str:
    parsed = parse_time(event.get("created_at"))
    if parsed is None:
        return "0"
    return str(int(parsed.timestamp() * 1_000_000_000))


def export_opentelemetry(state: dict[str, Any], *, version: str = "unknown") -> dict[str, Any]:
    trace_id = _hex_id(state.get("objective", "hulun"), 32)
    spans = []
    for event in state.get("events", []):
        event_id = str(event.get("id", "event"))
        attrs = [
            _otlp_attr("hulun.event.id", event_id),
            _otlp_attr("hulun.event.type", event.get("type", "event")),
            _otlp_attr("hulun.event.result", event.get("result", "unknown")),
            _otlp_attr("hulun.event.summary", event.get("summary", "")),
        ]
        if event.get("phase"):
            attrs.append(_otlp_attr("hulun.event.phase", event["phase"]))
            attrs.append(_otlp_attr("gen_ai.operation.name", event["phase"]))
        if event.get("model"):
            attrs.append(_otlp_attr("gen_ai.request.model", event["model"]))
        if event.get("prompt_tokens") is not None:
            attrs.append(_otlp_attr("gen_ai.usage.input_tokens", int(event["prompt_tokens"])))
        if event.get("completion_tokens") is not None:
            attrs.append(_otlp_attr("gen_ai.usage.output_tokens", int(event["completion_tokens"])))
        if event.get("cost") is not None:
            attrs.append(_otlp_attr("hulun.cost", float(event["cost"])))
        if event.get("latency_ms") is not None:
            attrs.append(_otlp_attr("hulun.latency_ms", int(event["latency_ms"])))
        if event.get("action_key"):
            attrs.append(_otlp_attr("hulun.action_key", event["action_key"]))
        if event.get("claims"):
            attrs.append(_otlp_attr("hulun.claims", event["claims"]))
        if event.get("evidence"):
            attrs.append(_otlp_attr("hulun.evidence.ids", event["evidence"]))
        if event.get("refs"):
            attrs.append(_otlp_attr("hulun.refs", event["refs"]))
        if event.get("privacy"):
            attrs.append(_otlp_attr("hulun.privacy.mode", event["privacy"].get("mode")))
            attrs.append(_otlp_attr("hulun.privacy.retention_days", event["privacy"].get("retention_days")))
        status = {"code": "STATUS_CODE_ERROR"} if event.get("result") == "fail" else {"code": "STATUS_CODE_OK"}
        time_nanos = _event_time_nanos(event)
        spans.append(
            {
                "traceId": trace_id,
                "spanId": _hex_id(f"{trace_id}:{event_id}", 16),
                "name": f"hulun.{event.get('type', 'event')}",
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": time_nanos,
                "endTimeUnixNano": time_nanos,
                "attributes": attrs,
                "status": status,
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_otlp_attr("service.name", "hulunguard")]},
                "scopeSpans": [{"scope": {"name": "hulun_guard", "version": version}, "spans": spans}],
            }
        ]
    }
