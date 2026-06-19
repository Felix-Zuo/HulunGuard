from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .constants import CONVERSATIONS_DIR, FAILURE_EVENT_TYPES, USEFUL_EVENT_TYPES
from .monitor import create_monitor, hulun_home, launch_widget, update_monitor
from .privacy import DEFAULT_RETENTION_DAYS, sanitize_event
from .risk import band_for
from .util import age_minutes, clamp_score, next_counter_id, next_id, utc_now

CONVERSATION_USEFUL_TYPES = USEFUL_EVENT_TYPES | {
    "assistant_checkpoint",
    "checkpoint",
    "file_change",
    "git_commit",
    "tool_result",
    "verification",
}
CONVERSATION_FAILURE_TYPES = FAILURE_EVENT_TYPES | {
    "tool_call",
    "tool_result",
    "command",
    "agent_error",
}
CLAIM_TYPES = {"assistant_claim", "final_attempt"}
POLISH_TYPES = {"assistant_summary", "summary", "assistant_update"}
USER_CHALLENGE_TYPES = {"user_challenge", "user_correction", "user_objection"}
LOCK_TIMEOUT_SECONDS = 10.0
STALE_LOCK_SECONDS = 120.0
LOCK_POLL_SECONDS = 0.025


def conversations_dir() -> Path:
    path = hulun_home() / CONVERSATIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def conversation_path(conversation_id: str) -> Path:
    return conversations_dir() / f"{conversation_id}.json"


def new_conversation_id() -> str:
    existing = [{"id": path.stem} for path in conversations_dir().glob("C*.json")]
    return next_id(existing, "C")


