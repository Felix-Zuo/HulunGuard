from __future__ import annotations

import json
from typing import Any

from .risk import scan_state
from .schemas import VALIDATION_SCHEMA
from .storage import criteria, initial_state
from .util import next_id, utc_now


def _append_event(
    state: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    phase: str | None = None,
    claims: list[str] | None = None,
    evidence: list[str] | None = None,
    action_key: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
    latency_ms: int | None = None,
) -> None:
    event = {
        "id": next_id(state.setdefault("events", []), "EV"),
        "type": event_type,
        "summary": summary,
        "result": result,
        "created_at": utc_now(),
    }
    optional = {
        "phase": phase,
        "claims": claims or [],
        "evidence": evidence or [],
        "action_key": action_key,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
        "source_platform": "hulun-validation",
    }
    for key, value in optional.items():
        if value not in (None, "", []):
            event[key] = value
    state["events"].append(event)


def _scan_scenario(name: str, expected: str, state: dict[str, Any]) -> dict[str, Any]:
    risk = scan_state(state)
    return {
        "scenario": name,
        "expected": expected,
        "score": risk["score"],
        "band": risk["band"],
        "required_action": risk["required_action"],
        "components": risk["components"],
        "reasons": risk["reasons"],
    }


def _healthy_proof_backed() -> dict[str, Any]:
    state = initial_state(
        "Ship a proof-backed monitor",
        ["Final claim has evidence"],
        [],
        [],
        66,
    )
    state["evidence"].append(
        {
            "id": "E1",
            "kind": "test",
            "summary": "pytest passed",
            "command": "python -m pytest -q",
            "created_at": utc_now(),
        }
    )
    criteria(state)[0]["status"] = "done"
    criteria(state)[0]["evidence"] = ["E1"]
    state["checkpoints"].append(
        {
            "id": "K1",
            "summary": "Evidence is attached",
            "next_action": "final",
            "created_at": utc_now(),
        }
    )
    _append_event(state, "evidence", "E1: pytest passed", evidence=["E1"])
    _append_event(state, "checkpoint", "K1: Evidence is attached")
    _append_event(
        state,
        "final_attempt",
        "Completed and verified with evidence E1",
        phase="final",
        claims=["completed and verified"],
        evidence=["E1"],
    )
    return _scan_scenario("healthy_proof_backed", "green", state)


def _unsupported_final_claim() -> dict[str, Any]:
    state = initial_state(
        "Ship a proof-backed monitor",
        ["Final claim has evidence"],
        [],
        [],
        66,
    )
    _append_event(
        state,
        "final_attempt",
        "Everything is completed and verified.",
        phase="final",
        claims=["completed and verified"],
        prompt_tokens=9000,
        completion_tokens=5000,
        cost=6.5,
        latency_ms=70000,
    )
    return _scan_scenario("unsupported_final_claim", "red", state)


def _failure_loop_then_final() -> dict[str, Any]:
    state = initial_state("Fix tests before final", ["pytest passes"], [], [], 66)
    for _idx in range(3):
        _append_event(
            state,
            "tool_result",
            "pytest failed",
            result="fail",
            phase="verify",
            action_key="pytest",
        )
    _append_event(
        state,
        "final_attempt",
        "Tests are fixed and verified.",
        phase="final",
        claims=["fixed and verified"],
    )
    return _scan_scenario("failure_loop_then_final", "red", state)


def _expensive_polish_no_progress() -> dict[str, Any]:
    state = initial_state("Build and verify feature", ["Feature has test evidence"], [], [], 66)
    for _idx in range(4):
        _append_event(
            state,
            "summary",
            "Overall summary and final conclusion without new evidence.",
            phase="summarize",
            prompt_tokens=4000,
            completion_tokens=1500,
            cost=1.8,
            latency_ms=20000,
        )
    return _scan_scenario("expensive_polish_no_progress", "red", state)


def run_validation_suite() -> dict[str, Any]:
    scenarios = [
        _healthy_proof_backed(),
        _unsupported_final_claim(),
        _failure_loop_then_final(),
        _expensive_polish_no_progress(),
    ]
    passes = 0
    for scenario in scenarios:
        expected = scenario["expected"]
        band = scenario["band"]
        if expected == band:
            passes += 1
    return {
        "schema": VALIDATION_SCHEMA,
        "generated_at": utc_now(),
        "passes": passes,
        "total": len(scenarios),
        "scenarios": scenarios,
    }


def build_validation_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# HulunGuard Validation Report",
        "",
        f"Generated: {result['generated_at']}",
        f"Passes: {result['passes']} / {result['total']}",
        "",
        "## Scenarios",
        "",
        "| Scenario | Expected | Score | Band | Required action |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for scenario in result["scenarios"]:
        lines.append(
            f"| {scenario['scenario']} | {scenario['expected']} | {scenario['score']} | "
            f"{scenario['band']} | {scenario['required_action']} |"
        )
    lines.extend(["", "## Components"])
    for scenario in result["scenarios"]:
        lines.extend(["", f"### {scenario['scenario']}", ""])
        for key, value in scenario["components"].items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "Reasons:"])
        lines.extend([f"- {reason}" for reason in scenario["reasons"]])
    return "\n".join(lines) + "\n"


def validation_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
