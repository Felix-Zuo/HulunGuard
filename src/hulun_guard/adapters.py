from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .constants import VALID_EVENT_PHASES
from .util import tokens

Observation = dict[str, Any]


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
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                items.append(value)
        return items

    payload = json.loads(path.read_text(encoding="utf-8"))
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
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value
        return

    yield from _read_items(path)


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


def normalize_generic(item: dict[str, Any], *, source_platform: str = "generic") -> Observation:
    text = _first_text(item, ["summary", "message", "content", "text", "observation", "response"]) or "Imported observation."
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
        result = _result_from_text(text, default="unknown")

    return {
        "type": event_type,
        "summary": text,
        "result": result,
        "phase": _normalize_phase(item.get("phase"), text),
        "claims": [str(claim).strip() for claim in claims if str(claim).strip()],
        "evidence": [str(eid).strip() for eid in evidence if str(eid).strip()],
        "refs": [str(ref).strip() for ref in refs if str(ref).strip()],
        "resolved": bool(item.get("resolved")) if "resolved" in item else None,
        "source_platform": _as_text(item.get("source_platform") or source_platform),
        "action_key": _as_text(item.get("action_key") or "").strip() or None,
        "prompt_tokens": _coerce_int(item.get("prompt_tokens")),
        "completion_tokens": _coerce_int(item.get("completion_tokens")),
        "cost": _coerce_float(item.get("cost")),
        "latency_ms": _coerce_int(item.get("latency_ms")),
        "model": _as_text(item.get("model") or "").strip() or None,
    }


def normalize_openhands(item: dict[str, Any]) -> Observation:
    raw_type = _first_text(item, ["type", "event_type", "class", "name"]).lower()
    text = _first_text(item, ["message", "error", "observation", "content", "thought", "action"]) or raw_type or "OpenHands event."

    if "error" in raw_type:
        event_type = "conversation_error" if "conversation" in raw_type else "agent_error"
        result = "fail"
        phase = "recover"
    elif "condensation" in raw_type or "summary" in raw_type:
        event_type = "summary"
        result = "pass"
        phase = "summarize"
    elif "observation" in raw_type:
        event_type = "tool_result"
        result = _result_from_text(text)
        phase = _phase_from_text(text, "orchestrate")
    elif "action" in raw_type:
        event_type = "command"
        result = "unknown"
        phase = _phase_from_text(text, "orchestrate")
    else:
        return normalize_generic(item, source_platform="openhands")

    return {
        **normalize_generic(item, source_platform="openhands"),
        "type": event_type,
        "summary": text,
        "result": result,
        "phase": phase,
        "action_key": _stable_action_key(text, raw_type or event_type),
    }


def normalize_swe_agent(item: dict[str, Any]) -> Observation:
    action = _first_text(item, ["action", "command", "tool_call"])
    observation = _first_text(item, ["observation", "result", "tool_result", "output"])
    thought = _first_text(item, ["thought", "response", "message"])
    text = " | ".join(part for part in [action, observation, thought] if part).strip() or "SWE-agent trajectory step."
    result = _result_from_text(observation or text, default="pass" if observation else "unknown")
    event_type = "tool_result" if observation else "command"
    return {
        **normalize_generic(item, source_platform="swe-agent"),
        "type": event_type,
        "summary": text,
        "result": result,
        "phase": _phase_from_text(text, "orchestrate"),
        "action_key": _stable_action_key(action or text, "swe-agent-step"),
    }


def load_observations(path: str | Path, source_format: str = "auto") -> list[Observation]:
    return list(iter_observations(path, source_format))


def iter_observations(path: str | Path, source_format: str = "auto") -> Iterator[Observation]:
    trace_path = Path(path)
    if not trace_path.exists():
        raise SystemExit(f"Trace file does not exist: {trace_path}")
    fmt = source_format.lower()
    if fmt == "auto":
        lowered = trace_path.name.lower()
        if "openhands" in lowered:
            fmt = "openhands"
        elif "swe" in lowered or "traj" in lowered:
            fmt = "swe-agent"
        else:
            fmt = "generic"

    normalizers = {
        "generic": normalize_generic,
        "openhands": normalize_openhands,
        "swe-agent": normalize_swe_agent,
    }
    if fmt not in normalizers:
        raise SystemExit(f"Unsupported trace format: {source_format}")
    normalizer = normalizers[fmt]
    for item in _iter_items(trace_path):
        yield normalizer(item)
