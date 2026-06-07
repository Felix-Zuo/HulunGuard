from __future__ import annotations

from typing import Any

from .constants import FAILURE_EVENT_TYPES, USEFUL_EVENT_TYPES
from .storage import criteria
from .util import age_minutes, clamp_score, overlap_ratio, utc_now


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


def _ratio(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return part / whole


def score_evidence_gap(state: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    items = criteria(state)
    if not items:
        return 25.0, ["No success criteria recorded."]

    done_items = [item for item in items if item.get("status") == "done"]
    done_without_evidence = [item for item in done_items if not item.get("evidence")]
    pending_without_evidence = [item for item in items if item.get("status") != "done" and not item.get("evidence")]

    score = 0.0
    if done_items:
        score += 18.0 * _ratio(len(done_without_evidence), len(done_items))
    else:
        score += 10.0
    score += 7.0 * _ratio(len(pending_without_evidence), len(items))

    if done_without_evidence:
        ids = ", ".join(item["id"] for item in done_without_evidence)
        reasons.append(f"Completed criteria without evidence: {ids}.")
    if not state.get("evidence"):
        score = max(score, 20.0)
        reasons.append("No evidence has been recorded yet.")
    return min(25.0, score), reasons


def score_unfinished_criteria(state: dict[str, Any]) -> tuple[float, list[str]]:
    items = criteria(state)
    if not items:
        return 20.0, ["No explicit done conditions exist."]
    unfinished = [item for item in items if item.get("status") in {"pending", "in_progress", "blocked"}]
    score = 20.0 * _ratio(len(unfinished), len(items))
    reasons = []
    if unfinished:
        ids = ", ".join(item["id"] for item in unfinished)
        reasons.append(f"Unfinished criteria remain: {ids}.")
    return score, reasons


def score_stagnation(state: dict[str, Any]) -> tuple[float, list[str]]:
    events = state.get("events", [])
    if not events:
        if state.get("steps") or state.get("criteria"):
            return 8.0, ["No execution events have been recorded."]
        return 0.0, []
    recent = events[-6:]
    useful = [event for event in recent if event.get("type") in USEFUL_EVENT_TYPES and event.get("result", "pass") != "fail"]
    text_only = [event for event in recent if event.get("type") in {"plan", "summary", "note", "final_attempt"}]
    score = 15.0 * (1.0 - _ratio(len(useful), len(recent)))
    if len(text_only) >= 4 and not useful:
        score = 15.0
    reasons = []
    if score >= 8:
        reasons.append("Recent events show little new execution evidence.")
    return min(15.0, score), reasons


def score_unhandled_failures(state: dict[str, Any]) -> tuple[float, list[str]]:
    events = state.get("events", [])
    failed = [
        event
        for event in events
        if event.get("type") in FAILURE_EVENT_TYPES and event.get("result") == "fail" and not event.get("resolved")
    ]
    score = min(15.0, 5.0 * len(failed))
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
            return 10.0, ["No checkpoint exists for resume after compaction."]
        return 4.0, ["No checkpoint exists yet."]
    latest = checkpoints[-1].get("created_at")
    age = age_minutes(latest)
    if age is None:
        return 8.0, ["Latest checkpoint timestamp is invalid."]
    if age > checkpoint_stale_minutes:
        return 10.0, [f"Latest checkpoint is stale: {age:.0f} minutes old."]
    if age > checkpoint_stale_minutes / 2:
        return 5.0, [f"Latest checkpoint is aging: {age:.0f} minutes old."]
    return 0.0, []


def score_intent_drift(state: dict[str, Any]) -> tuple[float, list[str]]:
    objective = state.get("objective", "")
    criteria_text = " ".join(item.get("text", "") for item in criteria(state))
    reference = f"{objective} {criteria_text}".strip()
    recent_text = " ".join(event.get("summary", "") for event in state.get("events", [])[-5:])
    if not recent_text:
        return 2.0, []
    overlap = overlap_ratio(reference, recent_text)
    if overlap >= 0.22:
        return 0.0, []
    score = 10.0 * (1.0 - min(1.0, overlap / 0.22))
    return score, [f"Recent event text weakly overlaps the objective ({overlap:.2f})."]


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
    return min(5.0, float(len(hits) * 2)), [f"Uncertainty markers appear without fresh verification: {', '.join(hits[:4])}."]


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
        "unfinished_criteria": score_unfinished_criteria(state),
        "stagnation": score_stagnation(state),
        "unhandled_failures": score_unhandled_failures(state),
        "context_decay": score_context_decay(state, checkpoint_stale_minutes),
        "intent_drift": score_intent_drift(state),
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
        "schema": "hulun.risk.v1",
        "generated_at": utc_now(),
        "score": score,
        "band": band,
        "threshold": configured_threshold,
        "blocked": blocked,
        "required_action": action_for(score, final_attempt),
        "final_attempt": final_attempt,
        "components": components,
        "reasons": reasons or ["Risk is within the configured operating band."],
    }
    return result
