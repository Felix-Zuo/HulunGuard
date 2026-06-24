from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import iter_observations
from .compatibility import AGENT_COMPATIBILITY
from .schemas import INTEGRATION_KIT_SCHEMA
from .util import utc_now

GENERATED_FILES = (
    "README.md",
    "hulun_integration.json",
    "run_ingest.ps1",
    "run_ingest.sh",
)


class IntegrationKitError(ValueError):
    """Raised when an integration kit request cannot be created safely."""


def supported_agent_ids() -> list[str]:
    return [str(item["id"]) for item in AGENT_COMPATIBILITY]


def _agent_by_id(agent_id: str) -> dict[str, Any]:
    for item in AGENT_COMPATIBILITY:
        if item["id"] == agent_id:
            return dict(item)
    raise IntegrationKitError(f"Unsupported agent id: {agent_id}")


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _jsonl_text(items: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items)


def _otlp_attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        encoded: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        encoded = {"intValue": str(value)}
    elif isinstance(value, float):
        encoded = {"doubleValue": value}
    elif isinstance(value, list):
        encoded = {"arrayValue": {"values": [_otlp_attr("", item)["value"] for item in value]}}
    else:
        encoded = {"stringValue": "" if value is None else str(value)}
    return {"key": key, "value": encoded}


def _sample_name(ingest_format: str) -> str:
    if ingest_format == "generic":
        return "sample-events.jsonl"
    if ingest_format == "openai-agents":
        return "sample-openai-agents-trace.json"
    if ingest_format in {"opentelemetry", "langfuse"}:
        return "sample-otlp.json"
    if ingest_format in {"openinference", "phoenix"}:
        return "sample-openinference.json"
    if ingest_format == "swe-agent":
        return "sample-trajectory.json"
    return f"sample-{ingest_format}.json"


