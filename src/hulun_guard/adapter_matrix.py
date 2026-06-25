from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .adapters import export_opentelemetry, iter_observations
from .privacy import DEFAULT_RETENTION_DAYS
from .schemas import ADAPTER_MATRIX_SCHEMA
from .sdk import append_project_event
from .service_exports import (
    JsonPostResponse,
    LangfuseServiceConfig,
    LangSmithServiceConfig,
    export_langfuse_observations,
    export_langsmith_runs,
)
from .storage import initial_state
from .util import utc_now

KEY_MARKER = "sk-" + "test" + "secret" + "012345678901234567890"
EMAIL_MARKER = "matrix@example.com"
AUTH_MARKER = "password=" + "hunter" + "2"
TRACE_REF_WITH_QUERY = "https://trace.example/run?id=abc&" + "token=" + "secret#debug"
REDACTED_REF = "https://trace.example/run"
EVIDENCE_ID = "E-matrix"
ACTION_KEY = "adapter-matrix-check"
MODEL = "gpt-matrix"
FORBIDDEN_VALUES = [KEY_MARKER, EMAIL_MARKER, "hunter2", "token=secret"]


def _otlp_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_otlp_value(item) for item in value]}}
    if isinstance(value, dict):
        return {"kvlistValue": {"values": [{"key": str(key), "value": _otlp_value(val)} for key, val in value.items()]}}
    return {"stringValue": "" if value is None else str(value)}


