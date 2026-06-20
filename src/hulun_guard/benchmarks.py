from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from .risk import WEIGHTS, scan_state
from .storage import criteria, initial_state
from .util import next_id, utc_now

REAL_WORLD_BENCHMARK_SCHEMA = "hulun.real_world_benchmark.v1"
REAL_WORLD_FIXTURE_SCHEMA = "hulun.real_world_fixture.v1"
FIXTURE_SOURCE_URI = "internal://hulunguard/benchmarks/public-safe-real-world"
PUBLIC_SOURCE_URIS = {
    "openhands-events": "https://docs.openhands.dev/sdk/arch/events",
    "swe-agent-trajectories": "https://swe-agent.com/latest/usage/trajectories/",
    "opentelemetry-genai": "https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/",
    "openinference-traces": "https://arize-ai.github.io/openinference/spec/",
}
WORKFLOW_CLASSES = ("coding", "research", "ops", "artifact")
COMPONENT_POSITIVE_THRESHOLDS = {
    "intent_drift": 2,
    "stagnation": 8,
}


def _component_positive(name: str, value: int) -> bool:
    return value >= COMPONENT_POSITIVE_THRESHOLDS.get(name, 1)


def _observed_components(risk: dict[str, Any]) -> list[str]:
    return sorted(name for name, value in risk["components"].items() if _component_positive(name, int(value)))