def _sample_payload(ingest_format: str, agent: dict[str, Any]) -> tuple[str, str]:
    name = agent["name"]
    source = agent["id"]
    if ingest_format == "generic":
        return (
            _sample_name(ingest_format),
            _jsonl_text(
                [
                    {
                        "type": "tool_result",
                        "summary": f"{name} verification command passed",
                        "result": "pass",
                        "phase": "verify",
                        "evidence": ["E-sample-verify"],
                        "refs": [f"{source}:sample:verify"],
                        "action_key": f"{source}:sample-verify",
                        "prompt_tokens": 120,
                        "completion_tokens": 24,
                        "cost": 0.01,
                        "latency_ms": 350,
                        "model": "sample-model",
                    },
                    {
                        "type": "final_attempt",
                        "summary": f"{name} sample final claim with evidence",
                        "result": "pass",
                        "phase": "final",
                        "claim": "sample workflow completed with verification evidence",
                        "evidence": ["E-sample-verify"],
                        "refs": [f"{source}:sample:final"],
                        "action_key": f"{source}:sample-final",
                    },
                ]
            ),
        )

    if ingest_format == "openai-agents":
        payload = {
            "data": [
                {
                    "object": "trace",
                    "id": "trace_openai_agents_sample",
                    "workflow_name": f"{name} sample workflow",
                    "group_id": "sample-group",
                    "metadata": {"source": "hulunguard-public-safe-sample"},
                },
                {
                    "object": "trace.span",
                    "id": "span_openai_agents_verify",
                    "trace_id": "trace_openai_agents_sample",
                    "parent_id": None,
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "ended_at": "2026-01-01T00:00:00.350000+00:00",
                    "span_data": {
                        "type": "function",
                        "name": "sample_verify",
                        "input": {"command": "pytest"},
                        "output": {"status": "passed"},
                    },
                    "error": None,
                    "metadata": {
                        "hulun.event.type": "tool_result",
                        "hulun.event.summary": f"{name} verification command passed",
                        "hulun.event.result": "pass",
                        "hulun.event.phase": "verify",
                        "hulun.evidence.ids": ["E-sample-verify"],
                        "hulun.refs": [f"{source}:sample:verify"],
                        "hulun.action_key": f"{source}:sample-verify",
                        "prompt_tokens": 120,
                        "completion_tokens": 24,
                        "hulun.cost": 0.01,
                        "hulun.latency_ms": 350,
                        "model": "sample-model",
                    },
                },
                {
                    "object": "trace.span",
                    "id": "span_openai_agents_final",
                    "trace_id": "trace_openai_agents_sample",
                    "parent_id": "span_openai_agents_verify",
                    "started_at": "2026-01-01T00:00:01+00:00",
                    "ended_at": "2026-01-01T00:00:01.100000+00:00",
                    "span_data": {
                        "type": "custom",
                        "name": "final",
                        "data": {
                            "sdk_span_type": "turn",
                            "status": "done",
                        },
                    },
                    "error": None,
                    "metadata": {
                        "hulun.event.type": "final_attempt",
                        "hulun.event.summary": f"{name} sample final claim with evidence",
                        "hulun.event.result": "pass",
                        "hulun.event.phase": "final",
                        "hulun.claims": ["sample workflow completed with verification evidence"],
                        "hulun.evidence.ids": ["E-sample-verify"],
                        "hulun.refs": [f"{source}:sample:final"],
                        "hulun.action_key": f"{source}:sample-final",
                    },
                },
            ]
        }
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format in {"opentelemetry", "langfuse"}:
        payload = {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "11111111111111111111111111111111",
                                    "spanId": "1111111111111111",
                                    "name": f"{name} sample verification",
                                    "attributes": [
                                        _otlp_attr("hulun.event.type", "tool_result"),
                                        _otlp_attr("hulun.event.summary", f"{name} verification command passed"),
                                        _otlp_attr("hulun.event.result", "pass"),
                                        _otlp_attr("hulun.event.phase", "verify"),
                                        _otlp_attr("hulun.evidence.ids", ["E-sample-verify"]),
                                        _otlp_attr("hulun.refs", [f"{source}:sample:verify"]),
                                        _otlp_attr("hulun.action_key", f"{source}:sample-verify"),
                                        _otlp_attr("gen_ai.operation.name", "tool"),
                                        _otlp_attr("gen_ai.tool.name", "sample_verify"),
                                        _otlp_attr("gen_ai.usage.input_tokens", 120),
                                        _otlp_attr("gen_ai.usage.output_tokens", 24),
                                        _otlp_attr("hulun.cost", 0.01),
                                        _otlp_attr("hulun.latency_ms", 350),
                                        _otlp_attr("gen_ai.request.model", "sample-model"),
                                    ],
                                    "status": {"code": "STATUS_CODE_OK"},
                                },
                                {
                                    "traceId": "11111111111111111111111111111111",
                                    "spanId": "2222222222222222",
                                    "name": f"{name} sample final",
                                    "attributes": [
                                        _otlp_attr("hulun.event.type", "final_attempt"),
                                        _otlp_attr("hulun.event.summary", f"{name} sample final claim with evidence"),
                                        _otlp_attr("hulun.event.result", "pass"),
                                        _otlp_attr("hulun.event.phase", "final"),
                                        _otlp_attr("hulun.claims", ["sample workflow completed with verification evidence"]),
                                        _otlp_attr("hulun.evidence.ids", ["E-sample-verify"]),
                                        _otlp_attr("hulun.refs", [f"{source}:sample:final"]),
                                        _otlp_attr("hulun.action_key", f"{source}:sample-final"),
                                        _otlp_attr("gen_ai.operation.name", "chat"),
                                    ],
                                    "status": {"code": "STATUS_CODE_OK"},
                                },
                            ]
                        }
                    ]
                }
            ]
        }
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format in {"openinference", "phoenix"}:
        payload = [
            {
                "trace_id": "sample-trace",
                "span_id": "sample-verify",
                "name": f"{name} sample verification",
                "attributes": {
                    "openinference.span.kind": "TOOL",
                    "hulun.event.type": "tool_result",
                    "hulun.event.summary": f"{name} verification command passed",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "verify",
                    "hulun.evidence.ids": ["E-sample-verify"],
                    "hulun.refs": [f"{source}:sample:verify"],
                    "hulun.action_key": f"{source}:sample-verify",
                    "llm.token_count.prompt": 120,
                    "llm.token_count.completion": 24,
                    "hulun.cost": 0.01,
                    "hulun.latency_ms": 350,
                    "llm.model_name": "sample-model",
                },
            },
            {
                "trace_id": "sample-trace",
                "span_id": "sample-final",
                "name": f"{name} sample final",
                "attributes": {
                    "openinference.span.kind": "LLM",
                    "hulun.event.type": "final_attempt",
                    "hulun.event.summary": f"{name} sample final claim with evidence",
                    "hulun.event.result": "pass",
                    "hulun.event.phase": "final",
                    "hulun.claims": ["sample workflow completed with verification evidence"],
                    "hulun.evidence.ids": ["E-sample-verify"],
                    "hulun.refs": [f"{source}:sample:final"],
                    "hulun.action_key": f"{source}:sample-final",
                },
            },
        ]
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format == "openhands":
        payload = {
            "events": [
                {
                    "type": "action",
                    "summary": "Run verification command",
                    "message": "python -m pytest",
                    "phase": "verify",
                    "action_key": f"{source}:sample-verify",
                    "refs": [f"{source}:sample:command"],
                },
                {
                    "type": "observation",
                    "summary": f"{name} verification command passed",
                    "message": "pytest passed",
                    "result": "pass",
                    "phase": "verify",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:verify"],
                    "action_key": f"{source}:sample-verify",
                },
                {
                    "type": "message",
                    "summary": f"{name} sample final claim with evidence",
                    "result": "pass",
                    "phase": "final",
                    "claim": "sample workflow completed with verification evidence",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:final"],
                    "action_key": f"{source}:sample-final",
                },
            ]
        }
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format == "swe-agent":
        payload = {
            "trajectory": [
                {
                    "action": "python -m pytest",
                    "observation": "pytest passed",
                    "summary": f"{name} verification command passed",
                    "result": "pass",
                    "phase": "verify",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:verify"],
                    "action_key": f"{source}:sample-verify",
                    "prompt_tokens": 120,
                    "completion_tokens": 24,
                    "cost": 0.01,
                    "latency_ms": 350,
                    "model": "sample-model",
                },
                {
                    "action": "final",
                    "observation": "sample workflow completed with verification evidence",
                    "summary": f"{name} sample final claim with evidence",
                    "result": "pass",
                    "phase": "final",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:final"],
                    "action_key": f"{source}:sample-final",
                },
            ]
        }
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format == "langgraph":
        payload = {
            "events": [
                {
                    "type": "tasks",
                    "event_type": "tool_result",
                    "summary": f"{name} verification command passed",
                    "result": "pass",
                    "phase": "verify",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:verify"],
                    "action_key": f"{source}:sample-verify",
                    "data": {"node": "sample_verify", "status": "ok"},
                },
                {
                    "type": "values",
                    "event_type": "final_attempt",
                    "summary": f"{name} sample final claim with evidence",
                    "result": "pass",
                    "phase": "final",
                    "claim": "sample workflow completed with verification evidence",
                    "evidence": ["E-sample-verify"],
                    "refs": [f"{source}:sample:final"],
                    "action_key": f"{source}:sample-final",
                    "data": {"node": "final"},
                },
            ]
        }
        return _sample_name(ingest_format), _json_text(payload)

    if ingest_format == "langsmith":
        payload = [
            {
                "id": "sample-run-verify",
                "trace_id": "sample-trace",
                "run_type": "tool",
                "name": "sample_verify",
                "summary": f"{name} verification command passed",
                "result": "pass",
                "phase": "verify",
                "evidence": ["E-sample-verify"],
                "refs": [f"{source}:sample:verify"],
                "action_key": f"{source}:sample-verify",
                "usage_metadata": {"input_tokens": 120, "output_tokens": 24},
                "latency_ms": 350,
                "invocation_params": {"model": "sample-model"},
            },
            {
                "id": "sample-run-final",
                "trace_id": "sample-trace",
                "run_type": "llm",
                "name": "sample_final",
                "summary": f"{name} sample final claim with evidence",
                "result": "pass",
                "phase": "final",
                "claim": "sample workflow completed with verification evidence",
                "evidence": ["E-sample-verify"],
                "refs": [f"{source}:sample:final"],
                "action_key": f"{source}:sample-final",
            },
        ]
        return _sample_name(ingest_format), _json_text(payload)

    raise IntegrationKitError(f"No integration kit sample for ingest format: {ingest_format}")


