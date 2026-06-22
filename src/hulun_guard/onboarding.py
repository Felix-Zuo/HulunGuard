from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .adapters import iter_observations
from .integration_kits import IntegrationKitError, generate_integration_kit, supported_agent_ids
from .privacy import DEFAULT_RETENTION_DAYS
from .risk import scan_state
from .schemas import ONBOARDING_SCHEMA
from .sdk import append_project_event
from .storage import initial_state, save_state
from .util import utc_now


class OnboardingError(ValueError):
    """Raised when an onboarding package cannot be generated safely."""


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _agent_ids(agent_id: str) -> list[str]:
    return supported_agent_ids() if agent_id == "all" else [agent_id]


def _validate_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise OnboardingError(f"Onboarding output path is not a directory: {output_dir}")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _sandbox_import(kit: dict[str, Any]) -> dict[str, Any]:
    agent = kit["agent"]
    observations = list(iter_observations(Path(kit["sample_trace"]), agent["ingest_format"]))
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        state = initial_state(
            f"Validate HulunGuard onboarding for {agent['name']}",
            ["Sample trace imports and scans without using private data"],
            [],
            [],
            66,
        )
        state["criteria"][0]["status"] = "done"
        state["criteria"][0]["evidence"] = ["E-sample-verify"]
        state.setdefault("evidence", []).append(
            {
                "id": "E-sample-verify",
                "kind": "trace",
                "summary": f"{agent['name']} public-safe onboarding sample imported in sandbox",
                "created_at": utc_now(),
                "privacy": {"mode": "redacted-default", "retention_days": DEFAULT_RETENTION_DAYS},
            }
        )
        for item in observations:
            append_project_event(
                state,
                str(item.get("type") or "observation"),
                str(item.get("summary") or "Imported onboarding observation"),
                result=str(item.get("result") or "unknown"),
                refs=_string_list(item.get("refs")),
                resolved=item.get("resolved"),
                evidence=_string_list(item.get("evidence")),
                extra={
                    "phase": item.get("phase"),
                    "claims": _string_list(item.get("claims")),
                    "source_platform": item.get("source_platform") or agent["id"],
                    "action_key": item.get("action_key"),
                    "prompt_tokens": item.get("prompt_tokens"),
                    "completion_tokens": item.get("completion_tokens"),
                    "cost": item.get("cost"),
                    "latency_ms": item.get("latency_ms"),
                    "model": item.get("model"),
                },
            )
        risk = scan_state(state)
        state["last_scan"] = risk
        save_state(sandbox, state)
        written_state = sandbox / ".hulun" / "state.json"
        return {
            "passed": written_state.exists() and len(observations) > 0,
            "imported": len(observations),
            "risk": {
                "slop_index": risk["slop_index"],
                "band": risk["band"],
                "required_action": risk["required_action"],
            },
        }


def _next_steps(agent: dict[str, Any]) -> dict[str, str]:
    ingest_format = agent["ingest_format"]
    placeholder = f"<your-{ingest_format}-trace>"
    if ingest_format == "generic":
        placeholder = "<your-events.jsonl>"
    elif ingest_format in {"opentelemetry", "langfuse"}:
        placeholder = "<your-otlp-trace.json>"
    elif ingest_format in {"openinference", "phoenix"}:
        placeholder = "<your-openinference-trace.json>"
    return {
        "real_trace_command": f"python -m hulun_guard ingest --format {ingest_format} --file {placeholder} --scan --init-if-missing",
        "mcp_command": "hulun-mcp --root .",
        "sdk_entrypoint": "from hulun_guard import HulunGuardClient",
    }


def run_onboarding(agent_id: str, output_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    base = Path(output_dir)
    _validate_output_dir(base)
    agents = _agent_ids(agent_id)
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for item_id in agents:
        target = base / item_id
        try:
            kit = generate_integration_kit(item_id, target, force=force, verify=True)
            sandbox_import = _sandbox_import(kit)
            if not sandbox_import["passed"]:
                failures.append({"agent": item_id, "reason": "sandbox_import_failed"})
            items.append(
                {
                    "agent": kit["agent"],
                    "kit_dir": kit["kit_dir"],
                    "sample_trace": kit["sample_trace"],
                    "ingest_command": kit["ingest_command"],
                    "verification": kit["verification"],
                    "sandbox_import": sandbox_import,
                    "next_steps": _next_steps(kit["agent"]),
                }
            )
        except IntegrationKitError as exc:
            raise OnboardingError(str(exc)) from None
    verified_count = sum(1 for item in items if item["verification"]["passed"] is True)
    sandbox_imported_count = sum(int(item["sandbox_import"]["imported"]) for item in items)
    return {
        "schema": ONBOARDING_SCHEMA,
        "generated_at": utc_now(),
        "requested_agent": agent_id,
        "output_dir": str(base),
        "agent_count": len(items),
        "verified_count": verified_count,
        "sandbox_imported_count": sandbox_imported_count,
        "gate": {
            "passed": not failures and verified_count == len(items) and sandbox_imported_count >= len(items),
            "failures": failures,
        },
        "agents": items,
    }


def onboarding_json(result: dict[str, Any]) -> str:
    return _json_text(result)
