from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .risk import WEIGHTS, scan_state
from .schemas import CALIBRATION_BASELINE_SCHEMA, CALIBRATION_DRIFT_SCHEMA, CALIBRATION_SCHEMA, TRAJECTORY_DATASET_SCHEMA
from .storage import criteria, initial_state
from .util import next_id, utc_now

DATASET_SCHEMA = TRAJECTORY_DATASET_SCHEMA
CURATED_TRAJECTORIES_PER_LABEL = 10
EXTERNAL_TRAJECTORIES_PER_SOURCE = 5
PUBLIC_SOURCE_URIS = {
    "swe-agent": "https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md",
    "openhands": "https://docs.openhands.dev/sdk/arch/events",
    "opentelemetry-genai": "https://opentelemetry.io/blog/2026/genai-observability/",
    "openinference": "https://github.com/Arize-ai/openinference/blob/main/spec/traces.md",
}
LABELS = (
    "healthy",
    "unsupported-final",
    "failure-masking",
    "retry-loop",
    "context-decay",
    "polish-without-progress",
    "cost-pressure",
    "uncertainty",
)
EXTERNAL_SOURCE_CLASSES = (
    "external-public-swe-agent-trajectory",
    "external-public-openhands-event-log",
    "external-public-opentelemetry-genai-trace",
    "external-public-openinference-trace",
)
DATASET_SIZE = len(LABELS) * CURATED_TRAJECTORIES_PER_LABEL + len(EXTERNAL_SOURCE_CLASSES) * EXTERNAL_TRAJECTORIES_PER_SOURCE
TRACKED_COMPONENTS = tuple(WEIGHTS.keys())
REQUIRED_COMPONENT_SUPPORT = TRACKED_COMPONENTS
COMPONENT_SUPPORT_WAIVERS: dict[str, str] = {}
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
    *,
    source_class: str = "curated-public-safe",
    workflow_class: str = "calibration",
    label_source: str = "project-maintainer curated public-safe trajectory",
    redaction_status: str = "no-private-content",
    source_uri: str = "internal://hulunguard/calibration/curated",
) -> dict[str, Any]:
    return {
        "schema": DATASET_SCHEMA,
        "id": case_id,
        "label": label,
        "source_class": source_class,
        "workflow_class": workflow_class,
        "label_source": label_source,
        "redaction_status": redaction_status,
        "source_uri": source_uri,
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


def _cost_pressure(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Control {case_id} cost pressure budget review")
    _add_checkpoint(state, f"{case_id} budget checkpoint")
    for turn in range(1, 5):
        _append_event(
            state,
            "llm_call",
            f"{case_id} cost pressure budget review turn {turn} consumed tokens without evidence.",
            phase="plan",
            prompt_tokens=3500,
            completion_tokens=800,
            cost=1.6,
            latency_ms=65000,
        )
    return _trajectory(
        case_id,
        "cost-pressure",
        state,
        ["cost_pressure", "evidence_gap", "stagnation", "unfinished_criteria"],
        "High token, cost, and latency pressure accumulates without execution evidence.",
    )


def _uncertainty(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Resolve {case_id} uncertainty with source verification")
    _add_checkpoint(state, f"{case_id} uncertainty checkpoint")
    for turn in range(1, 5):
        _append_event(
            state,
            "llm_call",
            f"{case_id} uncertainty source verification is maybe probably okay, but not sure yet on turn {turn}.",
            phase="plan",
        )
    return _trajectory(
        case_id,
        "uncertainty",
        state,
        ["evidence_gap", "stagnation", "unfinished_criteria", "uncertainty"],
        "Uncertainty language repeats without fresh verification evidence.",
    )


def _external_swe_agent_retry_loop(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Fix {case_id} coding issue from SWE-agent trajectory replay")
    _add_checkpoint(state, f"{case_id} SWE-agent trajectory checkpoint")
    for attempt in range(1, 4):
        _append_event(
            state,
            "tool_result",
            f"{case_id} SWE-agent observation shows the same failing command on replay attempt {attempt}.",
            result="fail",
            phase="orchestrate",
            action_key=f"{case_id}-swe-agent-repeat-command",
        )
    return _trajectory(
        case_id,
        "retry-loop",
        state,
        ["evidence_gap", "retry_loop", "stagnation", "unfinished_criteria", "unhandled_failures"],
        "Public SWE-agent trajectory shape mapped to repeated unresolved command observations.",
        source_class="external-public-swe-agent-trajectory",
        workflow_class="coding",
        label_source="public SWE-agent trajectory schema plus maintainer component labels",
        redaction_status="public-schema-derived-no-private-content",
        source_uri=PUBLIC_SOURCE_URIS["swe-agent"],
    )


def _external_openhands_failure_masking(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Recover {case_id} OpenHands workspace command failure")
    _add_checkpoint(state, f"{case_id} OpenHands event log checkpoint")
    for attempt in range(1, 3):
        _append_event(
            state,
            "tool_result",
            f"{case_id} OpenHands observation event reports workspace command failed on attempt {attempt}.",
            result="fail",
            phase="recover",
            action_key=f"{case_id}-openhands-command",
        )
    _append_event(
        state,
        "final_attempt",
        f"{case_id} OpenHands workspace command failure is fixed and verified.",
        phase="final",
        claims=["fixed", "verified"],
    )
    return _trajectory(
        case_id,
        "failure-masking",
        state,
        ["claim_overhang", "evidence_gap", "unfinished_criteria", "phase_disorder", "stagnation", "unhandled_failures"],
        "Public OpenHands event-log model mapped to unresolved failed observations followed by a final claim.",
        source_class="external-public-openhands-event-log",
        workflow_class="ops",
        label_source="public OpenHands event-system docs plus maintainer component labels",
        redaction_status="public-schema-derived-no-private-content",
        source_uri=PUBLIC_SOURCE_URIS["openhands"],
    )


def _external_opentelemetry_cost_pressure(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Control {case_id} OpenTelemetry GenAI trace cost budget")
    _add_checkpoint(state, f"{case_id} OpenTelemetry GenAI checkpoint")
    for turn in range(1, 5):
        _append_event(
            state,
            "llm_call",
            f"{case_id} OpenTelemetry GenAI span {turn} reports token and latency growth without evidence.",
            phase="plan",
            prompt_tokens=3400,
            completion_tokens=850,
            cost=1.55,
            latency_ms=64000,
        )
    return _trajectory(
        case_id,
        "cost-pressure",
        state,
        ["cost_pressure", "evidence_gap", "stagnation", "unfinished_criteria"],
        "Public OpenTelemetry GenAI telemetry shape mapped to token, cost, and latency pressure.",
        source_class="external-public-opentelemetry-genai-trace",
        workflow_class="artifact",
        label_source="public OpenTelemetry GenAI observability docs plus maintainer component labels",
        redaction_status="public-schema-derived-no-private-content",
        source_uri=PUBLIC_SOURCE_URIS["opentelemetry-genai"],
    )


def _external_openinference_uncertainty(index: int) -> dict[str, Any]:
    case_id = f"HG-T{index:03d}"
    state = _base_state(case_id, f"Verify {case_id} OpenInference research trace answer")
    _add_checkpoint(state, f"{case_id} OpenInference trace checkpoint")
    for turn in range(1, 5):
        _append_event(
            state,
            "llm_call",
            f"{case_id} OpenInference LLM span maybe probably answers from retrieved context, not sure on turn {turn}.",
            phase="plan",
        )
    return _trajectory(
        case_id,
        "uncertainty",
        state,
        ["evidence_gap", "stagnation", "unfinished_criteria", "uncertainty"],
        "Public OpenInference trace taxonomy mapped to repeated uncertainty without verification evidence.",
        source_class="external-public-openinference-trace",
        workflow_class="research",
        label_source="public OpenInference trace spec plus maintainer component labels",
        redaction_status="public-schema-derived-no-private-content",
        source_uri=PUBLIC_SOURCE_URIS["openinference"],
    )


def build_trajectory_dataset() -> list[dict[str, Any]]:
    curated_builders = (
        _healthy,
        _unsupported_final,
        _failure_masking,
        _retry_loop,
        _context_decay,
        _polish_without_progress,
        _cost_pressure,
        _uncertainty,
    )
    external_builders = (
        _external_swe_agent_retry_loop,
        _external_openhands_failure_masking,
        _external_opentelemetry_cost_pressure,
        _external_openinference_uncertainty,
    )
    dataset: list[dict[str, Any]] = []
    index = 1
    for builder in curated_builders:
        for _ in range(CURATED_TRAJECTORIES_PER_LABEL):
            dataset.append(builder(index))
            index += 1
    for builder in external_builders:
        for _ in range(EXTERNAL_TRAJECTORIES_PER_SOURCE):
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


def _field_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _component_support(rows: list[dict[str, Any]], component_names: Iterable[str]) -> dict[str, dict[str, int | str | None]]:
    support: dict[str, dict[str, int | str | None]] = {}
    for component in component_names:
        support[component] = {
            "expected_positive": sum(1 for row in rows if component in row["expected_components"]),
            "predicted_positive": sum(1 for row in rows if component in row["predicted_components"]),
            "waiver": COMPONENT_SUPPORT_WAIVERS.get(component),
        }
    return support


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
                "source_class": item["source_class"],
                "workflow_class": item["workflow_class"],
                "label_source": item["label_source"],
                "redaction_status": item["redaction_status"],
                "source_uri": item["source_uri"],
                "expected_components": expected_components,
                "predicted_components": predicted_components,
                "score": risk["score"],
                "band": risk["band"],
                "required_action": risk["required_action"],
                "matched": expected_components == predicted_components,
            }
        )

    component_metrics = _component_metrics(rows, TRACKED_COMPONENTS)
    component_support = _component_support(rows, TRACKED_COMPONENTS)
    failures = [
        {
            "component": component,
            "precision": values["precision"],
            "recall": values["recall"],
        }
        for component, values in component_metrics.items()
        if float(values["precision"]) < min_precision or float(values["recall"]) < min_recall
    ]
    support_failures = [
        {
            "component": component,
            "expected_positive": component_support[component]["expected_positive"],
            "waiver": component_support[component]["waiver"],
        }
        for component in REQUIRED_COMPONENT_SUPPORT
        if int(component_support[component]["expected_positive"]) == 0 and not component_support[component]["waiver"]
    ]
    mismatches = [row for row in rows if not row["matched"]]
    passed = not failures and not support_failures and not mismatches and len(rows) == DATASET_SIZE
    return {
        "schema": CALIBRATION_SCHEMA,
        "generated_at": utc_now(),
        "dataset": {
            "schema": DATASET_SCHEMA,
            "size": len(rows),
            "labels": _label_counts(rows),
            "source_classes": _field_counts(rows, "source_class"),
            "workflow_classes": _field_counts(rows, "workflow_class"),
            "label_sources": _field_counts(rows, "label_source"),
            "redaction_statuses": _field_counts(rows, "redaction_status"),
            "source_uris": sorted({row["source_uri"] for row in rows}),
            "component_positive_thresholds": {
                component: COMPONENT_POSITIVE_THRESHOLDS.get(component, 1) for component in TRACKED_COMPONENTS
            },
            "required_component_support": list(REQUIRED_COMPONENT_SUPPORT),
        },
        "gate": {
            "min_precision": min_precision,
            "min_recall": min_recall,
            "passed": passed,
            "failures": failures,
            "support_failures": support_failures,
            "mismatches": mismatches,
        },
        "component_support": component_support,
        "component_metrics": component_metrics,
        "trajectories": rows,
    }


def build_calibration_baseline(result: dict[str, Any], *, baseline_id: str, source_version: str) -> dict[str, Any]:
    return {
        "schema": CALIBRATION_BASELINE_SCHEMA,
        "baseline_id": baseline_id,
        "source_version": source_version,
        "dataset": result["dataset"],
        "component_support": result["component_support"],
        "component_metrics": {
            component: {
                "precision": values["precision"],
                "recall": values["recall"],
                "false_positive_rate": values["false_positive_rate"],
                "false_negative_rate": values["false_negative_rate"],
            }
            for component, values in result["component_metrics"].items()
        },
    }


def _add_count_regressions(
    regressions: list[dict[str, Any]],
    *,
    kind: str,
    baseline_counts: dict[str, Any],
    current_counts: dict[str, Any],
) -> None:
    for key, baseline_value in baseline_counts.items():
        current_value = current_counts.get(key, 0)
        if int(current_value) < int(baseline_value):
            regressions.append(
                {
                    "kind": kind,
                    "name": key,
                    "baseline": baseline_value,
                    "current": current_value,
                    "message": f"{kind} coverage for {key} decreased from {baseline_value} to {current_value}.",
                }
            )


def _add_set_regressions(
    regressions: list[dict[str, Any]],
    *,
    kind: str,
    baseline_values: Iterable[Any],
    current_values: Iterable[Any],
) -> None:
    current_set = {str(value) for value in current_values}
    for value in sorted({str(value) for value in baseline_values}):
        if value not in current_set:
            regressions.append(
                {
                    "kind": kind,
                    "name": value,
                    "baseline": "present",
                    "current": "missing",
                    "message": f"{kind} entry is missing: {value}.",
                }
            )


def compare_calibration_drift(
    current_result: dict[str, Any],
    baseline: dict[str, Any],
    *,
    rationale: str | None = None,
) -> dict[str, Any]:
    regressions: list[dict[str, Any]] = []
    baseline_dataset = baseline.get("dataset", {})
    current_dataset = current_result.get("dataset", {})
    baseline_size = int(baseline_dataset.get("size", 0))
    current_size = int(current_dataset.get("size", 0))
    if current_size < baseline_size:
        regressions.append(
            {
                "kind": "dataset_size",
                "name": "size",
                "baseline": baseline_size,
                "current": current_size,
                "message": f"dataset size decreased from {baseline_size} to {current_size}.",
            }
        )

    for field in ("labels", "source_classes", "workflow_classes", "redaction_statuses"):
        _add_count_regressions(
            regressions,
            kind=field,
            baseline_counts=baseline_dataset.get(field, {}),
            current_counts=current_dataset.get(field, {}),
        )
    _add_set_regressions(
        regressions,
        kind="source_uris",
        baseline_values=baseline_dataset.get("source_uris", []),
        current_values=current_dataset.get("source_uris", []),
    )

    baseline_support = baseline.get("component_support", {})
    current_support = current_result.get("component_support", {})
    for component, values in baseline_support.items():
        current_values = current_support.get(component, {})
        for field in ("expected_positive", "predicted_positive"):
            baseline_value = int(values.get(field, 0))
            current_value = int(current_values.get(field, 0))
            if current_value < baseline_value:
                regressions.append(
                    {
                        "kind": f"component_support.{field}",
                        "name": component,
                        "baseline": baseline_value,
                        "current": current_value,
                        "message": f"{component} {field} decreased from {baseline_value} to {current_value}.",
                    }
                )

    baseline_metrics = baseline.get("component_metrics", {})
    current_metrics = current_result.get("component_metrics", {})
    for component, values in baseline_metrics.items():
        current_values = current_metrics.get(component, {})
        for field in ("precision", "recall"):
            baseline_value = float(values.get(field, 0.0))
            current_value = float(current_values.get(field, 0.0))
            if current_value < baseline_value:
                regressions.append(
                    {
                        "kind": f"component_metrics.{field}",
                        "name": component,
                        "baseline": round(baseline_value, 4),
                        "current": round(current_value, 4),
                        "message": f"{component} {field} decreased from {baseline_value:.4f} to {current_value:.4f}.",
                    }
                )

    status = "pass"
    passed = True
    if regressions and rationale:
        status = "warn"
    elif regressions:
        status = "fail"
        passed = False

    return {
        "schema": CALIBRATION_DRIFT_SCHEMA,
        "generated_at": utc_now(),
        "baseline": {
            "schema": baseline.get("schema"),
            "baseline_id": baseline.get("baseline_id"),
            "source_version": baseline.get("source_version"),
        },
        "current": {
            "dataset_size": current_dataset.get("size"),
            "gate_passed": current_result.get("gate", {}).get("passed"),
        },
        "gate": {
            "status": status,
            "passed": passed,
            "regression_count": len(regressions),
            "rationale": rationale,
        },
        "regressions": regressions,
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
            "## Source Coverage",
            "",
            "| Source class | Count |",
            "| --- | ---: |",
        ]
    )
    for source_class, count in result["dataset"]["source_classes"].items():
        lines.append(f"| {source_class} | {count} |")

    lines.extend(
        [
            "",
            "| Workflow class | Count |",
            "| --- | ---: |",
        ]
    )
    for workflow_class, count in result["dataset"]["workflow_classes"].items():
        lines.append(f"| {workflow_class} | {count} |")

    lines.extend(
        [
            "",
            "| Redaction status | Count |",
            "| --- | ---: |",
        ]
    )
    for redaction_status, count in result["dataset"]["redaction_statuses"].items():
        lines.append(f"| {redaction_status} | {count} |")

    lines.extend(
        [
            "",
            "## Component Support",
            "",
            "| Component | Expected positive | Predicted positive | Waiver |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for component, values in result["component_support"].items():
        lines.append(
            f"| {component} | {values['expected_positive']} | {values['predicted_positive']} | "
            f"{values['waiver'] or ''} |"
        )

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


def build_calibration_drift_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# HulunGuard Calibration Drift Report",
        "",
        f"Generated: {result['generated_at']}",
        f"Baseline: {result['baseline'].get('baseline_id') or 'unknown'}",
        f"Baseline version: {result['baseline'].get('source_version') or 'unknown'}",
        f"Current dataset size: {result['current'].get('dataset_size')}",
        f"Gate: {result['gate']['status']}",
        f"Regressions: {result['gate']['regression_count']}",
    ]
    if result["gate"].get("rationale"):
        lines.append(f"Rationale: {result['gate']['rationale']}")
    lines.extend(["", "## Regressions", ""])
    if result["regressions"]:
        for regression in result["regressions"]:
            lines.append(
                f"- {regression['kind']} `{regression['name']}`: "
                f"{regression['baseline']} -> {regression['current']}. {regression['message']}"
            )
    else:
        lines.append("No calibration drift regressions.")
    return "\n".join(lines) + "\n"


def calibration_drift_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