def _readme(agent: dict[str, Any], sample_file: str) -> str:
    command = f"python -m hulun_guard ingest --format {agent['ingest_format']} --file {sample_file} --scan --init-if-missing"
    return "\n".join(
        [
            f"# HulunGuard Integration Kit: {agent['name']}",
            "",
            "This kit contains a public-safe sample trace and a ready-to-run ingest command.",
            "",
            "## Run",
            "",
            "```powershell",
            command,
            "```",
            "",
            "## Files",
            "",
            f"- `{sample_file}`: sample trace for the `{agent['ingest_format']}` adapter.",
            "- `hulun_integration.json`: machine-readable integration manifest.",
            "- `run_ingest.ps1`: Windows runner.",
            "- `run_ingest.sh`: POSIX shell runner.",
            "",
            "## Boundary",
            "",
            f"- Support tier: `{agent['tier']}`.",
            f"- Integration category: `{agent['category']}`.",
            f"- Source: {agent['source_uri']}",
            "- Do not commit private prompts, completions, tool arguments, credentials, customer files, or production logs.",
            "",
        ]
    )


def _powershell_runner(agent: dict[str, Any], sample_file: str) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$here = Split-Path -Parent $MyInvocation.MyCommand.Path",
            f"python -m hulun_guard ingest --format {agent['ingest_format']} --file (Join-Path $here '{sample_file}') --scan --init-if-missing",
            "",
        ]
    )


