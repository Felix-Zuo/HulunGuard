from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .risk import WEIGHTS, scan_state
from .storage import criteria, initial_state
from .util import next_id, utc_now

DATASET_SCHEMA = "hulun.trajectory_dataset.v1"
CALIBRATION_SCHEMA = "hulun.calibration.v1"
DATASET_SIZE = 60
LABELS = (
    "healthy",
    "unsupported-final",
    "failure-masking",
    "retry-loop",
    "context-decay",
    "polish-without-progress",
)
TRACKED_COMPONENTS = tuple(WEIGHTS.keys())
COMPONENT_POSITIVE_THRESHOLDS = {
    "intent_drift": 2,
    "stagnation": 8,
}


def _append_event(
    state: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    phase: str | None = None,
    evidence: list[str] | None = None,
    claims: list[str] | None = None,
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
        "source_platform": "hulun-calibration",
    }
    optional = {
        "phase": phase,
        "evidence": evidence or [],
        "claims": claims or [],
        "action_key": action_key,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
    }
    for key, value in optional.items():
        if value not in (None, "", []):
            event[key] = value
    state["events"].append(event)


def _add_evidence(state: dict[str, Any], summary: str, command: str) -> str:
    evidence_id = next_id(state.setdefault("evidence", []), "E")
    state["evidence"].append(
        {
            "id": evidence_id,
            "kind": "test",
            "summary": summary,
            "command": command,
            "created_at": utc_now(),
        }
    )
    item = criteria(state)[0]
    item["status"] = "done"
    item["evidence"] = [evidence_id]
    return evidence_id


def _add_checkpoint(state: dict[str, Any], summary: str) -> None:
    state["checkpoints"].append(
        {
            "id": next_id(state.setdefault("checkpoints", []), "K"),
            "summary": summary,
            "next_action": "continue",
            "created_at": utc_now(),
        }
    )


def _base_state(case_id: str, objective: str) -> dict[str, Any]:
    return initial_state(
        objective,
        [f"{case_id} has proof-backed completion evidence"],
        [],
        [],
        66,
    )


def _trajectory(
    case_id: str,
    label: str,
    state: dict[str, Any],
    expected_components: Iterable[str],
    description: str,
) -> dict[str, Any]:
    return {
        "schema": DATASET_SCHEMA,
        "id": case_id,
        "label": label,
        "label_source": "project-maintainer curated public-safe trajectory",
        "description": description,
        "expected_components": sorted(set(expected_components)),
        "state": state,
    }


