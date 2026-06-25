from __future__ import annotations

import json
from collections import Counter
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .adapters import MAX_TRACE_BYTES, _looks_like_phoenix_cli_payload, iter_observations
from .privacy import DEFAULT_RETENTION_DAYS
from .schemas import SERVICE_EXPORT_SCHEMA, TRACE_DOCTOR_SCHEMA
from .util import utc_now

TRACE_FORMATS = (
    "auto",
    "generic",
    "opentelemetry",
    "openinference",
    "openhands",
    "swe-agent",
    "langgraph",
    "langsmith",
    "langfuse",
    "phoenix",
    "openai-agents",
)

EXPLICIT_TRACE_FORMATS = tuple(item for item in TRACE_FORMATS if item != "auto")


def _format_hint_from_name(path: Path) -> str | None:
    name = path.name.lower()
    hints = (
        ("langgraph", "langgraph"),
        ("langsmith", "langsmith"),
        ("openai-agents", "openai-agents"),
        ("openai_agents", "openai-agents"),
        ("openai", "openai-agents"),
        ("langfuse", "langfuse"),
        ("phoenix", "phoenix"),
        ("openinference", "openinference"),
        ("opentelemetry", "opentelemetry"),
        ("otlp", "opentelemetry"),
        ("otel", "opentelemetry"),
        ("openhands", "openhands"),
        ("swe-agent", "swe-agent"),
        ("swe_agent", "swe-agent"),
        ("trajectory", "swe-agent"),
        ("traj", "swe-agent"),
    )
    for needle, fmt in hints:
        if needle in name:
            return fmt
    return None


def _read_probe(path: Path, *, max_items: int = 50) -> Any:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        items = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                items.append(json.loads(line))
                if len(items) >= max_items:
                    break
        return items
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        items.append(value)
        for child in value.values():
            if isinstance(child, (dict, list)):
                items.extend(_iter_dicts(child))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                items.extend(_iter_dicts(item))
    return items