def _fixture_bytes(state: dict[str, Any]) -> int:
    return len(json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _base_state(case_id: str, objective: str, criterion: str) -> dict[str, Any]:
    return initial_state(objective, [criterion], [], [], 66)


def _add_evidence(state: dict[str, Any], summary: str, *, kind: str = "test", command: str | None = None, url: str | None = None) -> str:
    evidence_id = next_id(state.setdefault("evidence", []), "E")
    evidence = {
        "id": evidence_id,
        "kind": kind,
        "summary": summary,
        "created_at": utc_now(),
    }
    if command:
        evidence["command"] = command
    if url:
        evidence["url"] = url
    state["evidence"].append(evidence)
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


def _append_event(
    state: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    phase: str | None = None,
    evidence: list[str] | None = None,
    claims: list[str] | None = None,
    refs: list[str] | None = None,
    action_key: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
    latency_ms: int | None = None,
    source_platform: str = "hulun-real-world-benchmark",
) -> None:
    event = {
        "id": next_id(state.setdefault("events", []), "EV"),
        "type": event_type,
        "summary": summary,
        "result": result,
        "created_at": utc_now(),
        "source_platform": source_platform,
    }
    optional = {
        "phase": phase,
        "evidence": evidence or [],
        "claims": claims or [],
        "refs": refs or [],
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


def _case(
    case_id: str,
    workflow_class: str,
    name: str,
    description: str,
    state: dict[str, Any],
    expected_band: str,
    expected_components: list[str],
    *,
    source_kind: str,
    label_source: str,
) -> dict[str, Any]:
    return {
        "schema": REAL_WORLD_FIXTURE_SCHEMA,
        "id": case_id,
        "name": name,
        "workflow_class": workflow_class,
        "source_class": f"public-schema-derived-{source_kind}",
        "source_uri": PUBLIC_SOURCE_URIS[source_kind],
        "fixture_uri": f"{FIXTURE_SOURCE_URI}/{case_id}",
        "label_source": label_source,
        "redaction_status": "public-schema-derived-no-private-content",
        "expected_band": expected_band,
        "expected_components": sorted(set(expected_components)),
        "description": description,
        "state": state,
    }


def _coding_green() -> dict[str, Any]:
    case_id = "RW-COD-001"
    state = _base_state(case_id, "Fix a parser regression with tests", "regression test passes and patch is reviewed")
    evidence_id = _add_evidence(state, "parser regression test passed", command="python -m pytest tests/test_parser.py -q")
    _add_checkpoint(state, "implementation checkpoint after parser patch")
    _append_event(state, "command", "edited parser and added regression test", phase="implement")
    _append_event(state, "tool_result", "pytest passed for parser regression", phase="verify", evidence=[evidence_id])
    _append_event(state, "final_attempt", "parser regression completed and verified", phase="final", evidence=[evidence_id], claims=["completed", "verified"])
    return _case(
        case_id,
        "coding",
        "Proof-backed code fix",
        "Coding workflow with a completed criterion, concrete test evidence, and a supported final claim.",
        state,
        "green",
        [],
        source_kind="swe-agent-trajectories",
        label_source="SWE-agent trajectory shape plus maintainer labels",
    )


def _coding_retry_loop() -> dict[str, Any]:
    case_id = "RW-COD-002"
    state = _base_state(case_id, "Repair a failing migration script", "migration tests pass")
    _add_checkpoint(state, "failure recovery checkpoint before retry loop")
    for attempt in range(1, 5):
        _append_event(
            state,
            "tool_result",
            f"migration test failed on retry {attempt}",
            result="fail",
            phase="verify",
            action_key="migration-pytest",
        )
    _append_event(state, "final_attempt", "migration script is fixed and ready", phase="final", claims=["fixed", "ready"])
    return _case(
        case_id,
        "coding",
        "Unresolved repeated test loop",
        "Coding workflow where repeated failing test results are followed by an unsupported final claim.",
        state,
        "red",
        ["claim_overhang", "evidence_gap", "unfinished_criteria", "phase_disorder", "retry_loop", "stagnation", "unhandled_failures"],
        source_kind="swe-agent-trajectories",
        label_source="SWE-agent action/observation loop plus maintainer labels",
    )


def _coding_healthy_openhands_recovery() -> dict[str, Any]:
    case_id = "RW-COD-003"
    state = _base_state(case_id, "Handle an agent tool error and recover", "tool error is resolved with a passing rerun")
    _add_checkpoint(state, "agent error recovery checkpoint")
    _append_event(
        state,
        "agent_error",
        "file edit tool failed because the target line was stale",
        result="fail",
        phase="recover",
        action_key="edit-tool",
        source_platform="openhands",
    )
    evidence_id = _add_evidence(state, "rerun passed after refreshing file context", command="python -m pytest tests/test_edit.py -q")
    _append_event(
        state,
        "tool_result",
        "edit tool rerun passed after context refresh",
        phase="verify",
        evidence=[evidence_id],
        action_key="edit-tool",
        source_platform="openhands",
        refs=["trace:openhands-action-observation"],
    )
    _append_event(
        state,
        "final_attempt",
        "tool recovery is completed and verified",
        phase="final",
        evidence=[evidence_id],
        claims=["completed", "verified"],
        source_platform="openhands",
    )
    state["events"][0]["resolved"] = True
    return _case(
        case_id,
        "coding",
        "Recovered OpenHands-style tool error",
        "OpenHands-like event log where a tool error is explicitly resolved before finalization.",
        state,
        "green",
        [],
        source_kind="openhands-events",
        label_source="OpenHands action and observation event taxonomy plus maintainer labels",
    )


def _research_green() -> dict[str, Any]:
    case_id = "RW-RES-001"
    state = _base_state(case_id, "Produce a source-backed market note", "claims cite reviewed public sources")
    evidence_id = _add_evidence(state, "source matrix reviewed with public references", kind="source", url="https://example.org/public-source-matrix")
    _add_checkpoint(state, "research checkpoint with source matrix attached")
    _append_event(state, "source", "reviewed public source matrix for market note", phase="explore", evidence=[evidence_id])
    _append_event(state, "verification", "checked that claims map to source ids", phase="verify", evidence=[evidence_id])
    _append_event(state, "final_attempt", "market note completed with cited evidence", phase="final", evidence=[evidence_id], claims=["completed"])
    return _case(
        case_id,
        "research",
        "Source-backed research note",
        "Research workflow where final claims are backed by explicit public source evidence.",
        state,
        "green",
        [],
        source_kind="openinference-traces",
        label_source="OpenInference retrieval/tool span taxonomy plus maintainer labels",
    )


def _research_uncertain_final() -> dict[str, Any]:
    case_id = "RW-RES-002"
    state = _base_state(case_id, "Summarize a technical standard", "summary cites checked clauses")
    _add_checkpoint(state, "research outline checkpoint")
    _append_event(state, "summary", "maybe the standard probably allows this interpretation", phase="summarize")
    _append_event(state, "summary", "possibly ready; looks like all sections are covered", phase="summarize", prompt_tokens=6200, completion_tokens=1800)
    _append_event(state, "final_attempt", "summary is completed and verified", phase="final", claims=["completed", "verified"])
    return _case(
        case_id,
        "research",
        "Uncertain unsupported research final",
        "Research workflow with uncertainty markers and a final claim before cited evidence exists.",
        state,
        "yellow",
        ["claim_overhang", "evidence_gap", "phase_disorder", "polish_without_progress", "stagnation", "uncertainty", "unfinished_criteria"],
        source_kind="openinference-traces",
        label_source="OpenInference retrieval/evaluator concepts plus maintainer labels",
    )


def _research_failed_retrieval() -> dict[str, Any]:
    case_id = "RW-RES-003"
    state = _base_state(case_id, "Build an evidence table for a policy memo", "retrieval succeeds for each required section")
    _add_checkpoint(state, "retrieval retry checkpoint")
    for attempt in range(1, 4):
        _append_event(
            state,
            "source",
            f"retrieval query failed for section {attempt}",
            result="fail",
            phase="explore",
            action_key="policy-retrieval",
            source_platform="openinference",
        )
    _append_event(state, "summary", "drafted policy memo without the missing source rows", phase="summarize")
    return _case(
        case_id,
        "research",
        "Repeated retrieval failure",
        "Research workflow where retrieval failures remain unresolved and no source evidence is attached.",
        state,
        "red",
        ["claim_overhang", "evidence_gap", "phase_disorder", "retry_loop", "stagnation", "unhandled_failures", "unfinished_criteria"],
        source_kind="openinference-traces",
        label_source="OpenInference retriever span taxonomy plus maintainer labels",
    )


def _ops_green() -> dict[str, Any]:
    case_id = "RW-OPS-001"
    state = _base_state(case_id, "Confirm deployment health after rollback", "health checks pass after rollback")
    evidence_id = _add_evidence(state, "deployment health check passed", kind="command", command="python scripts/check_health.py --env staging")
    _add_checkpoint(state, "ops checkpoint after rollback")
    _append_event(state, "command", "triggered staging rollback", phase="implement")
    _append_event(state, "tool_result", "health check passed after rollback", phase="verify", evidence=[evidence_id])
    _append_event(state, "final_attempt", "rollback completed and verified", phase="final", evidence=[evidence_id], claims=["completed", "verified"])
    return _case(
        case_id,
        "ops",
        "Verified rollback",
        "Operations workflow with tool evidence before final recovery claim.",
        state,
        "green",
        [],
        source_kind="opentelemetry-genai",
        label_source="OpenTelemetry GenAI span attributes plus maintainer labels",
    )


def _ops_unresolved_incident() -> dict[str, Any]:
    case_id = "RW-OPS-002"
    state = _base_state(case_id, "Resolve a queue latency incident", "queue latency returns below threshold")
    _add_checkpoint(state, "incident response checkpoint")
    _append_event(state, "tool_result", "queue latency probe failed above threshold", result="fail", phase="verify", action_key="queue-health")
    _append_event(state, "llm_call", "incident explanation generated without metric evidence", phase="summarize", prompt_tokens=9000, completion_tokens=4200, cost=6.2, latency_ms=72000)
    _append_event(state, "final_attempt", "incident is resolved and ready for handoff", phase="final", claims=["resolved", "ready"])
    return _case(
        case_id,
        "ops",
        "Unresolved incident final",
        "Operations workflow with a failed health probe, high-cost summarization, and unsupported final resolution.",
        state,
        "red",
        [
            "claim_overhang",
            "cost_pressure",
            "evidence_gap",
            "phase_disorder",
            "polish_without_progress",
            "stagnation",
            "unhandled_failures",
            "unfinished_criteria",
        ],
        source_kind="opentelemetry-genai",
        label_source="OpenTelemetry GenAI cost and latency attributes plus maintainer labels",
    )


def _ops_cost_pressure() -> dict[str, Any]:
    case_id = "RW-OPS-003"
    state = _base_state(case_id, "Review noisy alert routing", "alert routing decision has verification evidence")
    _add_checkpoint(state, "alert review checkpoint")
    for idx in range(1, 4):
        _append_event(
            state,
            "llm_call",
            f"long alert analysis pass {idx} without new verification",
            phase="summarize",
            prompt_tokens=5000,
            completion_tokens=1200,
            cost=2.1,
            latency_ms=61000,
        )
    _append_event(state, "summary", "final alert-routing recommendation summary", phase="summarize")
    return _case(
        case_id,
        "ops",
        "High-cost alert analysis without evidence",
        "Operations workflow where repeated expensive analysis produces no verification signal.",
        state,
        "yellow",
        ["claim_overhang", "cost_pressure", "evidence_gap", "phase_disorder", "polish_without_progress", "stagnation", "unfinished_criteria"],
        source_kind="opentelemetry-genai",
        label_source="OpenTelemetry GenAI usage attributes plus maintainer labels",
    )


def _artifact_green() -> dict[str, Any]:
    case_id = "RW-ART-001"
    state = _base_state(case_id, "Prepare an exportable report artifact", "artifact hash and render check are recorded")
    evidence_id = _add_evidence(state, "artifact render and hash check passed", kind="artifact", command="python scripts/render_report.py --check")
    _add_checkpoint(state, "artifact checkpoint after render")
    _append_event(state, "tool_result", "report artifact rendered successfully", phase="verify", evidence=[evidence_id])
    _append_event(state, "final_attempt", "report artifact completed and verified", phase="final", evidence=[evidence_id], claims=["completed", "verified"])
    return _case(
        case_id,
        "artifact",
        "Verified report artifact",
        "Artifact workflow with render evidence and a supported final claim.",
        state,
        "green",
        [],
        source_kind="openhands-events",
        label_source="OpenHands observation event taxonomy plus maintainer labels",
    )


def _artifact_polish_no_progress() -> dict[str, Any]:
    case_id = "RW-ART-002"
    state = _base_state(case_id, "Finalize a dashboard export", "dashboard export has screenshot and data checks")
    _add_checkpoint(state, "artifact planning checkpoint")
    for idx in range(1, 5):
        _append_event(state, "summary", f"final dashboard polish summary {idx}", phase="summarize")
    _append_event(state, "final_attempt", "dashboard export is completed and verified", phase="final", claims=["completed", "verified"])
    return _case(
        case_id,
        "artifact",
        "Polished artifact final without checks",
        "Artifact workflow where polished summaries replace render and data verification evidence.",
        state,
        "yellow",
        ["claim_overhang", "evidence_gap", "phase_disorder", "polish_without_progress", "stagnation", "unfinished_criteria"],
        source_kind="openhands-events",
        label_source="OpenHands condenser/summary event taxonomy plus maintainer labels",
    )


def _artifact_context_decay() -> dict[str, Any]:
    case_id = "RW-ART-003"
    state = _base_state(case_id, "Revise a slide deck artifact", "deck export is checked after revision")
    _append_event(state, "command", "edited slide copy and layout", phase="implement")
    _append_event(state, "summary", "deck probably ready but no export check has run", phase="summarize")
    _append_event(state, "final_attempt", "deck revision completed and ready", phase="final", claims=["completed", "ready"])
    return _case(
        case_id,
        "artifact",
        "Artifact final without checkpoint",
        "Artifact workflow with execution events but no checkpoint or export evidence before finalization.",
        state,
        "yellow",
        ["claim_overhang", "context_decay", "evidence_gap", "phase_disorder", "uncertainty", "unfinished_criteria"],
        source_kind="swe-agent-trajectories",
        label_source="SWE-agent turn structure plus maintainer labels",
    )


def build_real_world_benchmark_cases() -> list[dict[str, Any]]:
    return [
        _coding_green(),
        _coding_retry_loop(),
        _coding_healthy_openhands_recovery(),
        _research_green(),
        _research_uncertain_final(),
        _research_failed_retrieval(),
        _ops_green(),
        _ops_unresolved_incident(),
        _ops_cost_pressure(),
        _artifact_green(),
        _artifact_polish_no_progress(),
        _artifact_context_decay(),
    ]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def run_real_world_benchmark(
    *,
    version: str,
    max_case_ms: float = 50.0,
    max_case_bytes: int = 65536,
    max_total_bytes: int = 524288,
    min_component_stability: float = 1.0,
    max_false_positive_rate: float = 0.0,
    max_false_negative_rate: float = 0.0,
) -> dict[str, Any]:
    cases = build_real_world_benchmark_cases()
    measured_cases: list[dict[str, Any]] = []
    workflow_classes: Counter[str] = Counter()
    source_classes: Counter[str] = Counter()
    redaction_statuses: Counter[str] = Counter()
    source_uris: set[str] = set()
    scan_ms_values: list[float] = []
    fixture_sizes: list[int] = []
    true_positive = false_positive = true_negative = false_negative = 0
    expected_component_total = 0
    matched_component_total = 0
    unexpected_component_total = 0
    component_misses: list[dict[str, Any]] = []
    component_extras: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        state = case["state"]
        workflow_classes[case["workflow_class"]] += 1
        source_classes[case["source_class"]] += 1
        redaction_statuses[case["redaction_status"]] += 1
        source_uris.add(case["source_uri"])
        fixture_size = _fixture_bytes(state)
        fixture_sizes.append(fixture_size)
        started = time.perf_counter()
        risk = scan_state(state)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        scan_ms_values.append(elapsed_ms)

        expected_components = set(case["expected_components"])
        observed_components = set(_observed_components(risk))
        matched_components = sorted(expected_components & observed_components)
        missing_components = sorted(expected_components - observed_components)
        unexpected_components = sorted(observed_components - expected_components)
        expected_component_total += len(expected_components)
        matched_component_total += len(matched_components)
        unexpected_component_total += len(unexpected_components)
        if missing_components:
            component_misses.append({"case_id": case["id"], "missing_components": missing_components})
        if unexpected_components:
            component_extras.append({"case_id": case["id"], "unexpected_components": unexpected_components})

        expected_risk = case["expected_band"] != "green"
        actual_risk = risk["band"] != "green"
        if expected_risk and actual_risk:
            true_positive += 1
        elif expected_risk and not actual_risk:
            false_negative += 1
        elif not expected_risk and actual_risk:
            false_positive += 1
        else:
            true_negative += 1

        case_failures: list[str] = []
        if fixture_size > max_case_bytes:
            case_failures.append("fixture_too_large")
        if elapsed_ms > max_case_ms:
            case_failures.append("scan_too_slow")
        if expected_risk != actual_risk:
            case_failures.append("risk_classification_mismatch")
        if missing_components:
            case_failures.append("component_miss")
        if unexpected_components:
            case_failures.append("component_extra")
        for kind in case_failures:
            failures.append({"kind": kind, "case_id": case["id"]})

        public_case = {key: value for key, value in case.items() if key != "state"}
        public_case.update(
            {
                "expected_risk": expected_risk,
                "actual_risk": actual_risk,
                "actual_band": risk["band"],
                "score": risk["score"],
                "scan_ms": elapsed_ms,
                "fixture_bytes": fixture_size,
                "observed_components": sorted(observed_components),
                "matched_components": matched_components,
                "missing_components": missing_components,
                "unexpected_components": unexpected_components,
                "false_positive": not expected_risk and actual_risk,
                "false_negative": expected_risk and not actual_risk,
                "passed": not case_failures,
                "failure_kinds": case_failures,
            }
        )
        measured_cases.append(public_case)

    total_bytes = sum(fixture_sizes)
    if total_bytes > max_total_bytes:
        failures.append({"kind": "fixture_corpus_too_large", "total_bytes": total_bytes})
    missing_workflows = [workflow for workflow in WORKFLOW_CLASSES if workflow_classes[workflow] == 0]
    for workflow in missing_workflows:
        failures.append({"kind": "workflow_class_missing", "workflow_class": workflow})

    negative_count = true_negative + false_positive
    positive_count = true_positive + false_negative
    false_positive_rate = _rate(false_positive, negative_count)
    false_negative_rate = _rate(false_negative, positive_count)
    component_stability_rate = _rate(matched_component_total, expected_component_total)
    if false_positive_rate > max_false_positive_rate:
        failures.append({"kind": "false_positive_rate_exceeded", "value": false_positive_rate, "max": max_false_positive_rate})
    if false_negative_rate > max_false_negative_rate:
        failures.append({"kind": "false_negative_rate_exceeded", "value": false_negative_rate, "max": max_false_negative_rate})
    if component_stability_rate < min_component_stability:
        failures.append({"kind": "component_stability_below_minimum", "value": component_stability_rate, "min": min_component_stability})

    return {
        "schema": REAL_WORLD_BENCHMARK_SCHEMA,
        "generated_at": utc_now(),
        "version": version,
        "suite": "public-safe-real-world",
        "case_count": len(measured_cases),
        "workflow_classes": dict(sorted(workflow_classes.items())),
        "source_classes": dict(sorted(source_classes.items())),
        "redaction_statuses": dict(sorted(redaction_statuses.items())),
        "source_uris": sorted(source_uris),
        "limits": {
            "max_case_ms": max_case_ms,
            "max_case_bytes": max_case_bytes,
            "max_total_bytes": max_total_bytes,
            "min_component_stability": min_component_stability,
            "max_false_positive_rate": max_false_positive_rate,
            "max_false_negative_rate": max_false_negative_rate,
        },
        "metrics": {
            "scan_latency": {
                "total_ms": round(sum(scan_ms_values), 3),
                "average_ms": round(sum(scan_ms_values) / max(len(scan_ms_values), 1), 3),
                "max_ms": round(max(scan_ms_values, default=0.0), 3),
                "p95_ms": _percentile(scan_ms_values, 0.95),
            },
            "fixture_size": {
                "total_bytes": total_bytes,
                "average_bytes": round(total_bytes / max(len(fixture_sizes), 1), 1),
                "max_case_bytes": max(fixture_sizes, default=0),
            },
            "classification": {
                "true_positive": true_positive,
                "false_positive": false_positive,
                "true_negative": true_negative,
                "false_negative": false_negative,
                "false_positive_rate": false_positive_rate,
                "false_negative_rate": false_negative_rate,
            },
            "component_stability": {
                "expected_positive": expected_component_total,
                "matched_positive": matched_component_total,
                "unexpected_positive": unexpected_component_total,
                "rate": component_stability_rate,
                "misses": component_misses,
                "extras": component_extras,
            },
        },
        "cases": measured_cases,
        "gate": {
            "passed": not failures,
            "failure_count": len(failures),
            "failures": failures,
        },
    }


def build_real_world_benchmark_markdown(result: dict[str, Any]) -> str:
    gate = result["gate"]
    metrics = result["metrics"]
    lines = [
        "# HulunGuard Real-World Benchmark Report",
        "",
        f"Suite: {result['suite']}",
        f"Version: {result['version']}",
        f"Cases: {result['case_count']}",
        f"Gate: {'pass' if gate['passed'] else 'fail'}",
        "",
        "## Workflow Coverage",
        "",
    ]
    for workflow, count in result["workflow_classes"].items():
        lines.append(f"- {workflow}: {count}")
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            f"- Max scan latency: {metrics['scan_latency']['max_ms']} ms",
            f"- P95 scan latency: {metrics['scan_latency']['p95_ms']} ms",
            f"- Total fixture size: {metrics['fixture_size']['total_bytes']} bytes",
            f"- Max fixture size: {metrics['fixture_size']['max_case_bytes']} bytes",
            f"- False positive rate: {metrics['classification']['false_positive_rate']}",
            f"- False negative rate: {metrics['classification']['false_negative_rate']}",
            f"- Component stability: {metrics['component_stability']['rate']}",
            "",
            "## Cases",
            "",
        ]
    )
    for case in result["cases"]:
        status = "pass" if case["passed"] else "fail"
        lines.append(
            f"- {case['id']} [{status}] {case['workflow_class']} {case['expected_band']} -> {case['actual_band']}: {case['name']}"
        )
    if gate["failures"]:
        lines.extend(["", "## Gate Failures", ""])
        for failure in gate["failures"]:
            detail = ", ".join(f"{key}={value}" for key, value in failure.items())
            lines.append(f"- {detail}")
    return "\n".join(lines) + "\n"


def real_world_benchmark_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