def _shell_runner(agent: dict[str, Any], sample_file: str) -> str:
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "set -eu",
            'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
            f'python -m hulun_guard ingest --format {agent["ingest_format"]} --file "$HERE/{sample_file}" --scan --init-if-missing',
            "",
        ]
    )


def _check_collisions(output_dir: Path, sample_file: str, *, force: bool) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise IntegrationKitError(f"Integration kit output path is not a directory: {output_dir}")
    names = set(GENERATED_FILES)
    names.add(sample_file)
    collisions = [output_dir / name for name in sorted(names) if (output_dir / name).exists()]
    if collisions and not force:
        joined = ", ".join(str(path) for path in collisions)
        raise IntegrationKitError(f"Integration kit files already exist. Use --force to overwrite: {joined}")


def generate_integration_kit(agent_id: str, output_dir: str | Path, *, force: bool = False, verify: bool = False) -> dict[str, Any]:
    agent = _agent_by_id(agent_id)
    target = Path(output_dir)
    sample_file, sample_text = _sample_payload(agent["ingest_format"], agent)
    _check_collisions(target, sample_file, force=force)
    target.mkdir(parents=True, exist_ok=True)

    sample_path = target / sample_file
    files = {
        sample_file: sample_text,
        "README.md": _readme(agent, sample_file),
        "run_ingest.ps1": _powershell_runner(agent, sample_file),
        "run_ingest.sh": _shell_runner(agent, sample_file),
    }
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8", newline="\n")

    observations: list[dict[str, Any]] = []
    verification: dict[str, Any] = {"requested": verify, "passed": None, "observation_count": None, "event_types": []}
    if verify:
        observations = list(iter_observations(sample_path, agent["ingest_format"]))
        event_types = sorted({str(item.get("type", "unknown")) for item in observations})
        verification = {
            "requested": True,
            "passed": len(observations) > 0,
            "observation_count": len(observations),
            "event_types": event_types,
        }
        if not verification["passed"]:
            raise IntegrationKitError(f"Integration kit sample produced no observations: {sample_path}")

    command = f'python -m hulun_guard ingest --format {agent["ingest_format"]} --file "{sample_path}" --scan --init-if-missing'
    manifest = {
        "schema": INTEGRATION_KIT_SCHEMA,
        "generated_at": utc_now(),
        "agent": agent,
        "kit_dir": str(target),
        "sample_trace": str(sample_path),
        "ingest_command": command,
        "verification": verification,
        "files": sorted([*files.keys(), "hulun_integration.json"]),
    }
    (target / "hulun_integration.json").write_text(_json_text(manifest), encoding="utf-8", newline="\n")
    return manifest


def generate_integration_kits(agent_id: str, output_dir: str | Path, *, force: bool = False, verify: bool = False) -> dict[str, Any]:
    base = Path(output_dir)
    ids = supported_agent_ids() if agent_id == "all" else [agent_id]
    kits = []
    for item_id in ids:
        target = base / item_id if agent_id == "all" else base
        kits.append(generate_integration_kit(item_id, target, force=force, verify=verify))
    failed = [kit for kit in kits if kit["verification"]["requested"] and not kit["verification"]["passed"]]
    return {
        "schema": INTEGRATION_KIT_SCHEMA,
        "generated_at": utc_now(),
        "requested_agent": agent_id,
        "output_dir": str(base),
        "kit_count": len(kits),
        "verified_count": sum(1 for kit in kits if kit["verification"]["passed"] is True),
        "gate": {"passed": not failed, "failures": [kit["agent"]["id"] for kit in failed]},
        "kits": kits,
    }


def integration_kits_json(result: dict[str, Any]) -> str:
    return _json_text(result)