def load_conversation(conversation_id: str) -> dict[str, Any]:
    path = conversation_path(conversation_id)
    if not path.exists():
        raise SystemExit(f"Unknown conversation id: {conversation_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


@contextmanager
def conversation_write_lock(conversation_id: str) -> Any:
    lock_path = conversation_path(conversation_id).with_suffix(".json.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if lock_age > STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise SystemExit(f"Timed out waiting for conversation lock: {lock_path}")
            time.sleep(LOCK_POLL_SECONDS)
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()} created_at={utc_now()}\n")
            break
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def save_conversation(data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    _atomic_write_json(conversation_path(data["id"]), data)


def start_conversation(
    *,
    name: str,
    group: str,
    root: str,
    objective: str | None = None,
    monitor: bool = False,
    widget: bool = False,
) -> dict[str, Any]:
    now = utc_now()
    data = {
        "schema": "hulun.conversation.v1",
        "id": new_conversation_id(),
        "name": name,
        "group": group,
        "root": str(Path(root).resolve()),
        "objective": objective or name,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "events": [],
        "last_scan": None,
        "monitor_id": None,
    }
    append_conversation_event(data, "conversation_start", f"Conversation started: {name}", result="pass")
    risk = scan_conversation(data)
    data["last_scan"] = risk
    if monitor:
        monitor_data = create_monitor(
            name,
            group,
            root,
            int(risk["score"]),
            reasons=risk["reasons"],
            risk_source="conversation",
            conversation_id=data["id"],
        )
        data["monitor_id"] = monitor_data["id"]
        if widget:
            launch_widget(monitor_data["id"])
    save_conversation(data)
    return data


def append_conversation_event(
    data: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    phase: str | None = None,
    claims: list[str] | None = None,
    evidence: list[str] | None = None,
    refs: list[str] | None = None,
    resolved: bool | None = None,
    action_key: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    event = {
        "id": next_counter_id(data, "events", "EV"),
        "type": event_type,
        "summary": summary.strip(),
        "result": result,
        "created_at": utc_now(),
    }
    optional = {
        "phase": phase,
        "claims": claims or [],
        "evidence": evidence or [],
        "refs": refs or [],
        "resolved": resolved,
        "action_key": action_key,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
        "model": model,
    }
    for key, value in optional.items():
        if value not in (None, "", []):
            event[key] = value
    event = sanitize_event(event, include_sensitive=include_sensitive, retention_days=retention_days)
    data.setdefault("events", []).append(event)
    return event


def _ratio(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return part / whole


def _recent(data: dict[str, Any], count: int = 10) -> list[dict[str, Any]]:
    return data.get("events", [])[-count:]


def _has_evidence(event: dict[str, Any]) -> bool:
    return bool(event.get("evidence")) or event.get("type") in {"evidence", "verification", "git_commit", "file_change"}


def _is_claim(event: dict[str, Any]) -> bool:
    return bool(event.get("claims")) or event.get("type") in CLAIM_TYPES or event.get("phase") == "final"


def _has_recent_evidence(data: dict[str, Any]) -> bool:
    return any(_has_evidence(event) and event.get("result", "pass") != "fail" for event in _recent(data, 12))


def _claim_events(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in _recent(data, 12) if _is_claim(event)]


def _unsupported_claim_events(data: dict[str, Any]) -> list[dict[str, Any]]:
    recent_evidence = _has_recent_evidence(data)
    return [event for event in _claim_events(data) if not _has_evidence(event) and not recent_evidence]


def _unresolved_failure_events(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in data.get("events", [])
        if event.get("type") in CONVERSATION_FAILURE_TYPES and event.get("result") == "fail" and not event.get("resolved")
    ]


def _pending_tool_ids(data: dict[str, Any]) -> dict[str, str]:
    pending: dict[str, str] = {}
    for event in data.get("events", []):
        key = event.get("action_key") or event.get("id")
        str_key = str(key)
        if event.get("type") == "tool_call":
            pending[str_key] = event["id"]
        elif event.get("type") == "tool_result" and str_key in pending:
            pending.pop(str_key, None)
    return pending


def _score_claim_overhang(data: dict[str, Any]) -> tuple[float, list[str]]:
    claim_events = _claim_events(data)
    if not claim_events:
        return 0.0, []
    unsupported = _unsupported_claim_events(data)
    score = 30.0 * _ratio(len(unsupported), len(claim_events))
    if unsupported:
        return score, [f"Conversation claims lack nearby evidence: {', '.join(event['id'] for event in unsupported[-4:])}."]
    return 0.0, []


def _score_unresolved_failures(data: dict[str, Any]) -> tuple[float, list[str]]:
    failures = _unresolved_failure_events(data)
    score = min(24.0, 8.0 * len(failures))
    if failures:
        return score, [f"Conversation has unresolved failed events: {', '.join(event['id'] for event in failures[-4:])}."]
    return 0.0, []


def _score_pending_tools(data: dict[str, Any]) -> tuple[float, list[str]]:
    pending = _pending_tool_ids(data)
    score = min(18.0, 8.0 * len(pending))
    if pending:
        return score, [f"Tool calls are still pending: {', '.join(pending.values())}."]
    return 0.0, []


def _score_stagnation(data: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent(data, 8)
    if len(recent) < 4:
        return 0.0, []
    useful = [event for event in recent if event.get("type") in CONVERSATION_USEFUL_TYPES and event.get("result", "pass") != "fail"]
    text_only = [event for event in recent if event.get("type") in POLISH_TYPES or event.get("phase") in {"plan", "summarize"}]
    if not useful and len(text_only) >= 4:
        return 14.0, ["Conversation is producing updates/summaries without fresh tool evidence."]
    score = 10.0 * (1.0 - _ratio(len(useful), len(recent)))
    if score >= 7:
        return score, ["Recent conversation events show little execution evidence."]
    return 0.0, []


def _score_user_challenge(data: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent(data, 6)
    challenges = [event for event in recent if event.get("type") in USER_CHALLENGE_TYPES]
    if challenges:
        return min(12.0, 6.0 * len(challenges)), ["User challenged the monitor or agent state; calibration is required."]
    return 0.0, []


def _score_context_decay(data: dict[str, Any], checkpoint_stale_minutes: int) -> tuple[float, list[str]]:
    checkpoints = [event for event in data.get("events", []) if event.get("type") in {"checkpoint", "assistant_checkpoint"}]
    if not checkpoints:
        if len(data.get("events", [])) >= 10:
            return 10.0, ["No conversation checkpoint exists after many turns."]
        return 0.0, []
    latest = checkpoints[-1].get("created_at")
    age = age_minutes(latest)
    if age is None:
        return 6.0, ["Latest conversation checkpoint timestamp is invalid."]
    if age > checkpoint_stale_minutes:
        return 10.0, [f"Latest conversation checkpoint is stale: {age:.0f} minutes old."]
    return 0.0, []


def _score_cost_pressure(data: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent(data, 8)
    useful = [event for event in recent if event.get("type") in CONVERSATION_USEFUL_TYPES and event.get("result", "pass") != "fail"]
    if useful:
        return 0.0, []
    total_tokens = sum(int(event.get("prompt_tokens") or 0) + int(event.get("completion_tokens") or 0) for event in recent)
    total_cost = sum(float(event.get("cost") or 0.0) for event in recent)
    if total_tokens >= 12000 or total_cost >= 5:
        return 5.0, ["High model pressure without nearby execution evidence."]
    return 0.0, []


def _score_final_gate(data: dict[str, Any]) -> tuple[float, list[str]]:
    final_events = [event for event in _recent(data, 12) if event.get("type") == "final_attempt" or event.get("phase") == "final"]
    if not final_events:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []
    unsupported = _unsupported_claim_events(data)
    pending = _pending_tool_ids(data)
    failures = _unresolved_failure_events(data)

    if unsupported:
        score += 10.0
        reasons.append("Final gate is open while completion claims have no nearby evidence.")
    if pending:
        score += 8.0
        reasons.append("Final gate is open while tool calls are still pending.")
    if failures:
        score += 18.0
        reasons.append("Final gate is open while failed events are unresolved.")
    return min(24.0, score), reasons


def scan_conversation(data: dict[str, Any], *, checkpoint_stale_minutes: int = 45) -> dict[str, Any]:
    parts = {
        "claim_overhang": _score_claim_overhang(data),
        "unresolved_failures": _score_unresolved_failures(data),
        "pending_tools": _score_pending_tools(data),
        "final_gate": _score_final_gate(data),
        "stagnation": _score_stagnation(data),
        "user_challenge": _score_user_challenge(data),
        "context_decay": _score_context_decay(data, checkpoint_stale_minutes),
        "cost_pressure": _score_cost_pressure(data),
    }
    components = {name: clamp_score(score) for name, (score, _reasons) in parts.items()}
    reasons: list[str] = []
    for _name, (_score, part_reasons) in parts.items():
        reasons.extend(part_reasons)
    score = clamp_score(sum(score for score, _reasons in parts.values()))
    band = band_for(score)
    if score >= 66:
        action = "block_final"
    elif score >= 36:
        action = "calibrate"
    elif score >= 15:
        action = "watch"
    else:
        action = "continue"
    return {
        "schema": "hulun.conversation_risk.v1",
        "generated_at": utc_now(),
        "score": score,
        "slop_index": score,
        "band": band,
        "required_action": action,
        "components": components,
        "reasons": reasons or ["Conversation runtime is within the configured operating band."],
    }


def record_conversation_event(
    conversation_id: str,
    event_type: str,
    summary: str,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with conversation_write_lock(conversation_id):
        data = load_conversation(conversation_id)
        event = append_conversation_event(data, event_type, summary, **kwargs)
        risk = scan_conversation(data)
        data["last_scan"] = risk
        save_conversation(data)
    if data.get("monitor_id"):
        update_monitor(
            data["monitor_id"],
            score=int(risk["score"]),
            summary=event["summary"],
            result=kwargs.get("result", "pass"),
            reason=risk["reasons"][0] if risk.get("reasons") else None,
        )
    return data, event, risk


def refresh_conversation_scan(
    conversation_id: str,
    *,
    checkpoint_stale_minutes: int = 45,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with conversation_write_lock(conversation_id):
        data = load_conversation(conversation_id)
        risk = scan_conversation(data, checkpoint_stale_minutes=checkpoint_stale_minutes)
        data["last_scan"] = risk
        save_conversation(data)
    if data.get("monitor_id"):
        update_monitor(
            data["monitor_id"],
            score=int(risk["score"]),
            summary="Conversation scan refreshed.",
            reason=risk["reasons"][0] if risk.get("reasons") else None,
        )
    return data, risk


def close_conversation(conversation_id: str) -> dict[str, Any]:
    with conversation_write_lock(conversation_id):
        data = load_conversation(conversation_id)
        data["status"] = "closed"
        append_conversation_event(data, "conversation_close", "Conversation closed.", result="pass")
        risk = scan_conversation(data)
        data["last_scan"] = risk
        save_conversation(data)
    if data.get("monitor_id"):
        update_monitor(data["monitor_id"], status="closed", score=int(risk["score"]), summary="Conversation closed.")
    return data