def _otlp_attr(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": _otlp_value(value)}


def adapter_support_tiers() -> list[dict[str, Any]]:
    return [
        {
            "tier": "integration-tested",
            "surfaces": ["opentelemetry", "openinference", "openhands", "swe-agent", "openai-agents"],
            "guarantee": "Public-safe fixture streams are imported through adapters, checked for contract fields, and covered by the adapter-matrix gate.",
        },
        {
            "tier": "hosted-fixture-tested",
            "surfaces": ["langgraph", "langsmith-file-export", "langfuse", "phoenix", "phoenix-cli-export"],
            "guarantee": "Hosted platform fixture shapes are checked with synthetic public-safe exports and no service-specific private trace data.",
        },
        {
            "tier": "native-export-tested",
            "surfaces": ["langsmith-service-export", "langfuse-service-export"],
            "guarantee": "Mocked service HTTP export checks explicit auth, selected fields, pagination, redaction, and importability without real credentials.",
        },
        {
            "tier": "roundtrip-tested",
            "surfaces": ["opentelemetry", "openinference", "langfuse", "phoenix", "phoenix-cli-export"],
            "guarantee": "Hulun-compatible attributes survive import, HulunGuard persistence, OTLP export, and OTLP re-import.",
        },
        {
            "tier": "conformance",
            "surfaces": ["cli", "sdk", "mcp", "stdin-payload", "in-memory-payload", "generic"],
            "guarantee": "The shared adapter contract test verifies field preservation, redaction, and malformed payload rejection.",
        },
        {
            "tier": "best-effort",
            "surfaces": ["custom-json", "provider-specific exports without supported fields"],
            "guarantee": "Use generic JSON, OpenTelemetry, or OpenInference fields; unsupported provider-specific payloads are summarized or ignored.",
        },
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _has_no_private_content(value: Any) -> bool:
    serialized = _serialized(value)
    return all(forbidden not in serialized for forbidden in FORBIDDEN_VALUES)


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _build_state(objective: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    state = initial_state(objective, ["adapter integration preserves runtime semantics"], [], [], 66)
    for observation in observations:
        append_project_event(
            state,
            observation.get("type") or "observation",
            observation.get("summary") or "Imported observation.",
            result=observation.get("result") or "unknown",
            refs=observation.get("refs") or [],
            resolved=observation.get("resolved"),
            evidence=observation.get("evidence") or [],
            extra={
                "phase": observation.get("phase"),
                "claims": observation.get("claims") or [],
                "source_platform": observation.get("source_platform"),
                "action_key": observation.get("action_key"),
                "prompt_tokens": observation.get("prompt_tokens"),
                "completion_tokens": observation.get("completion_tokens"),
                "cost": observation.get("cost"),
                "latency_ms": observation.get("latency_ms"),
                "model": observation.get("model"),
            },
            include_sensitive=False,
            retention_days=DEFAULT_RETENTION_DAYS,
        )
    return state


def _event_checks(events: list[dict[str, Any]], *, expected_count: int, source_platform: str, require_final: bool = False) -> list[dict[str, Any]]:
    results = {event.get("result") for event in events}
    phases = {event.get("phase") for event in events}
    event_types = {event.get("type") for event in events}
    first = events[0] if events else {}
    checks = [
        _check("event_count", len(events) == expected_count, f"{len(events)} / {expected_count} events"),
        _check("source_platform", all(event.get("source_platform") == source_platform for event in events), source_platform),
        _check("action_key", any(event.get("action_key") == ACTION_KEY for event in events), ACTION_KEY),
        _check("tokens", any(event.get("prompt_tokens") == 123 and event.get("completion_tokens") == 45 for event in events)),
        _check("cost_latency", any(event.get("cost") == 0.67 and event.get("latency_ms") == 890 for event in events)),
        _check("model", any(event.get("model") == MODEL for event in events), MODEL),
        _check("evidence", any(EVIDENCE_ID in event.get("evidence", []) for event in events), EVIDENCE_ID),
        _check("redacted_ref", any(REDACTED_REF in event.get("refs", []) for event in events), REDACTED_REF),
        _check("privacy_redaction", _has_no_private_content(events), "no private values in normalized events"),
        _check("success_retry_recovery", {"pass", "fail"}.issubset(results) and {"recover", "verify"}.issubset(phases)),
        _check("summary_path", "summary" in event_types or "summarize" in phases),
    ]
    if require_final:
        checks.append(_check("finalization_path", "final" in phases or "final_attempt" in event_types))
    if first:
        checks.append(_check("privacy_metadata", first.get("privacy", {}).get("mode") == "redacted-default"))
    return checks


def _roundtrip_checks(
    events: list[dict[str, Any]],
    roundtrip: list[dict[str, Any]],
    exported: dict[str, Any],
    *,
    source_platform: str,
) -> list[dict[str, Any]]:
    exported_spans = exported.get("resourceSpans", [{}])[0].get("scopeSpans", [{}])[0].get("spans", [])
    roundtrip_refs = [ref for event in roundtrip for ref in event.get("refs", [])]
    return [
        *_event_checks(events, expected_count=2, source_platform=source_platform),
        _check("exported_span_count", len(exported_spans) == len(events), f"{len(exported_spans)} / {len(events)} spans"),
        _check("roundtrip_event_count", len(roundtrip) == len(events), f"{len(roundtrip)} / {len(events)} events"),
        _check("roundtrip_action_key", any(event.get("action_key") == ACTION_KEY for event in roundtrip), ACTION_KEY),
        _check("roundtrip_tokens", any(event.get("prompt_tokens") == 123 and event.get("completion_tokens") == 45 for event in roundtrip)),
        _check("roundtrip_cost_latency", any(event.get("cost") == 0.67 and event.get("latency_ms") == 890 for event in roundtrip)),
        _check("roundtrip_evidence", any(EVIDENCE_ID in event.get("evidence", []) for event in roundtrip), EVIDENCE_ID),
        _check("roundtrip_ref_redaction", REDACTED_REF in roundtrip_refs, REDACTED_REF),
        _check("roundtrip_privacy_redaction", _has_no_private_content({"events": events, "roundtrip": roundtrip, "exported": exported})),
    ]


def _case(name: str, surface: str, tier: str, checks: list[dict[str, Any]], *, input_events: int, output_events: int) -> dict[str, Any]:
    failures = [check for check in checks if not check["passed"]]
    return {
        "name": name,
        "surface": surface,
        "tier": tier,
        "input_events": input_events,
        "output_events": output_events,
        "passed": not failures,
        "failure_count": len(failures),
        "checks": checks,
    }


def _opentelemetry_fixture() -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_otlp_attr("service.name", "matrix-agent")]},
                "scopeSpans": [
                    {
                        "scope": {"name": "matrix.otel"},
                        "spans": [
                            {
                                "traceId": "trace-otel-a",
                                "spanId": "span-otel-a",
                                "name": "tool retry failed",
                                "attributes": [
                                    _otlp_attr("hulun.event.type", "tool_result"),
                                    _otlp_attr("hulun.event.summary", f"pytest retry failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}"),
                                    _otlp_attr("hulun.event.result", "fail"),
                                    _otlp_attr("hulun.event.phase", "verify"),
                                    _otlp_attr("hulun.evidence.ids", [EVIDENCE_ID]),
                                    _otlp_attr("hulun.refs", [TRACE_REF_WITH_QUERY]),
                                    _otlp_attr("hulun.action_key", ACTION_KEY),
                                    _otlp_attr("gen_ai.usage.input_tokens", 123),
                                    _otlp_attr("gen_ai.usage.output_tokens", 45),
                                    _otlp_attr("hulun.cost", 0.67),
                                    _otlp_attr("hulun.latency_ms", 890),
                                    _otlp_attr("gen_ai.request.model", MODEL),
                                    _otlp_attr("gen_ai.tool.call.arguments", f"{KEY_MARKER} {EMAIL_MARKER} {AUTH_MARKER}"),
                                ],
                                "status": {"code": "STATUS_CODE_ERROR"},
                            },
                            {
                                "traceId": "trace-otel-b",
                                "spanId": "span-otel-b",
                                "name": "recovery summary",
                                "attributes": [
                                    _otlp_attr("hulun.event.type", "summary"),
                                    _otlp_attr("hulun.event.summary", "Recovery completed after retry evidence was attached."),
                                    _otlp_attr("hulun.event.result", "pass"),
                                    _otlp_attr("hulun.event.phase", "recover"),
                                    _otlp_attr("hulun.evidence.ids", [EVIDENCE_ID]),
                                    _otlp_attr("hulun.refs", [TRACE_REF_WITH_QUERY]),
                                ],
                                "status": {"code": "STATUS_CODE_OK"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def _openinference_fixture() -> list[dict[str, Any]]:
    return [
        {
            "trace_id": "trace-oi-a",
            "span_id": "span-oi-a",
            "name": "tool retry failed",
            "attributes": {
                "openinference.span.kind": "TOOL",
                "hulun.event.type": "tool_result",
                "hulun.event.summary": f"OpenInference tool retry failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "hulun.event.result": "fail",
                "hulun.event.phase": "verify",
                "hulun.evidence.ids": [EVIDENCE_ID],
                "hulun.refs": [TRACE_REF_WITH_QUERY],
                "hulun.action_key": ACTION_KEY,
                "llm.token_count.prompt": 123,
                "llm.token_count.completion": 45,
                "hulun.cost": 0.67,
                "hulun.latency_ms": 890,
                "llm.model_name": MODEL,
                "tool.parameters": f"{KEY_MARKER} {EMAIL_MARKER} {AUTH_MARKER}",
            },
            "status": {"code": "STATUS_CODE_ERROR"},
        },
        {
            "trace_id": "trace-oi-b",
            "span_id": "span-oi-b",
            "name": "recovery summary",
            "attributes": {
                "openinference.span.kind": "CHAIN",
                "hulun.event.type": "summary",
                "hulun.event.summary": "OpenInference recovery summary after retry.",
                "hulun.event.result": "pass",
                "hulun.event.phase": "recover",
                "hulun.evidence.ids": [EVIDENCE_ID],
                "hulun.refs": [TRACE_REF_WITH_QUERY],
            },
            "status": {"code": "STATUS_CODE_OK"},
        },
    ]


def _phoenix_cli_fixture() -> dict[str, Any]:
    return {
        "traceId": "trace-phoenix-cli-matrix",
        "spans": [
            {
                "name": "tool retry failed",
                "context": {"trace_id": "trace-phoenix-cli-matrix", "span_id": "span-phoenix-cli-a"},
                "span_kind": "TOOL",
                "parent_id": None,
                "start_time": "2026-06-25T00:00:00.000Z",
                "end_time": "2026-06-25T00:00:00.890Z",
                "status_code": "ERROR",
                "attributes": {
                    "hulun.event.type": "tool_result",
                    "hulun.event.summary": "Phoenix CLI tool retry failed after contract mismatch.",
                    "hulun.event.result": "fail",
                    "hulun.event.phase": "verify",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                    "hulun.refs": [TRACE_REF_WITH_QUERY],
                    "hulun.action_key": ACTION_KEY,
                    "llm.token_count.prompt": 123,
                    "llm.token_count.completion": 45,
                    "hulun.cost": 0.67,
                    "llm.model_name": MODEL,
                },
            },
            {
                "name": "recovery summary",
                "context": {"trace_id": "trace-phoenix-cli-matrix", "span_id": "span-phoenix-cli-b"},
                "span_kind": "CHAIN",
                "parent_id": "span-phoenix-cli-a",
                "start_time": "2026-06-25T00:00:01.000Z",
                "end_time": "2026-06-25T00:00:01.120Z",
                "status_code": "OK",
                "attributes": {
                    "hulun.event.type": "summary",
                    "hulun.event.summary": "Phoenix CLI recovery summary after retry.",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "recover",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                    "hulun.refs": [TRACE_REF_WITH_QUERY],
                },
            },
        ],
    }


def _openhands_fixture() -> dict[str, Any]:
    return {
        "events": [
            {
                "type": "action",
                "message": "inspect repository and run adapter matrix plan",
                "result": "pass",
                "phase": "explore",
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
            },
            {
                "type": "observation",
                "summary": f"pytest failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "message": f"pytest failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "result": "fail",
                "phase": "verify",
                "action_key": ACTION_KEY,
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "cost": 0.67,
                "latency_ms": 890,
                "model": MODEL,
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
            },
            {
                "type": "action",
                "message": "retry failed adapter case with narrower fixture",
                "result": "unknown",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
            },
            {
                "type": "observation",
                "message": "retry passed after recovery patch",
                "result": "pass",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
            },
            {
                "type": "condensation",
                "message": "summarize integration state and remaining release gate",
                "result": "pass",
                "phase": "summarize",
                "evidence": [EVIDENCE_ID],
            },
            {
                "type": "action",
                "message": "finalize adapter matrix release evidence",
                "result": "pass",
                "phase": "final",
                "evidence": [EVIDENCE_ID],
            },
        ]
    }


def _swe_agent_fixture() -> dict[str, Any]:
    return {
        "trajectory": [
            {
                "action": "python -m pytest tests/test_adapter_matrix.py",
                "observation": "test command started",
                "result": "pass",
                "phase": "implement",
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
            },
            {
                "action": "python -m pytest tests/test_adapter_matrix.py",
                "observation": f"failure after retry with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "summary": f"failure after retry with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "result": "fail",
                "phase": "verify",
                "action_key": ACTION_KEY,
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "cost": 0.67,
                "latency_ms": 890,
                "model": MODEL,
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
            },
            {
                "action": "apply_patch recovery update",
                "thought": "recover by preserving adapter action keys",
                "result": "unknown",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
            },
            {
                "action": "python -m pytest tests/test_adapter_matrix.py",
                "observation": "retry passed after recovery update",
                "result": "pass",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
            },
            {
                "thought": "summary: adapter matrix now covers integration-tested streams",
                "result": "pass",
                "phase": "summarize",
                "evidence": [EVIDENCE_ID],
            },
            {
                "action": "finalize release note",
                "observation": "finalization evidence recorded",
                "result": "pass",
                "phase": "final",
                "evidence": [EVIDENCE_ID],
            },
        ]
    }


def _langgraph_fixture() -> dict[str, Any]:
    return {
        "events": [
            {
                "type": "updates",
                "summary": "graph node prepared adapter fixture",
                "result": "pass",
                "phase": "explore",
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
                "data": {"planner": {"status": "ready"}},
            },
            {
                "type": "tasks",
                "event_type": "tool_result",
                "summary": f"LangGraph task failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                "result": "fail",
                "phase": "verify",
                "action_key": ACTION_KEY,
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "cost": 0.67,
                "latency_ms": 890,
                "model": MODEL,
                "evidence": [EVIDENCE_ID],
                "refs": [TRACE_REF_WITH_QUERY],
                "data": {"pytest": {"status": "failed"}},
            },
            {
                "type": "custom",
                "summary": "retry adapter fixture with narrowed state",
                "result": "unknown",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
                "data": {"status": "retrying"},
            },
            {
                "type": "tasks",
                "event_type": "tool_result",
                "summary": "retry passed after recovery state update",
                "result": "pass",
                "phase": "recover",
                "evidence": [EVIDENCE_ID],
            },
            {
                "type": "values",
                "summary": "summary state contains integration evidence",
                "result": "pass",
                "phase": "summarize",
                "evidence": [EVIDENCE_ID],
            },
            {
                "type": "updates",
                "event_type": "final_attempt",
                "summary": "finalize hosted adapter fixture",
                "result": "pass",
                "phase": "final",
                "evidence": [EVIDENCE_ID],
            },
        ]
    }


def _langsmith_fixture() -> list[dict[str, Any]]:
    return [
        {
            "id": "run-langsmith-a",
            "trace_id": "trace-langsmith",
            "run_type": "chain",
            "name": "inspect hosted adapter run",
            "result": "pass",
            "phase": "explore",
            "evidence": [EVIDENCE_ID],
            "refs": [TRACE_REF_WITH_QUERY],
        },
        {
            "id": "run-langsmith-b",
            "trace_id": "trace-langsmith",
            "run_type": "tool",
            "name": "pytest hosted adapter run",
            "summary": f"LangSmith run failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
            "error": f"LangSmith run failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
            "result": "fail",
            "phase": "verify",
            "action_key": ACTION_KEY,
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "cost": 0.67,
            "latency_ms": 890,
            "invocation_params": {"model": MODEL},
            "evidence": [EVIDENCE_ID],
            "refs": [TRACE_REF_WITH_QUERY],
        },
        {
            "id": "run-langsmith-c",
            "trace_id": "trace-langsmith",
            "run_type": "chain",
            "name": "retry hosted adapter run",
            "result": "unknown",
            "phase": "recover",
            "evidence": [EVIDENCE_ID],
        },
        {
            "id": "run-langsmith-d",
            "trace_id": "trace-langsmith",
            "run_type": "tool",
            "name": "retry passed hosted adapter run",
            "result": "pass",
            "phase": "recover",
            "evidence": [EVIDENCE_ID],
        },
        {
            "id": "run-langsmith-e",
            "trace_id": "trace-langsmith",
            "run_type": "chain",
            "name": "summarize hosted adapter run",
            "event_type": "summary",
            "result": "pass",
            "phase": "summarize",
            "evidence": [EVIDENCE_ID],
        },
        {
            "id": "run-langsmith-f",
            "trace_id": "trace-langsmith",
            "run_type": "chain",
            "name": "finalize hosted adapter run",
            "event_type": "final_attempt",
            "result": "pass",
            "phase": "final",
            "evidence": [EVIDENCE_ID],
        },
    ]


def _openai_agents_fixture() -> dict[str, Any]:
    return {
        "data": [
            {
                "object": "trace",
                "id": "trace_openai_agents_matrix",
                "workflow_name": "OpenAI Agents SDK adapter matrix workflow",
                "group_id": "matrix-group",
                "metadata": {"source": "hulunguard-public-safe-fixture"},
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_explore",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": None,
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:00:00.100000+00:00",
                "span_data": {"type": "agent", "name": "MatrixAgent", "handoffs": [], "tools": ["sample_verify"], "output_type": "text"},
                "error": None,
                "metadata": {
                    "hulun.event.summary": "OpenAI Agents SDK agent prepared adapter fixture",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "explore",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                    "hulun.refs": [TRACE_REF_WITH_QUERY],
                },
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_verify",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": "span_openai_agents_explore",
                "started_at": "2026-01-01T00:00:01+00:00",
                "ended_at": "2026-01-01T00:00:01.890000+00:00",
                "span_data": {"type": "guardrail", "name": "sample_guardrail", "triggered": True},
                "error": {"message": f"guardrail failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}", "data": {"attempt": 1}},
                "metadata": {
                    "hulun.event.summary": f"OpenAI Agents SDK guardrail failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                    "hulun.event.result": "fail",
                    "hulun.event.phase": "verify",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                    "hulun.refs": [TRACE_REF_WITH_QUERY],
                    "hulun.action_key": ACTION_KEY,
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "hulun.cost": 0.67,
                    "hulun.latency_ms": 890,
                    "model": MODEL,
                },
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_recover",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": "span_openai_agents_verify",
                "started_at": "2026-01-01T00:00:02+00:00",
                "ended_at": "2026-01-01T00:00:02.300000+00:00",
                "span_data": {"type": "handoff", "from_agent": "MatrixAgent", "to_agent": "RecoveryAgent"},
                "error": None,
                "metadata": {
                    "hulun.event.summary": "OpenAI Agents SDK handoff prepared recovery agent",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "orchestrate",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                },
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_recovered",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": "span_openai_agents_recover",
                "started_at": "2026-01-01T00:00:03+00:00",
                "ended_at": "2026-01-01T00:00:03.200000+00:00",
                "span_data": {"type": "function", "name": "sample_verify", "input": {"command": "pytest"}, "output": {"status": "passed"}},
                "error": None,
                "metadata": {
                    "hulun.event.type": "tool_result",
                    "hulun.event.summary": "OpenAI Agents SDK retry passed after recovery",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "recover",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                },
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_summary",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": "span_openai_agents_recovered",
                "started_at": "2026-01-01T00:00:04+00:00",
                "ended_at": "2026-01-01T00:00:04.100000+00:00",
                "span_data": {"type": "custom", "name": "summary", "data": {"sdk_span_type": "turn"}},
                "error": None,
                "metadata": {
                    "hulun.event.type": "summary",
                    "hulun.event.summary": "OpenAI Agents SDK summary preserved integration evidence",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "summarize",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                },
            },
            {
                "object": "trace.span",
                "id": "span_openai_agents_final",
                "trace_id": "trace_openai_agents_matrix",
                "parent_id": "span_openai_agents_summary",
                "started_at": "2026-01-01T00:00:05+00:00",
                "ended_at": "2026-01-01T00:00:05.100000+00:00",
                "span_data": {"type": "custom", "name": "final", "data": {"sdk_span_type": "turn"}},
                "error": None,
                "metadata": {
                    "hulun.event.type": "final_attempt",
                    "hulun.event.summary": "OpenAI Agents SDK finalization evidence recorded",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "final",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                },
            },
        ]
    }


def _roundtrip_case(name: str, source_format: str, fixture: Any, tmp: Path) -> dict[str, Any]:
    source_path = tmp / f"{name}.json"
    exported_path = tmp / f"{name}.exported.otlp.json"
    _write_json(source_path, fixture)
    observations = list(iter_observations(source_path, source_format))
    state = _build_state(f"{name} adapter roundtrip", observations)
    exported = export_opentelemetry(state, version="adapter-matrix")
    _write_json(exported_path, exported)
    roundtrip = list(iter_observations(exported_path, "opentelemetry"))
    checks = _roundtrip_checks(state["events"], roundtrip, exported, source_platform=source_format)
    return _case(
        name,
        source_format,
        "roundtrip-tested",
        checks,
        input_events=len(observations),
        output_events=len(roundtrip),
    )


def _stream_case(name: str, source_format: str, fixture: Any, tmp: Path) -> dict[str, Any]:
    source_path = tmp / f"{name}.json"
    _write_json(source_path, fixture)
    observations = list(iter_observations(source_path, source_format))
    state = _build_state(f"{name} adapter stream", observations)
    checks = _event_checks(state["events"], expected_count=6, source_platform=source_format, require_final=True)
    return _case(
        name,
        source_format,
        "hosted-fixture-tested" if source_format in {"langgraph", "langsmith"} else "integration-tested",
        checks,
        input_events=len(observations),
        output_events=len(state["events"]),
    )


def _langsmith_service_export_case(tmp: Path) -> dict[str, Any]:
    output = tmp / "langsmith-service-export.json"
    requests: list[dict[str, Any]] = []

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float) -> JsonPostResponse:
        requests.append({"url": url, "headers": dict(headers), "payload": dict(payload), "timeout_seconds": timeout_seconds})
        return JsonPostResponse(
            status=200,
            body={
                "items": [
                    {
                        "id": "run-langsmith-service-a",
                        "trace_id": "trace-langsmith-service",
                        "run_type": "tool",
                        "name": "service export failed tool",
                        "status": "error",
                        "error": f"tool failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "total_cost": 0.67,
                        "latency_ms": 890,
                        "inputs": {"prompt": KEY_MARKER},
                    },
                    {
                        "id": "run-langsmith-service-b",
                        "trace_id": "trace-langsmith-service",
                        "run_type": "chain",
                        "name": "service export recovery summary",
                        "status": "success",
                    },
                ],
                "next_cursor": None,
            },
        )

    report = export_langsmith_runs(
        LangSmithServiceConfig(
            endpoint="http://127.0.0.1:1",
            api_key="matrix-secret-key",
            project_id="matrix-project",
            output=output,
            page_size=2,
            max_runs=2,
            overwrite=True,
        ),
        transport=transport,
    )
    observations = list(iter_observations(output, "langsmith"))
    serialized_output = output.read_text(encoding="utf-8")
    checks = [
        _check("service_report_schema", report.get("schema") == "hulun.service_export.v1"),
        _check("explicit_auth_header", requests and requests[0]["headers"].get("X-Api-Key") == "matrix-secret-key"),
        _check("selected_fields", requests and "selects" in requests[0]["payload"] and "INPUTS" not in requests[0]["payload"]["selects"]),
        _check("page_size", requests and requests[0]["payload"].get("page_size") == 2),
        _check("run_count", report.get("exported", {}).get("run_count") == 2),
        _check("trace_doctor_next_command", "trace-doctor --format langsmith" in report.get("exported", {}).get("trace_doctor_command", "")),
        _check("adapter_importable", len(observations) == 2),
        _check("source_platform", all(item.get("source_platform") == "langsmith" for item in observations)),
        _check("privacy_redaction", _has_no_private_content({"report": report, "output": serialized_output, "observations": observations})),
        _check("api_key_not_persisted", "matrix-secret-key" not in _service_export_serialized_for_matrix(report, serialized_output)),
    ]
    return _case(
        "langsmith_service_export",
        "langsmith-service-export",
        "native-export-tested",
        checks,
        input_events=2,
        output_events=len(observations),
    )


def _langfuse_service_export_case(tmp: Path) -> dict[str, Any]:
    output = tmp / "langfuse-service-export.json"
    requests: list[dict[str, Any]] = []

    def transport(url: str, headers: dict[str, str], timeout_seconds: float) -> JsonPostResponse:
        requests.append({"url": url, "headers": dict(headers), "timeout_seconds": timeout_seconds})
        return JsonPostResponse(
            status=200,
            body={
                "data": [
                    {
                        "id": "obs-langfuse-service-a",
                        "traceId": "trace-langfuse-service",
                        "type": "GENERATION",
                        "name": "service export generation",
                        "level": "DEFAULT",
                        "startTime": "2026-06-25T00:00:00Z",
                        "endTime": "2026-06-25T00:00:01Z",
                        "inputUsage": 123,
                        "outputUsage": 45,
                        "totalCost": 0.67,
                        "providedModelName": "gpt-matrix",
                        "input": {"prompt": KEY_MARKER},
                        "output": f"contact {EMAIL_MARKER} {AUTH_MARKER}",
                    },
                    {
                        "id": "obs-langfuse-service-b",
                        "traceId": "trace-langfuse-service",
                        "type": "SPAN",
                        "name": "service export failed tool",
                        "level": "ERROR",
                        "statusMessage": f"tool failed with {KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                    },
                ],
                "meta": {"cursor": None},
            },
        )

    report = export_langfuse_observations(
        LangfuseServiceConfig(
            endpoint="http://127.0.0.1:1",
            public_key="pk-matrix-public",
            secret_key=KEY_MARKER,
            output=output,
            from_start_time="2026-06-25T00:00:00Z",
            to_start_time="2026-06-25T01:00:00Z",
            limit=2,
            max_observations=2,
            overwrite=True,
        ),
        transport=transport,
    )
    observations = list(iter_observations(output, "generic"))
    serialized_output = output.read_text(encoding="utf-8")
    query = parse_qs(urlsplit(requests[0]["url"]).query) if requests else {}
    expected_auth = "Basic " + base64.b64encode(f"pk-matrix-public:{KEY_MARKER}".encode("utf-8")).decode("ascii")
    checks = [
        _check("service_report_schema", report.get("schema") == "hulun.service_export.v1"),
        _check("explicit_basic_auth_header", requests and requests[0]["headers"].get("Authorization") == expected_auth),
        _check("selected_fields", query.get("fields") == ["core,basic,usage,trace_context"]),
        _check("bounded_time_window", query.get("fromStartTime") == ["2026-06-25T00:00:00Z"] and query.get("toStartTime") == ["2026-06-25T01:00:00Z"]),
        _check("limit", query.get("limit") == ["2"]),
        _check("observation_count", report.get("exported", {}).get("observation_count") == 2),
        _check("trace_doctor_next_command", "trace-doctor --format generic" in report.get("exported", {}).get("trace_doctor_command", "")),
        _check("adapter_importable", len(observations) == 2),
        _check("source_platform", all(item.get("source_platform") == "langfuse" for item in observations)),
        _check("privacy_redaction", _has_no_private_content({"report": report, "output": serialized_output, "observations": observations})),
        _check(
            "keys_not_persisted",
            "pk-matrix-public" not in _service_export_serialized_for_matrix(report, serialized_output)
            and KEY_MARKER not in _service_export_serialized_for_matrix(report, serialized_output),
        ),
    ]
    return _case(
        "langfuse_service_export",
        "langfuse-service-export",
        "native-export-tested",
        checks,
        input_events=2,
        output_events=len(observations),
    )


def _service_export_serialized_for_matrix(report: dict[str, Any], output_text: str) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True) + output_text


def _safe_case(label: str, runner: Callable[[Path], dict[str, Any]], tmp: Path) -> dict[str, Any]:
    try:
        return runner(tmp)
    except Exception as exc:  # pragma: no cover - defensive report shaping for release gates
        return _case(
            label,
            "unknown",
            "integration-tested",
            [_check("case_exception", False, f"{type(exc).__name__}: {exc}")],
            input_events=0,
            output_events=0,
        )


def run_adapter_matrix() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hulun-adapter-matrix-") as tmp_dir:
        tmp = Path(tmp_dir)
        cases = [
            _safe_case(
                "opentelemetry_roundtrip",
                lambda workdir: _roundtrip_case("opentelemetry_roundtrip", "opentelemetry", _opentelemetry_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "openinference_roundtrip",
                lambda workdir: _roundtrip_case("openinference_roundtrip", "openinference", _openinference_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "langfuse_otel_roundtrip",
                lambda workdir: _roundtrip_case("langfuse_otel_roundtrip", "langfuse", _opentelemetry_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "phoenix_openinference_roundtrip",
                lambda workdir: _roundtrip_case("phoenix_openinference_roundtrip", "phoenix", _openinference_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "phoenix_cli_export",
                lambda workdir: _roundtrip_case("phoenix_cli_export", "phoenix", _phoenix_cli_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "openhands_stream",
                lambda workdir: _stream_case("openhands_stream", "openhands", _openhands_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "swe_agent_stream",
                lambda workdir: _stream_case("swe_agent_stream", "swe-agent", _swe_agent_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "langgraph_stream",
                lambda workdir: _stream_case("langgraph_stream", "langgraph", _langgraph_fixture(), workdir),
                tmp,
            ),
            _safe_case(
                "langsmith_run_export",
                lambda workdir: _stream_case("langsmith_run_export", "langsmith", _langsmith_fixture(), workdir),
                tmp,
            ),
            _safe_case("langsmith_service_export", _langsmith_service_export_case, tmp),
            _safe_case("langfuse_service_export", _langfuse_service_export_case, tmp),
            _safe_case(
                "openai_agents_trace_export",
                lambda workdir: _stream_case("openai_agents_trace_export", "openai-agents", _openai_agents_fixture(), workdir),
                tmp,
            ),
        ]
    failures = [case for case in cases if not case["passed"]]
    total_checks = sum(len(case["checks"]) for case in cases)
    failed_checks = sum(case["failure_count"] for case in cases)
    return {
        "schema": ADAPTER_MATRIX_SCHEMA,
        "generated_at": utc_now(),
        "fixture_policy": "synthetic-public-safe-no-private-traces",
        "support_tiers": adapter_support_tiers(),
        "cases": cases,
        "gate": {
            "passed": not failures,
            "case_count": len(cases),
            "failure_count": len(failures),
            "check_count": total_checks,
            "failed_check_count": failed_checks,
            "failures": [{"name": case["name"], "failed_checks": [check for check in case["checks"] if not check["passed"]]} for case in failures],
        },
    }


def adapter_matrix_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