def _has_nested_key(value: Any, key: str) -> bool:
    return any(key in item for item in _iter_dicts(value))


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("events", "steps", "trajectory", "messages", "observations", "runs", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [value]
    return []


def _span_attrs(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("attributes")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        attrs: dict[str, Any] = {}
        for attr in raw:
            if isinstance(attr, dict) and attr.get("key"):
                attrs[str(attr["key"])] = attr.get("value")
        return attrs
    return {}


def detect_trace_format(path: str | Path, payload: Any | None = None) -> str:
    trace_path = Path(path)
    name_hint = _format_hint_from_name(trace_path)
    probe = payload if payload is not None else _read_probe(trace_path)
    dicts = _iter_dicts(probe)
    items = _dict_items(probe)

    if (
        isinstance(probe, dict)
        and probe.get("schema") == SERVICE_EXPORT_SCHEMA
        and probe.get("provider") == "langfuse"
        and isinstance(probe.get("observations"), list)
    ):
        return "generic"

    if _looks_like_phoenix_cli_payload(probe):
        return "phoenix"

    if _has_nested_key(probe, "resourceSpans"):
        return name_hint if name_hint in {"langfuse", "opentelemetry"} else "opentelemetry"

    if any(item.get("object") == "trace.span" or isinstance(item.get("span_data"), dict) for item in dicts):
        return "openai-agents"

    if any("openinference.span.kind" in _span_attrs(item) for item in dicts):
        return name_hint if name_hint in {"phoenix", "openinference"} else "openinference"

    if isinstance(probe, dict) and isinstance(probe.get("trajectory"), list):
        return "swe-agent"

    if any(item.get("run_type") or item.get("dotted_order") for item in items):
        return "langsmith"

    stream_markers = {"messages", "updates", "values", "tasks", "debug", "custom", "checkpoints"}
    if any(str(item.get("type") or item.get("stream_mode") or item.get("event") or "").lower() in stream_markers for item in items):
        return "langgraph"

    if any(str(item.get("class") or item.get("type") or item.get("event_type") or "").lower().find("observation") >= 0 for item in items):
        return "openhands"

    if any(item.get("action") and item.get("observation") for item in items):
        return "swe-agent"

    return name_hint or "generic"


def _quote_arg(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _next_ingest_command(path: Path, fmt: str, *, include_sensitive: bool, retention_days: int, max_trace_bytes: int) -> str:
    parts = [
        "python",
        "-m",
        "hulun_guard",
        "ingest",
        "--format",
        fmt,
        "--file",
        _quote_arg(str(path)),
        "--scan",
        "--init-if-missing",
    ]
    if include_sensitive:
        parts.append("--include-sensitive")
    if retention_days != DEFAULT_RETENTION_DAYS:
        parts.extend(["--retention-days", str(retention_days)])
    if max_trace_bytes != MAX_TRACE_BYTES:
        parts.extend(["--max-trace-bytes", str(max_trace_bytes)])
    return " ".join(parts)


def _field_coverage(observations: list[dict[str, Any]], field: str) -> dict[str, Any]:
    present = sum(1 for item in observations if item.get(field) not in (None, "", []))
    total = len(observations)
    ratio = round(present / total, 4) if total else 0.0
    return {"present": present, "total": total, "ratio": ratio}


def _sample_observations(observations: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    sample = []
    for item in observations[: max(0, sample_size)]:
        sample.append(
            {
                "type": item.get("type"),
                "result": item.get("result"),
                "phase": item.get("phase"),
                "source_platform": item.get("source_platform"),
                "summary": item.get("summary"),
                "has_action_key": bool(item.get("action_key")),
                "evidence_count": len(item.get("evidence") or []),
                "ref_count": len(item.get("refs") or []),
            }
        )
    return sample


def _counter(values: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value or "missing") for value in values).items()))


def _quality_warnings(observations: list[dict[str, Any]], *, selected_format: str, include_sensitive: bool, size_bytes: int, max_trace_bytes: int) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if selected_format == "generic":
        warnings.append(
            {
                "code": "generic_bridge",
                "detail": "The trace uses the generic bridge; native adapter fields may be unavailable.",
            }
        )
    if include_sensitive:
        warnings.append(
            {
                "code": "sensitive_mode",
                "detail": "Sensitive mode is enabled; only use it for trusted local debugging.",
            }
        )
    if size_bytes >= int(max_trace_bytes * 0.8):
        warnings.append(
            {
                "code": "near_size_limit",
                "detail": f"Trace size is near the configured {max_trace_bytes} byte limit.",
            }
        )
    if observations and not any(item.get("phase") for item in observations):
        warnings.append({"code": "missing_phase", "detail": "No observations include a phase; risk phase signals will be weaker."})
    if observations and not any(item.get("action_key") for item in observations):
        warnings.append({"code": "missing_action_key", "detail": "No observations include action_key; retry-loop detection will be weaker."})
    if observations and not any(item.get("evidence") or item.get("refs") for item in observations):
        warnings.append({"code": "missing_external_refs", "detail": "No observations include evidence ids or refs; final-claim evidence checks will be weaker."})
    return warnings


def diagnose_trace_file(
    path: str | Path,
    *,
    source_format: str = "auto",
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_trace_bytes: int = MAX_TRACE_BYTES,
    sample_size: int = 3,
    strict: bool = False,
) -> dict[str, Any]:
    trace_path = Path(path)
    failures: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    file_info = {
        "path": str(trace_path),
        "name": trace_path.name,
        "size_bytes": 0,
        "max_trace_bytes": max_trace_bytes,
    }

    if source_format not in TRACE_FORMATS:
        failures.append({"code": "unsupported_format", "detail": f"Unsupported trace format: {source_format}"})

    if not trace_path.exists():
        failures.append({"code": "file_missing", "detail": f"Trace file does not exist: {trace_path}"})
    elif not trace_path.is_file():
        failures.append({"code": "not_file", "detail": f"Trace path is not a file: {trace_path}"})
    else:
        try:
            file_info["size_bytes"] = trace_path.stat().st_size
        except OSError as exc:
            failures.append({"code": "stat_failed", "detail": str(exc)})
        if file_info["size_bytes"] > max_trace_bytes:
            failures.append(
                {
                    "code": "file_too_large",
                    "detail": f"Trace file is {file_info['size_bytes']} bytes, limit is {max_trace_bytes} bytes.",
                }
            )

    probe: Any | None = None
    detected_format = "unknown"
    if not failures:
        try:
            probe = _read_probe(trace_path)
            detected_format = detect_trace_format(trace_path, probe)
        except JSONDecodeError as exc:
            failures.append({"code": "json_invalid", "detail": str(exc)})
        except OSError as exc:
            failures.append({"code": "read_failed", "detail": str(exc)})

    selected_format = detected_format if source_format == "auto" else source_format
    observations: list[dict[str, Any]] = []
    if not failures:
        try:
            observations = list(
                iter_observations(
                    trace_path,
                    selected_format,
                    include_sensitive=include_sensitive,
                    max_trace_bytes=max_trace_bytes,
                )
            )
        except (JSONDecodeError, OSError, SystemExit, TypeError, ValueError) as exc:
            failures.append({"code": "adapter_failed", "detail": str(exc)})
    if not failures and not observations:
        failures.append({"code": "no_observations", "detail": "The selected adapter produced zero observations."})

    if observations:
        warnings.extend(
            _quality_warnings(
                observations,
                selected_format=selected_format,
                include_sensitive=include_sensitive,
                size_bytes=int(file_info["size_bytes"]),
                max_trace_bytes=max_trace_bytes,
            )
        )

    strict_failures = [{"code": f"strict_{item['code']}", "detail": item["detail"]} for item in warnings] if strict else []
    all_failures = [*failures, *strict_failures]
    field_coverage = {
        "phase": _field_coverage(observations, "phase"),
        "action_key": _field_coverage(observations, "action_key"),
        "evidence": _field_coverage(observations, "evidence"),
        "refs": _field_coverage(observations, "refs"),
        "model": _field_coverage(observations, "model"),
        "prompt_tokens": _field_coverage(observations, "prompt_tokens"),
        "completion_tokens": _field_coverage(observations, "completion_tokens"),
    }

    return {
        "schema": TRACE_DOCTOR_SCHEMA,
        "generated_at": utc_now(),
        "file": file_info,
        "detected_format": detected_format,
        "selected_format": selected_format,
        "privacy": {
            "mode": "sensitive-opt-in" if include_sensitive else "redacted-default",
            "retention_days": retention_days,
        },
        "observation_count": len(observations),
        "type_counts": _counter([item.get("type") for item in observations]),
        "result_counts": _counter([item.get("result") for item in observations]),
        "phase_counts": _counter([item.get("phase") for item in observations]),
        "source_platform_counts": _counter([item.get("source_platform") for item in observations]),
        "field_coverage": field_coverage,
        "sample_observations": _sample_observations(observations, sample_size),
        "next_command": _next_ingest_command(
            trace_path,
            selected_format if selected_format != "unknown" else "generic",
            include_sensitive=include_sensitive,
            retention_days=retention_days,
            max_trace_bytes=max_trace_bytes,
        ),
        "warnings": warnings,
        "gate": {
            "passed": not all_failures,
            "failure_count": len(all_failures),
            "failures": all_failures,
            "strict": strict,
        },
    }


def trace_doctor_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