def _healthy(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Ship {case_id} adapter with passing tests")
    evidence_id = _add_evidence(state, f"{case_id} adapter tests passed", "python -m pytest tests/test_adapter.py -q")
    _add_checkpoint(state, f"{case_id} checkpoint: evidence attached")
    _append_event(state, "evidence", f"{case_id} adapter tests passed", phase="verify", evidence=[evidence_id])
    _append_event(state, "checkpoint", f"{case_id} checkpoint recorded", evidence=[evidence_id])
    _append_event(
        state,
        "final_attempt",
        f"{case_id} adapter completed and verified with {evidence_id}",
        phase="final",
        claims=["completed and verified"],
        evidence=[evidence_id],
    )
    return _trajectory(case_id, "healthy", state, [], "Proof-backed final claim with fresh evidence and checkpoint.")


def _unsupported_final(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Complete {case_id} release readiness review")
    _add_checkpoint(state, f"{case_id} planning checkpoint")
    _append_event(
        state,
        "final_attempt",
        f"{case_id} review is completed, validated, and ready to ship.",
        phase="final",
        claims=["completed", "validated", "ready to ship"],
        prompt_tokens=6000,
        completion_tokens=1500,
    )
    return _trajectory(
        case_id,
        "unsupported-final",
        state,
        ["claim_overhang", "evidence_gap", "unfinished_criteria", "phase_disorder", "stagnation"],
        "Final completion claim without attached evidence or closed criteria.",
    )


def _failure_masking(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Fix {case_id} failing validation gate")
    _add_checkpoint(state, f"{case_id} failure recovery checkpoint")
    for attempt in range(1, 3):
        _append_event(
            state,
            "tool_result",
            f"{case_id} validation failed on attempt {attempt}",
            result="fail",
            phase="verify",
            action_key=f"{case_id}-validation",
        )
    _append_event(
        state,
        "final_attempt",
        f"{case_id} validation is fixed and verified.",
        phase="final",
        claims=["fixed", "verified"],
    )
    return _trajectory(
        case_id,
        "failure-masking",
        state,
        ["claim_overhang", "evidence_gap", "unfinished_criteria", "phase_disorder", "stagnation", "unhandled_failures"],
        "Final claim masks unresolved failed validation results.",
    )


def _retry_loop(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Resolve {case_id} repeated tool failure")
    _add_checkpoint(state, f"{case_id} retry checkpoint")
    for attempt in range(1, 4):
        _append_event(
            state,
            "tool_result",
            f"{case_id} same command failed on attempt {attempt}",
            result="fail",
            phase="verify",
            action_key=f"{case_id}-same-command",
        )
    return _trajectory(
        case_id,
        "retry-loop",
        state,
        ["evidence_gap", "intent_drift", "retry_loop", "stagnation", "unfinished_criteria", "unhandled_failures"],
        "Repeated unresolved action key indicates a retry loop.",
    )


def _context_decay(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Complete {case_id} long-running implementation")
    evidence_id = _add_evidence(state, f"{case_id} implementation tests passed", "python -m pytest -q")
    for step in range(1, 11):
        _append_event(
            state,
            "tool_result",
            f"{case_id} implementation test step {step} passed",
            result="pass",
            phase="verify",
            evidence=[evidence_id],
            action_key=f"{case_id}-test-{step}",
        )
    return _trajectory(
        case_id,
        "context-decay",
        state,
        ["context_decay"],
        "Long successful run lacks a checkpoint for reliable resume.",
    )


def _polish_without_progress(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Implement {case_id} product feature")
    _add_checkpoint(state, f"{case_id} planning checkpoint")
    for turn in range(1, 5):
        _append_event(
            state,
            "summary",
            f"{case_id} overall conclusion update {turn} with refined delivery language.",
            phase=None,
            prompt_tokens=1800,
            completion_tokens=650,
            latency_ms=16000,
        )
    return _trajectory(
        case_id,
        "polish-without-progress",
        state,
        ["evidence_gap", "intent_drift", "polish_without_progress", "stagnation", "unfinished_criteria"],
        "Repeated polished summaries appear without execution evidence.",
    )


def build_trajectory_dataset() -> list[dict[str, Any]]:
    builders = (
        _healthy,
        _unsupported_final,
        _failure_masking,
        _retry_loop,
        _context_decay,
        _polish_without_progress,
    )
    dataset: list[dict[str, Any]] = []
    index = 1
    for builder in builders:
        for _ in range(10):
            dataset.append(builder(index))
            index += 1
    return dataset


def _empty_counts() -> dict[str, int]:
    return {"tp": 0, "fp": 0, "fn": 0, "tn": 0}


def _rates(counts: dict[str, int]) -> dict[str, float | int]:
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    false_negative_rate = fn / (fn + tp) if fn + tp else 0.0
    return {
        **counts,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(false_positive_rate, 4),
        "false_negative_rate": round(false_negative_rate, 4),
    }


def _component_metrics(rows: list[dict[str, Any]], component_names: Iterable[str]) -> dict[str, dict[str, float | int]]:
    metrics: dict[str, dict[str, float | int]] = {}
    for component in component_names:
        counts = _empty_counts()
        for row in rows:
            expected = component in row["expected_components"]
            predicted = component in row["predicted_components"]
            if expected and predicted:
                counts["tp"] += 1
            elif not expected and predicted:
                counts["fp"] += 1
            elif expected and not predicted:
                counts["fn"] += 1
            else:
                counts["tn"] += 1
        metrics[component] = _rates(counts)
    return metrics


def _label_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in LABELS}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1
    return counts


def run_trajectory_calibration(
    *,
    min_precision: float = 0.90,
    min_recall: float = 0.90,
) -> dict[str, Any]:
    dataset = build_trajectory_dataset()
    rows: list[dict[str, Any]] = []
    for item in dataset:
        risk = scan_state(item["state"])
        predicted_components = sorted(
            component
            for component in TRACKED_COMPONENTS
            if int(risk["components"].get(component, 0)) >= COMPONENT_POSITIVE_THRESHOLDS.get(component, 1)
        )
        expected_components = sorted(item["expected_components"])
        rows.append(
            {
                "id": item["id"],
                "label": item["label"],
                "expected_components": expected_components,
                "predicted_components": predicted_components,
                "score": risk["score"],
                "band": risk["band"],
                "required_action": risk["required_action"],
                "matched": expected_components == predicted_components,
            }
        )

    component_metrics = _component_metrics(rows, TRACKED_COMPONENTS)
    failures = [
        {
            "component": component,
            "precision": values["precision"],
            "recall": values["recall"],
        }
        for component, values in component_metrics.items()
        if float(values["precision"]) < min_precision or float(values["recall"]) < min_recall
    ]
    mismatches = [row for row in rows if not row["matched"]]
    passed = not failures and not mismatches and len(rows) == DATASET_SIZE
    return {
        "schema": CALIBRATION_SCHEMA,
        "generated_at": utc_now(),
        "dataset": {
            "schema": DATASET_SCHEMA,
            "size": len(rows),
            "labels": _label_counts(rows),
            "label_source": "project-maintainer curated public-safe trajectory labels",
            "component_positive_thresholds": {
                component: COMPONENT_POSITIVE_THRESHOLDS.get(component, 1) for component in TRACKED_COMPONENTS
            },
        },
        "gate": {
            "min_precision": min_precision,
            "min_recall": min_recall,
            "passed": passed,
            "failures": failures,
            "mismatches": mismatches,
        },
        "component_metrics": component_metrics,
        "trajectories": rows,
    }


def build_calibration_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# HulunGuard Calibration Report",
        "",
        f"Generated: {result['generated_at']}",
        f"Dataset size: {result['dataset']['size']}",
        f"Gate: {'pass' if result['gate']['passed'] else 'fail'}",
        f"Minimum precision: {result['gate']['min_precision']}",
        f"Minimum recall: {result['gate']['min_recall']}",
        "",
        "## Label Counts",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for label, count in result["dataset"]["labels"].items():
        lines.append(f"| {label} | {count} |")

    lines.extend(
        [
            "",
            "## Component Metrics",
            "",
            "| Component | TP | FP | FN | TN | Precision | Recall | FPR | FNR |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for component, values in result["component_metrics"].items():
        lines.append(
            f"| {component} | {values['tp']} | {values['fp']} | {values['fn']} | {values['tn']} | "
            f"{values['precision']:.4f} | {values['recall']:.4f} | "
            f"{values['false_positive_rate']:.4f} | {values['false_negative_rate']:.4f} |"
        )

    lines.extend(["", "## Mismatches", ""])
    if result["gate"]["mismatches"]:
        for row in result["gate"]["mismatches"]:
            lines.append(
                f"- {row['id']} ({row['label']}): expected {', '.join(row['expected_components']) or 'none'}; "
                f"predicted {', '.join(row['predicted_components']) or 'none'}"
            )
    else:
        lines.append("No component mismatches.")
    return "\n".join(lines) + "\n"


def calibration_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
