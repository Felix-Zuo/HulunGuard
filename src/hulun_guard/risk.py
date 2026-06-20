from __future__ import annotations

from collections import Counter
from typing import Any

from .constants import FAILURE_EVENT_TYPES, USEFUL_EVENT_TYPES
from .schemas import RISK_SCHEMA
from .storage import criteria
from .util import age_minutes, clamp_score, overlap_ratio, tokens, utc_now

UNCERTAINTY_MARKERS = [
    "maybe",
    "probably",
    "possibly",
    "looks like",
    "should be",
    "i think",
    "not sure",
    "uncertain",
    "大概",
    "可能",
    "应该",
    "看起来",
    "也许",
    "不确定",
    "估计",
]

CLAIM_MARKERS = [
    "completed",
    "done",
    "fixed",
    "finished",
    "passed",
    "ready",
    "resolved",
    "validated",
    "verified",
    "works",
    "完成",
    "已完成",
    "修复",
    "已修复",
    "通过",
    "验证",
    "已验证",
    "没问题",
    "可以交付",
]

POLISH_MARKERS = [
    "conclusion",
    "deliverable",
    "final",
    "in short",
    "overall",
    "summary",
    "总结",
    "综上",
    "最终",
    "整体来说",
    "可以认为",
]

FINAL_PHASES = {"final", "summarize"}
VERIFY_EVENT_TYPES = {"approval", "evidence", "source", "test", "verification"}

WEIGHTS = {
    "evidence_gap": 20,
    "claim_overhang": 14,
    "unfinished_criteria": 14,
    "stagnation": 11,
    "unhandled_failures": 11,
    "context_decay": 8,
    "intent_drift": 7,
    "phase_disorder": 4,
    "polish_without_progress": 4,
    "retry_loop": 3,
    "cost_pressure": 2,
    "uncertainty": 2,
}


