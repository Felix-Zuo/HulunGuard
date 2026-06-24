from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .constants import VALID_STATUSES
from .privacy import DEFAULT_RETENTION_DAYS
from .util import utc_now

STATE_SCHEMA = "hulun.state.v1"
RISK_SCHEMA = "hulun.risk.v1"
CONVERSATION_SCHEMA = "hulun.conversation.v1"
CONVERSATION_RISK_SCHEMA = "hulun.conversation_risk.v1"
VALIDATION_SCHEMA = "hulun.validation.v1"
TRAJECTORY_DATASET_SCHEMA = "hulun.trajectory_dataset.v1"
CALIBRATION_SCHEMA = "hulun.calibration.v1"
CALIBRATION_BASELINE_SCHEMA = "hulun.calibration_baseline.v1"
CALIBRATION_DRIFT_SCHEMA = "hulun.calibration_drift.v1"
BENCHMARK_SCHEMA = "hulun.benchmark.v1"
REAL_WORLD_BENCHMARK_SCHEMA = "hulun.real_world_benchmark.v1"
REAL_WORLD_FIXTURE_SCHEMA = "hulun.real_world_fixture.v1"
RETENTION_CLEANUP_SCHEMA = "hulun.retention_cleanup.v1"
DOCTOR_SCHEMA = "hulun.doctor.v1"
EXPORT_OPENTELEMETRY_SCHEMA = "hulun.export.opentelemetry.v1"
ADAPTER_MATRIX_SCHEMA = "hulun.adapter_matrix.v1"
AGENT_COMPATIBILITY_SCHEMA = "hulun.agent_compatibility.v1"
INTEGRATION_KIT_SCHEMA = "hulun.integration_kit.v1"
ONBOARDING_SCHEMA = "hulun.onboarding.v1"
CALIBRATION_DRIFT_ERROR_SCHEMA = "hulun.calibration_drift_error.v1"
SCHEMA_COMPATIBILITY_SCHEMA = "hulun.schema_compatibility.v1"
MONITOR_SCHEMA = "hulun.monitor.v1"
THREAT_MODEL_CHECK_SCHEMA = "hulun.threat_model_check.v1"
GITHUB_RELEASE_VERIFICATION_SCHEMA = "hulun.github_release_verification.v1"
TRACE_DOCTOR_SCHEMA = "hulun.trace_doctor.v1"
BATCH_INGEST_SCHEMA = "hulun.batch_ingest.v1"
COLLECTOR_SCHEMA = "hulun.collector.v1"
DEFAULT_SCHEMA_FIXTURE_DIR = Path(__file__).with_name("schema_fixtures")
RISK_WEIGHTS = {
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

SUPPORTED_PUBLIC_SCHEMAS: dict[str, dict[str, Any]] = {
    "state": {
        "current": STATE_SCHEMA,
        "supported": [STATE_SCHEMA, "legacy:missing-schema"],
        "promise": "Project ledgers are normalized in place without dropping evidence, privacy, events, checkpoints, or last risk scan fields.",
    },
    "risk": {"current": RISK_SCHEMA, "supported": [RISK_SCHEMA, "legacy:missing-schema"], "promise": "Risk reports preserve score, band, components, reasons, and action fields."},
    "conversation": {
        "current": CONVERSATION_SCHEMA,
        "supported": [CONVERSATION_SCHEMA, "legacy:missing-schema"],
        "promise": "Conversation ledgers preserve events, privacy metadata, monitor ids, and last conversation-risk scan fields.",
    },
    "conversation_risk": {
        "current": CONVERSATION_RISK_SCHEMA,
        "supported": [CONVERSATION_RISK_SCHEMA, "legacy:missing-schema"],
        "promise": "Conversation risk reports preserve score, band, components, reasons, and action fields.",
    },
    "validation": {"current": VALIDATION_SCHEMA, "supported": [VALIDATION_SCHEMA, "legacy:missing-schema"], "promise": "Validation reports preserve pass counts and scenario summaries."},
    "trajectory_dataset": {
        "current": TRAJECTORY_DATASET_SCHEMA,
        "supported": [TRAJECTORY_DATASET_SCHEMA],
        "promise": "Calibration trajectory dataset summaries preserve size, labels, source coverage, workflow coverage, and redaction coverage.",
    },
    "calibration": {"current": CALIBRATION_SCHEMA, "supported": [CALIBRATION_SCHEMA, "legacy:missing-schema"], "promise": "Calibration reports preserve dataset, gate, component support, metrics, and trajectories."},
    "calibration_baseline": {
        "current": CALIBRATION_BASELINE_SCHEMA,
        "supported": [CALIBRATION_BASELINE_SCHEMA],
        "promise": "Calibration baselines are append-stable and compared by drift gates.",
    },
    "calibration_drift": {
        "current": CALIBRATION_DRIFT_SCHEMA,
        "supported": [CALIBRATION_DRIFT_SCHEMA, "legacy:missing-schema"],
        "promise": "Calibration drift reports preserve baseline, current gate, regressions, and rationale.",
    },
    "benchmark": {"current": BENCHMARK_SCHEMA, "supported": [BENCHMARK_SCHEMA, "legacy:missing-schema"], "promise": "Scan benchmark reports preserve event count, latency, throughput, and pass/fail gate."},
    "real_world_benchmark": {
        "current": REAL_WORLD_BENCHMARK_SCHEMA,
        "supported": [REAL_WORLD_BENCHMARK_SCHEMA, "legacy:missing-schema"],
        "promise": "Real-world benchmark reports preserve suite coverage, limits, metrics, cases, and gate failures.",
    },
    "real_world_fixture": {
        "current": REAL_WORLD_FIXTURE_SCHEMA,
        "supported": [REAL_WORLD_FIXTURE_SCHEMA],
        "promise": "Real-world benchmark fixture fields are public-safe and schema-versioned.",
    },
    "retention_cleanup": {
        "current": RETENTION_CLEANUP_SCHEMA,
        "supported": [RETENTION_CLEANUP_SCHEMA],
        "promise": "Retention cleanup reports preserve dry-run/apply mode, summary, safety violations, and gate result.",
    },
    "doctor": {"current": DOCTOR_SCHEMA, "supported": [DOCTOR_SCHEMA], "promise": "Doctor reports preserve check names, statuses, details, and final result."},
    "export_opentelemetry": {
        "current": EXPORT_OPENTELEMETRY_SCHEMA,
        "supported": [EXPORT_OPENTELEMETRY_SCHEMA, "legacy:missing-schema"],
        "promise": "Adapter command reports preserve output path and exported span count. The export payload itself follows OTLP JSON.",
    },
    "adapter_matrix": {
        "current": ADAPTER_MATRIX_SCHEMA,
        "supported": [ADAPTER_MATRIX_SCHEMA],
        "promise": "Adapter integration reports preserve support tiers, public-safe fixture policy, case outcomes, and gate failures.",
    },
    "agent_compatibility": {
        "current": AGENT_COMPATIBILITY_SCHEMA,
        "supported": [AGENT_COMPATIBILITY_SCHEMA],
        "promise": "Agent compatibility reports preserve supported agents, integration category, tier, source URI, ingest format, and command.",
    },
    "integration_kit": {
        "current": INTEGRATION_KIT_SCHEMA,
        "supported": [INTEGRATION_KIT_SCHEMA],
        "promise": "Integration kit reports preserve requested agent, generated files, ingest command, sample trace path, and verification outcome.",
    },
    "onboarding": {
        "current": ONBOARDING_SCHEMA,
        "supported": [ONBOARDING_SCHEMA],
        "promise": "Onboarding reports preserve requested agent, generated kit location, sample verification, sandbox import outcome, and next-step commands.",
    },
    "calibration_drift_error": {
        "current": CALIBRATION_DRIFT_ERROR_SCHEMA,
        "supported": [CALIBRATION_DRIFT_ERROR_SCHEMA],
        "promise": "Calibration-drift error payloads preserve error kind, baseline path, and diagnostic detail.",
    },
    "schema_compatibility": {
        "current": SCHEMA_COMPATIBILITY_SCHEMA,
        "supported": [SCHEMA_COMPATIBILITY_SCHEMA],
        "promise": "Schema compatibility reports preserve fixture outcomes, generated schemas, and release gate failures.",
    },
    "monitor": {"current": MONITOR_SCHEMA, "supported": [MONITOR_SCHEMA], "promise": "Monitor ledgers preserve live score, band, group, conversation, and status."},
    "threat_model_check": {
        "current": THREAT_MODEL_CHECK_SCHEMA,
        "supported": [THREAT_MODEL_CHECK_SCHEMA],
        "promise": "Threat model check reports preserve documented boundary checks, link checks, and gate failures.",
    },
    "github_release_verification": {
        "current": GITHUB_RELEASE_VERIFICATION_SCHEMA,
        "supported": [GITHUB_RELEASE_VERIFICATION_SCHEMA],
        "promise": "GitHub release verification reports preserve repository, tag, asset directory, checksum, SBOM, attestation, and gate fields.",
    },
    "trace_doctor": {
        "current": TRACE_DOCTOR_SCHEMA,
        "supported": [TRACE_DOCTOR_SCHEMA],
        "promise": "Trace doctor reports preserve file, detected format, selected format, observation counts, field coverage, warnings, next command, and gate fields.",
    },
    "batch_ingest": {
        "current": BATCH_INGEST_SCHEMA,
        "supported": [BATCH_INGEST_SCHEMA],
        "promise": "Batched ingestion reports preserve operation, queue status, imported counts, event ids, and dead-letter counts.",
    },
    "collector": {
        "current": COLLECTOR_SCHEMA,
        "supported": [COLLECTOR_SCHEMA],
        "promise": "Collector reports preserve health, status, ingest, smoke, managed flush, operations status, service template, endpoint, queue, auth, limit, response, runtime, generated file, and gate fields.",
    },
}

_SCHEMA_RE = re.compile(r"^(?P<family>.+)\.v(?P<major>\d+)$")


class SchemaCompatibilityError(ValueError):
    """Raised when a payload declares an unsupported HulunGuard schema."""


def schema_family(schema: str | None) -> str | None:
    if not schema:
        return None
    match = _SCHEMA_RE.match(schema)
    return match.group("family") if match else None


def schema_major(schema: str | None) -> int | None:
    if not schema:
        return None
    match = _SCHEMA_RE.match(schema)
    return int(match.group("major")) if match else None


def _schema_supported(kind: str, schema: str | None) -> bool:
    entry = SUPPORTED_PUBLIC_SCHEMAS[kind]
    if not schema:
        return "legacy:missing-schema" in entry["supported"]
    current = str(entry["current"])
    return schema_family(schema) == schema_family(current) and schema_major(schema) in {1}


def ensure_supported_schema(kind: str, payload: dict[str, Any]) -> None:
    schema = payload.get("schema")
    if schema is not None and not isinstance(schema, str):
        raise SchemaCompatibilityError(f"{kind} schema must be a string.")
    if not _schema_supported(kind, schema):
        raise SchemaCompatibilityError(f"Unsupported {kind} schema: {schema or 'missing'}")


def _copy_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _timestamp(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else utc_now()


def _privacy(record: dict[str, Any]) -> dict[str, Any]:
    existing = record.get("privacy") if isinstance(record.get("privacy"), dict) else {}
    value = existing.get("retention_days", DEFAULT_RETENTION_DAYS)
    try:
        retention_days = max(1, int(value))
    except (TypeError, ValueError):
        retention_days = DEFAULT_RETENTION_DAYS
    return {"mode": str(existing.get("mode") or "redacted-default"), "retention_days": retention_days}


def _status(value: Any) -> str:
    text = str(value or "pending")
    return text if text in VALID_STATUSES else "pending"


def _normalize_item(value: Any, prefix: str, index: int) -> tuple[dict[str, Any] | None, Any | None]:
    if isinstance(value, str):
        return {"id": f"{prefix}{index}", "text": value, "status": "pending", "evidence": []}, None
    if not isinstance(value, dict):
        return None, value
    item = _copy_dict(value)
    item["id"] = str(item.get("id") or f"{prefix}{index}")
    item["text"] = str(item.get("text") or item.get("summary") or item.get("criterion") or item.get("description") or "")
    item["status"] = _status(item.get("status"))
    item["evidence"] = _string_list(item.get("evidence") or item.get("evidence_ids"))
    return item, None


def _normalize_evidence(value: Any, index: int) -> tuple[dict[str, Any] | None, Any | None]:
    if isinstance(value, str):
        return {"id": f"E{index}", "kind": "other", "summary": value, "created_at": utc_now(), "privacy": {"mode": "redacted-default", "retention_days": DEFAULT_RETENTION_DAYS}}, None
    if not isinstance(value, dict):
        return None, value
    evidence = _copy_dict(value)
    evidence["id"] = str(evidence.get("id") or f"E{index}")
    evidence["kind"] = str(evidence.get("kind") or evidence.get("type") or "other")
    evidence["summary"] = str(evidence.get("summary") or evidence.get("text") or evidence.get("description") or "")
    evidence["created_at"] = _timestamp(evidence.get("created_at") or evidence.get("time"))
    evidence["privacy"] = _privacy(evidence)
    return evidence, None


def _normalize_event(value: Any, index: int, prefix: str = "EV") -> tuple[dict[str, Any] | None, Any | None]:
    if isinstance(value, str):
        return {"id": f"{prefix}{index}", "type": "observation", "summary": value, "result": "unknown", "created_at": utc_now(), "privacy": {"mode": "redacted-default", "retention_days": DEFAULT_RETENTION_DAYS}}, None
    if not isinstance(value, dict):
        return None, value
    event = _copy_dict(value)
    event["id"] = str(event.get("id") or f"{prefix}{index}")
    event["type"] = str(event.get("type") or event.get("event_type") or event.get("kind") or "observation")
    event["summary"] = str(event.get("summary") or event.get("text") or event.get("message") or "")
    result = str(event.get("result") or "unknown")
    event["result"] = result if result in {"pass", "fail", "unknown"} else "unknown"
    event["created_at"] = _timestamp(event.get("created_at") or event.get("time") or event.get("timestamp"))
    event["refs"] = _string_list(event.get("refs") or event.get("ref"))
    event["evidence"] = _string_list(event.get("evidence") or event.get("evidence_ids"))
    event["claims"] = _string_list(event.get("claims") or event.get("claim"))
    event["privacy"] = _privacy(event)
    return event, None


def _normalize_dict_list(values: Any, prefix: str) -> tuple[list[dict[str, Any]], list[Any]]:
    normalized: list[dict[str, Any]] = []
    legacy: list[Any] = []
    for index, value in enumerate(_as_list(values), start=1):
        item, unstructured = _normalize_item(value, prefix, index)
        if item is not None:
            normalized.append(item)
        elif unstructured is not None:
            legacy.append(unstructured)
    return normalized, legacy


def _normalize_evidence_list(values: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    normalized: list[dict[str, Any]] = []
    legacy: list[Any] = []
    for index, value in enumerate(_as_list(values), start=1):
        item, unstructured = _normalize_evidence(value, index)
        if item is not None:
            normalized.append(item)
        elif unstructured is not None:
            legacy.append(unstructured)
    return normalized, legacy


def _normalize_event_list(values: Any, prefix: str = "EV") -> tuple[list[dict[str, Any]], list[Any]]:
    normalized: list[dict[str, Any]] = []
    legacy: list[Any] = []
    for index, value in enumerate(_as_list(values), start=1):
        item, unstructured = _normalize_event(value, index, prefix=prefix)
        if item is not None:
            normalized.append(item)
        elif unstructured is not None:
            legacy.append(unstructured)
    return normalized, legacy


def _migration_record(source_schema: str | None, target_schema: str, source: str | None) -> dict[str, Any]:
    return {
        "from": source_schema or "legacy:missing-schema",
        "to": target_schema,
        "source": source,
        "applied_at": utc_now(),
    }


def _add_migration(payload: dict[str, Any], source_schema: str | None, target_schema: str, source: str | None) -> None:
    if source_schema == target_schema:
        return
    migrations = payload.setdefault("schema_migrations", [])
    if isinstance(migrations, list):
        migrations.append(_migration_record(source_schema, target_schema, source))


def _score_from(payload: dict[str, Any]) -> int:
    value = payload.get("score", payload.get("slop_index", payload.get("index", 0)))
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _band_for(score: int) -> str:
    if score >= 66:
        return "red"
    if score >= 36:
        return "yellow"
    return "green"


def _normalize_risk_report(payload: dict[str, Any], *, target_schema: str = RISK_SCHEMA, source: str | None = None) -> dict[str, Any]:
    ensure_supported_schema("conversation_risk" if target_schema == CONVERSATION_RISK_SCHEMA else "risk", payload)
    original_schema = payload.get("schema") if isinstance(payload.get("schema"), str) else None
    score = _score_from(payload)
    report = _copy_dict(payload)
    report["schema"] = target_schema
    report["generated_at"] = _timestamp(report.get("generated_at") or report.get("created_at"))
    report["score"] = score
    report["slop_index"] = int(report.get("slop_index", score) or score)
    report["band"] = str(report.get("band") or _band_for(score))
    report["required_action"] = str(report.get("required_action") or ("block_final" if score >= 66 else "calibrate" if score >= 36 else "continue"))
    report["components"] = report.get("components") if isinstance(report.get("components"), dict) else {}
    report["reasons"] = _string_list(report.get("reasons")) or ["Risk is within the configured operating band."]
    if target_schema == RISK_SCHEMA:
        report["threshold"] = int(report.get("threshold") or 66)
        report["blocked"] = bool(report.get("blocked", score >= int(report["threshold"])))
        report["final_attempt"] = bool(report.get("final_attempt", False))
        report["weights"] = report.get("weights") if isinstance(report.get("weights"), dict) else RISK_WEIGHTS
    _add_migration(report, original_schema, target_schema, source)
    return report


def normalize_state(payload: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    ensure_supported_schema("state", payload)
    original_schema = payload.get("schema") if isinstance(payload.get("schema"), str) else None
    state = _copy_dict(payload)
    legacy_unstructured = _copy_dict(state.get("legacy_unstructured"))

    criteria_values = state.get("criteria") if isinstance(state.get("criteria"), list) and state.get("criteria") else state.get("success_criteria")
    criteria_items, criteria_legacy = _normalize_dict_list(criteria_values or state.get("acceptance_criteria") or state.get("done_conditions"), "C")
    steps, steps_legacy = _normalize_dict_list(state.get("steps"), "S")
    evidence, evidence_legacy = _normalize_evidence_list(state.get("evidence") or state.get("proofs") or state.get("evidence_items"))
    events, events_legacy = _normalize_event_list(state.get("events") or state.get("log") or state.get("observations"))
    risks, risks_legacy = _normalize_dict_list(state.get("risks"), "R")
    decisions, decisions_legacy = _normalize_dict_list(state.get("decisions"), "D")
    checkpoints, checkpoints_legacy = _normalize_dict_list(state.get("checkpoints"), "K")

    for key, values in {
        "criteria": criteria_legacy,
        "steps": steps_legacy,
        "evidence": evidence_legacy,
        "events": events_legacy,
        "risks": risks_legacy,
        "decisions": decisions_legacy,
        "checkpoints": checkpoints_legacy,
    }.items():
        if values:
            legacy_unstructured.setdefault(key, []).extend(values)

    state["schema"] = STATE_SCHEMA
    state["version"] = 1
    state["created_at"] = _timestamp(state.get("created_at"))
    state["updated_at"] = _timestamp(state.get("updated_at"))
    state["objective"] = str(state.get("objective") or state.get("goal") or "")
    state["threshold"] = int(state.get("threshold") or 66)
    state["criteria"] = criteria_items
    state["success_criteria"] = []
    state["constraints"] = _string_list(state.get("constraints"))
    state["assumptions"] = _string_list(state.get("assumptions"))
    state["steps"] = steps
    state["evidence"] = evidence
    state["events"] = events
    state["risks"] = risks
    state["decisions"] = decisions
    state["checkpoints"] = checkpoints
    if isinstance(state.get("last_scan"), dict):
        state["last_scan"] = _normalize_risk_report(state["last_scan"], source=source)
    else:
        state["last_scan"] = None
    state["last_verify"] = state.get("last_verify") if isinstance(state.get("last_verify"), dict) else None
    if legacy_unstructured:
        state["legacy_unstructured"] = legacy_unstructured
    _add_migration(state, original_schema, STATE_SCHEMA, source)
    return state


def normalize_conversation(payload: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    ensure_supported_schema("conversation", payload)
    original_schema = payload.get("schema") if isinstance(payload.get("schema"), str) else None
    data = _copy_dict(payload)
    events, events_legacy = _normalize_event_list(data.get("events") or data.get("messages") or data.get("log"))
    data["schema"] = CONVERSATION_SCHEMA
    data["id"] = str(data.get("id") or "C1")
    data["name"] = str(data.get("name") or data.get("conversation") or data["id"])
    data["group"] = str(data.get("group") or "default")
    data["root"] = str(data.get("root") or ".")
    data["objective"] = str(data.get("objective") or data["name"])
    data["created_at"] = _timestamp(data.get("created_at"))
    data["updated_at"] = _timestamp(data.get("updated_at"))
    data["status"] = str(data.get("status") or "active")
    data["events"] = events
    if isinstance(data.get("last_scan"), dict):
        data["last_scan"] = _normalize_risk_report(data["last_scan"], target_schema=CONVERSATION_RISK_SCHEMA, source=source)
    else:
        data["last_scan"] = None
    data["monitor_id"] = data.get("monitor_id")
    if events_legacy:
        data.setdefault("legacy_unstructured", {})["events"] = events_legacy
    _add_migration(data, original_schema, CONVERSATION_SCHEMA, source)
    return data


def normalize_report(kind: str, payload: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    if kind in {"risk", "conversation_risk"}:
        return _normalize_risk_report(payload, target_schema=CONVERSATION_RISK_SCHEMA if kind == "conversation_risk" else RISK_SCHEMA, source=source)
    ensure_supported_schema(kind, payload)
    original_schema = payload.get("schema") if isinstance(payload.get("schema"), str) else None
    current_schema = str(SUPPORTED_PUBLIC_SCHEMAS[kind]["current"])
    report = _copy_dict(payload)
    report["schema"] = current_schema
    report["generated_at"] = _timestamp(report.get("generated_at") or report.get("created_at"))
    if kind == "validation":
        scenarios = report.get("scenarios") if isinstance(report.get("scenarios"), list) else []
        report["scenarios"] = [item for item in scenarios if isinstance(item, dict)]
        report["total"] = int(report.get("total") or len(report["scenarios"]))
        report["passes"] = int(report.get("passes") or report.get("pass_count") or 0)
    elif kind == "calibration":
        report["dataset"] = report.get("dataset") if isinstance(report.get("dataset"), dict) else {"schema": TRAJECTORY_DATASET_SCHEMA, "size": int(report.get("dataset_size") or 0)}
        report["gate"] = report.get("gate") if isinstance(report.get("gate"), dict) else {"passed": bool(report.get("passed", True)), "failures": []}
        report["component_support"] = report.get("component_support") if isinstance(report.get("component_support"), dict) else {}
        report["component_metrics"] = report.get("component_metrics") if isinstance(report.get("component_metrics"), dict) else {}
        report["trajectories"] = report.get("trajectories") if isinstance(report.get("trajectories"), list) else []
    elif kind == "calibration_drift":
        report["baseline"] = report.get("baseline") if isinstance(report.get("baseline"), dict) else {}
        report["current"] = report.get("current") if isinstance(report.get("current"), dict) else {}
        report["gate"] = report.get("gate") if isinstance(report.get("gate"), dict) else {"passed": bool(report.get("passed", True)), "status": "pass", "regression_count": 0}
        report["regressions"] = report.get("regressions") if isinstance(report.get("regressions"), list) else []
    elif kind == "benchmark":
        report["events"] = int(report.get("events") or report.get("event_count") or 0)
        report["scan_ms"] = float(report.get("scan_ms") or report.get("latency_ms") or 0.0)
        report["events_per_second"] = float(report.get("events_per_second") or 0.0)
        report["passed"] = bool(report.get("passed", True))
    elif kind == "real_world_benchmark":
        report["suite"] = str(report.get("suite") or "public-safe-real-world")
        report["case_count"] = int(report.get("case_count") or len(report.get("cases") or []))
        report["metrics"] = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
        report["gate"] = report.get("gate") if isinstance(report.get("gate"), dict) else {"passed": bool(report.get("passed", True)), "failure_count": 0, "failures": []}
        report["cases"] = report.get("cases") if isinstance(report.get("cases"), list) else []
    elif kind == "export_opentelemetry":
        report["output"] = str(report.get("output") or report.get("path") or "")
        report["spans"] = int(report.get("spans") or report.get("span_count") or 0)
    elif kind == "adapter_matrix":
        report["fixture_policy"] = str(report.get("fixture_policy") or "")
        report["support_tiers"] = report.get("support_tiers") if isinstance(report.get("support_tiers"), list) else []
        report["cases"] = report.get("cases") if isinstance(report.get("cases"), list) else []
        report["gate"] = report.get("gate") if isinstance(report.get("gate"), dict) else {"passed": bool(report.get("passed", True)), "failure_count": 0, "failures": []}
    _add_migration(report, original_schema, current_schema, source)
    return report


def infer_fixture_kind(path: Path, payload: dict[str, Any]) -> str:
    schema = payload.get("schema")
    if isinstance(schema, str):
        for kind, entry in SUPPORTED_PUBLIC_SCHEMAS.items():
            if schema_family(schema) == schema_family(str(entry["current"])):
                return kind
    name = path.stem.lower()
    candidates = (
        ("conversation_risk", "conversation_risk"),
        ("real_world_benchmark", "real_world_benchmark"),
        ("calibration_drift", "calibration_drift"),
        ("github_release_verification", "github_release_verification"),
        ("release_verification", "github_release_verification"),
        ("trace_doctor", "trace_doctor"),
        ("trace_diagnostic", "trace_doctor"),
        ("collector", "collector"),
        ("http_collector", "collector"),
        ("batch_ingest", "batch_ingest"),
        ("batched_ingest", "batch_ingest"),
        ("ingest_queue", "batch_ingest"),
        ("adapter_matrix", "adapter_matrix"),
        ("adapter_export", "export_opentelemetry"),
        ("opentelemetry", "export_opentelemetry"),
        ("conversation", "conversation"),
        ("state", "state"),
        ("validation", "validation"),
        ("calibration", "calibration"),
        ("benchmark", "benchmark"),
        ("risk", "risk"),
    )
    for needle, kind in candidates:
        if needle in name:
            return kind
    raise SchemaCompatibilityError(f"Cannot infer schema fixture kind for {path}")


def normalize_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaCompatibilityError(f"Fixture must contain a JSON object: {path}")
    kind = infer_fixture_kind(path, payload)
    if kind == "state":
        normalized = normalize_state(payload, source=str(path))
    elif kind == "conversation":
        normalized = normalize_conversation(payload, source=str(path))
    else:
        normalized = normalize_report(kind, payload, source=str(path))
    return {"path": str(path), "kind": kind, "input_schema": payload.get("schema") or "legacy:missing-schema", "output_schema": normalized.get("schema"), "normalized": normalized}


def supported_schema_summary() -> list[dict[str, Any]]:
    return [
        {
            "kind": kind,
            "current": entry["current"],
            "supported": entry["supported"],
            "promise": entry["promise"],
        }
        for kind, entry in sorted(SUPPORTED_PUBLIC_SCHEMAS.items())
    ]


def default_schema_fixture_dir(root: Path | None = None) -> Path:
    if root is not None:
        repo_fixture_dir = root / "tests" / "fixtures" / "schema"
        if repo_fixture_dir.exists() and any(repo_fixture_dir.glob("*.json")):
            return repo_fixture_dir
    return DEFAULT_SCHEMA_FIXTURE_DIR


def run_schema_compatibility_check(fixture_dir: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    if not fixture_dir.exists():
        failures.append({"kind": "fixture_dir_missing", "path": str(fixture_dir)})
    else:
        fixture_paths = sorted(fixture_dir.glob("*.json"))
        if not fixture_paths:
            failures.append({"kind": "fixture_dir_empty", "path": str(fixture_dir)})
        for path in fixture_paths:
            try:
                item = normalize_fixture(path)
                expected = str(SUPPORTED_PUBLIC_SCHEMAS[item["kind"]]["current"])
                if item["output_schema"] != expected:
                    failures.append({"kind": "schema_mismatch", "path": str(path), "expected": expected, "actual": item["output_schema"]})
                items.append({key: value for key, value in item.items() if key != "normalized"})
            except (OSError, json.JSONDecodeError, SchemaCompatibilityError, TypeError, ValueError) as exc:
                failures.append({"kind": "fixture_failed", "path": str(path), "error": str(exc)})
    return {
        "schema": SCHEMA_COMPATIBILITY_SCHEMA,
        "generated_at": utc_now(),
        "fixture_dir": str(fixture_dir),
        "supported_schemas": supported_schema_summary(),
        "fixtures": items,
        "gate": {
            "passed": not failures,
            "failure_count": len(failures),
            "failures": failures,
        },
    }


def schema_compatibility_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