def _ratio(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return part / whole


def _recent_events(state: dict[str, Any], count: int = 8) -> list[dict[str, Any]]:
    return state.get("events", [])[-count:]


def _event_text(event: dict[str, Any]) -> str:
    claims = " ".join(str(claim) for claim in event.get("claims", []) if claim)
    return f"{event.get('summary', '')} {claims}".strip()


def _marker_hits(text: str, markers: list[str]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker.lower() in lowered]


def _claim_count(event: dict[str, Any]) -> int:
    explicit = len([claim for claim in event.get("claims", []) if str(claim).strip()])
    marker_count = len(_marker_hits(_event_text(event), CLAIM_MARKERS))
    if event.get("type") == "final_attempt" or event.get("phase") in FINAL_PHASES:
        marker_count = max(marker_count, 1)
    return min(5, explicit + marker_count)


def _has_verification_signal(event: dict[str, Any]) -> bool:
    if event.get("evidence"):
        return True
    if event.get("type") in VERIFY_EVENT_TYPES and event.get("result", "pass") == "pass":
        return True
    return False


def _event_key(event: dict[str, Any]) -> str:
    configured = str(event.get("action_key") or "").strip()
    if configured:
        return configured
    text_tokens = sorted(tokens(_event_text(event)))
    if not text_tokens:
        return str(event.get("type", "event"))
    return f"{event.get('type', 'event')}:{' '.join(text_tokens[:6])}"


def score_evidence_gap(state: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    items = criteria(state)
    if not items:
        return float(WEIGHTS["evidence_gap"]), ["No success criteria recorded."]

    done_items = [item for item in items if item.get("status") == "done"]
    done_without_evidence = [item for item in done_items if not item.get("evidence")]
    pending_without_evidence = [item for item in items if item.get("status") != "done" and not item.get("evidence")]

    score = 0.0
    if done_items:
        score += 14.0 * _ratio(len(done_without_evidence), len(done_items))
    else:
        score += 8.0
    score += 6.0 * _ratio(len(pending_without_evidence), len(items))

    if done_without_evidence:
        ids = ", ".join(item["id"] for item in done_without_evidence)
        reasons.append(f"Completed criteria without evidence: {ids}.")
    if not state.get("evidence"):
        score = max(score, 16.0)
        reasons.append("No evidence has been recorded yet.")
    return min(float(WEIGHTS["evidence_gap"]), score), reasons


def score_unfinished_criteria(state: dict[str, Any]) -> tuple[float, list[str]]:
    items = criteria(state)
    if not items:
        return float(WEIGHTS["unfinished_criteria"]), ["No explicit done conditions exist."]
    unfinished = [item for item in items if item.get("status") in {"pending", "in_progress", "blocked"}]
    score = WEIGHTS["unfinished_criteria"] * _ratio(len(unfinished), len(items))
    reasons = []
    if unfinished:
        ids = ", ".join(item["id"] for item in unfinished)
        reasons.append(f"Unfinished criteria remain: {ids}.")
    return score, reasons


def score_claim_overhang(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent_events(state, 10)
    claiming_events = [event for event in recent if _claim_count(event)]
    if not claiming_events:
        return 0.0, []

    unfinished = [item for item in criteria(state) if item.get("status") in {"pending", "in_progress", "blocked"}]
    all_done_with_evidence = bool(criteria(state)) and not unfinished and all(
        item.get("evidence") for item in criteria(state) if item.get("status") == "done"
    )
    finalish = [event for event in claiming_events if event.get("type") == "final_attempt" or event.get("phase") in FINAL_PHASES]

    unsupported = 0
    claims = 0
    for event in claiming_events:
        count = _claim_count(event)
        claims += count
        supported = bool(event.get("evidence")) or (
            (event.get("type") == "final_attempt" or event.get("phase") in FINAL_PHASES) and all_done_with_evidence
        )
        if not supported:
            unsupported += count

    score = WEIGHTS["claim_overhang"] * _ratio(unsupported, claims)
    if finalish and unfinished:
        score = max(score, WEIGHTS["claim_overhang"] * 0.75)

    if score < 1:
        return 0.0, []
    reasons = [f"Completion or verification claims outpace evidence coverage ({claims - unsupported}/{claims})."]
    if finalish and unfinished:
        reasons.append("Final or summary phase appeared while criteria are still unfinished.")
    return min(float(WEIGHTS["claim_overhang"]), score), reasons


def score_stagnation(state: dict[str, Any]) -> tuple[float, list[str]]:
    events = state.get("events", [])
    if not events:
        if state.get("steps") or state.get("criteria"):
            return 6.0, ["No execution events have been recorded."]
        return 0.0, []
    recent = events[-6:]
    useful = [event for event in recent if event.get("type") in USEFUL_EVENT_TYPES and event.get("result", "pass") != "fail"]
    text_only = [event for event in recent if event.get("type") in {"plan", "summary", "note", "final_attempt"}]
    score = WEIGHTS["stagnation"] * (1.0 - _ratio(len(useful), len(recent)))
    if len(text_only) >= 4 and not useful:
        score = float(WEIGHTS["stagnation"])
    reasons = []
    if score >= 8:
        reasons.append("Recent events show little new execution evidence.")
    return min(float(WEIGHTS["stagnation"]), score), reasons


def score_unhandled_failures(state: dict[str, Any]) -> tuple[float, list[str]]:
    events = state.get("events", [])
    failed = [
        event
        for event in events
        if event.get("type") in FAILURE_EVENT_TYPES and event.get("result") == "fail" and not event.get("resolved")
    ]
    score = min(float(WEIGHTS["unhandled_failures"]), 4.0 * len(failed))
    reasons = []
    if failed:
        ids = ", ".join(event["id"] for event in failed[-4:])
        reasons.append(f"Unresolved failed tool/test/source events: {ids}.")
    return score, reasons


def score_context_decay(state: dict[str, Any], checkpoint_stale_minutes: int) -> tuple[float, list[str]]:
    checkpoints = state.get("checkpoints", [])
    events = state.get("events", [])
    if not checkpoints:
        if len(events) >= 3 or state.get("steps"):
            return float(WEIGHTS["context_decay"]), ["No checkpoint exists for resume after compaction."]
        return 3.0, ["No checkpoint exists yet."]
    latest = checkpoints[-1].get("created_at")
    age = age_minutes(latest)
    if age is None:
        return 6.0, ["Latest checkpoint timestamp is invalid."]
    if age > checkpoint_stale_minutes:
        return float(WEIGHTS["context_decay"]), [f"Latest checkpoint is stale: {age:.0f} minutes old."]
    if age > checkpoint_stale_minutes / 2:
        return 4.0, [f"Latest checkpoint is aging: {age:.0f} minutes old."]
    return 0.0, []


def score_intent_drift(state: dict[str, Any]) -> tuple[float, list[str]]:
    objective = state.get("objective", "")
    criteria_text = " ".join(item.get("text", "") for item in criteria(state))
    reference = f"{objective} {criteria_text}".strip()
    recent_text = " ".join(event.get("summary", "") for event in state.get("events", [])[-5:])
    if not recent_text:
        return 1.0, []
    overlap = overlap_ratio(reference, recent_text)
    if overlap >= 0.22:
        return 0.0, []
    score = WEIGHTS["intent_drift"] * (1.0 - min(1.0, overlap / 0.22))
    return score, [f"Recent event text weakly overlaps the objective ({overlap:.2f})."]


def score_phase_disorder(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent_events(state, 8)
    if not recent:
        return 0.0, []

    unfinished = [item for item in criteria(state) if item.get("status") in {"pending", "in_progress", "blocked"}]
    finalish = [event for event in recent if event.get("type") == "final_attempt" or event.get("phase") in FINAL_PHASES]
    verification = [event for event in recent if _has_verification_signal(event)]
    unresolved_failures = [
        event
        for event in state.get("events", [])
        if event.get("type") in FAILURE_EVENT_TYPES and event.get("result") == "fail" and not event.get("resolved")
    ]

    score = 0.0
    reasons: list[str] = []
    if finalish and unfinished:
        score += 2.5
        reasons.append("Final or summary phase appeared before open criteria were closed.")
    if finalish and not verification:
        score += 1.5
        reasons.append("Final or summary phase appeared without nearby verification evidence.")
    if finalish and unresolved_failures:
        score += 1.5
        reasons.append("Final or summary phase appeared while failures are unresolved.")
    return min(float(WEIGHTS["phase_disorder"]), score), reasons


def score_polish_without_progress(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent_events(state, 8)
    if not recent:
        return 0.0, []

    polish_events = [
        event
        for event in recent
        if event.get("phase") in FINAL_PHASES
        or event.get("type") in {"final_attempt", "summary"}
        or _marker_hits(_event_text(event), POLISH_MARKERS)
    ]
    useful = [event for event in recent if event.get("type") in USEFUL_EVENT_TYPES and event.get("result", "pass") != "fail"]
    if len(polish_events) < 2 or useful:
        return 0.0, []
    score = min(float(WEIGHTS["polish_without_progress"]), float(len(polish_events)))
    return score, ["Polished summary/final language is increasing without fresh execution evidence."]


def score_retry_loop(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent = [
        event
        for event in _recent_events(state, 12)
        if event.get("type") in FAILURE_EVENT_TYPES or event.get("action_key")
    ]
    if not recent:
        return 0.0, []

    unresolved = [event for event in recent if event.get("result") in {"fail", "unknown"} and not event.get("resolved")]
    counts = Counter(_event_key(event) for event in unresolved)
    repeated = [(key, count) for key, count in counts.items() if count >= 3]
    if not repeated:
        return 0.0, []
    key, count = max(repeated, key=lambda item: item[1])
    score = min(float(WEIGHTS["retry_loop"]), float(count))
    return score, [f"Repeated unresolved action loop detected: {key} ({count} times)."]


def score_cost_pressure(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent = _recent_events(state, 8)
    total_tokens = sum(int(event.get("prompt_tokens") or 0) + int(event.get("completion_tokens") or 0) for event in recent)
    total_cost = sum(float(event.get("cost") or 0.0) for event in recent)
    max_latency = max([int(event.get("latency_ms") or 0) for event in recent] or [0])
    useful = [event for event in recent if event.get("type") in USEFUL_EVENT_TYPES and event.get("result", "pass") != "fail"]

    if useful:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    if total_tokens >= 12000:
        score += 1.0
        reasons.append(f"High token usage without fresh evidence: {total_tokens} tokens.")
    if total_cost >= 5.0:
        score += 1.0
        reasons.append(f"High model cost without fresh evidence: {total_cost:.2f}.")
    if max_latency >= 60000:
        score += 1.0
        reasons.append(f"High latency without fresh evidence: {max_latency} ms.")
    return min(float(WEIGHTS["cost_pressure"]), score), reasons


def score_uncertainty(state: dict[str, Any]) -> tuple[float, list[str]]:
    recent_text = " ".join(event.get("summary", "") for event in state.get("events", [])[-6:]).lower()
    if not recent_text:
        return 0.0, []
    hits = [marker for marker in UNCERTAINTY_MARKERS if marker in recent_text]
    if not hits:
        return 0.0, []
    useful_recent = [
        event
        for event in state.get("events", [])[-6:]
        if event.get("type") in USEFUL_EVENT_TYPES and event.get("result", "pass") == "pass"
    ]
    if useful_recent:
        return 1.0, []
    return min(float(WEIGHTS["uncertainty"]), float(len(hits))), [f"Uncertainty markers appear without fresh verification: {', '.join(hits[:4])}."]


def band_for(score: int) -> str:
    if score >= 66:
        return "red"
    if score >= 36:
        return "yellow"
    return "green"


def action_for(score: int, final_attempt: bool) -> str:
    if score >= 66:
        return "block_final" if final_attempt else "recover"
    if score >= 36:
        return "checkpoint"
    return "continue"


def scan_state(
    state: dict[str, Any],
    *,
    threshold: int | None = None,
    final_attempt: bool = False,
    checkpoint_stale_minutes: int = 45,
) -> dict[str, Any]:
    parts = {
        "evidence_gap": score_evidence_gap(state),
        "claim_overhang": score_claim_overhang(state),
        "unfinished_criteria": score_unfinished_criteria(state),
        "stagnation": score_stagnation(state),
        "unhandled_failures": score_unhandled_failures(state),
        "context_decay": score_context_decay(state, checkpoint_stale_minutes),
        "intent_drift": score_intent_drift(state),
        "phase_disorder": score_phase_disorder(state),
        "polish_without_progress": score_polish_without_progress(state),
        "retry_loop": score_retry_loop(state),
        "cost_pressure": score_cost_pressure(state),
        "uncertainty": score_uncertainty(state),
    }
    components = {name: clamp_score(score) for name, (score, _reasons) in parts.items()}
    reasons: list[str] = []
    for _name, (_score, part_reasons) in parts.items():
        reasons.extend(part_reasons)
    score = clamp_score(sum(score for score, _reasons in parts.values()))
    configured_threshold = threshold if threshold is not None else int(state.get("threshold", 66))
    band = band_for(score)
    blocked = score >= configured_threshold
    result = {
        "schema": RISK_SCHEMA,
        "generated_at": utc_now(),
        "score": score,
        "slop_index": score,
        "band": band,
        "threshold": configured_threshold,
        "blocked": blocked,
        "required_action": action_for(score, final_attempt),
        "final_attempt": final_attempt,
        "components": components,
        "weights": WEIGHTS,
        "reasons": reasons or ["Risk is within the configured operating band."],
    }
    return result
