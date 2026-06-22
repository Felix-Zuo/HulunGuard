from __future__ import annotations

import argparse
import functools
import http.server
import ipaddress
import json
import socketserver
import sys
import tempfile
import threading
import time
import webbrowser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .adapter_matrix import adapter_matrix_json, run_adapter_matrix
from .adapters import MAX_TRACE_BYTES, export_opentelemetry, iter_observations
from .benchmarks import build_real_world_benchmark_markdown, real_world_benchmark_json, run_real_world_benchmark
from .calibration import (
    build_calibration_drift_markdown,
    build_calibration_markdown,
    calibration_drift_json,
    calibration_json,
    compare_calibration_drift,
    run_trajectory_calibration,
)
from .compatibility import agent_compatibility_json, compatibility_report
from .constants import DASHBOARD_FILE, RISK_REPORT_FILE, VALID_EVENT_PHASES, VALID_STATUSES
from .conversation import (
    close_conversation,
    load_conversation,
    record_conversation_event,
    refresh_conversation_scan,
    start_conversation,
)
from .integration_kits import generate_integration_kits, integration_kits_json, supported_agent_ids
from .monitor import (
    board_path,
    close_monitor,
    create_monitor,
    group_summary,
    hulun_home,
    launch_widget,
    list_monitors,
    load_monitor,
    update_monitor,
)
from .onboarding import OnboardingError, onboarding_json, run_onboarding
from .privacy import DEFAULT_RETENTION_DAYS, sanitize_evidence
from .reports import build_board_html, build_dashboard_html, build_verify_markdown
from .retention import retention_cleanup_json, run_retention_cleanup
from .risk import scan_state
from .schemas import (
    BENCHMARK_SCHEMA,
    CALIBRATION_DRIFT_ERROR_SCHEMA,
    DOCTOR_SCHEMA,
    EXPORT_OPENTELEMETRY_SCHEMA,
    default_schema_fixture_dir,
    run_schema_compatibility_check,
    schema_compatibility_json,
)
from .sdk import append_project_event
from .security import run_threat_model_check, threat_model_check_json
from .storage import (
    criteria,
    find_item,
    hulun_dir,
    initial_state,
    load_state,
    project_root,
    resume_path,
    risk_path,
    save_state,
    verify_path,
    write_json,
)
from .util import hash_file, next_id, normalize_list, sort_ids, status_counts, utc_now
from .validation import build_validation_markdown, run_validation_suite, validation_json


def host_for_browser_url(actual_host: str) -> str:
    if not actual_host:
        return "127.0.0.1"
    try:
        if ipaddress.ip_address(actual_host).is_unspecified:
            return "127.0.0.1"
    except ValueError:
        return actual_host
    return actual_host


def package_version() -> str:
    try:
        from . import __version__

        return __version__
    except ImportError:
        try:
            return version("hulun-guard")
        except PackageNotFoundError:
            return "unknown"


def require_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status '{status}'. Expected one of: {', '.join(sorted(VALID_STATUSES))}")
    return status


def require_phase(phase: str | None) -> str | None:
    if phase is None:
        return None
    if phase not in VALID_EVENT_PHASES:
        raise SystemExit(f"Invalid phase '{phase}'. Expected one of: {', '.join(sorted(VALID_EVENT_PHASES))}")
    return phase


def append_event(
    state: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    refs: list[str] | None = None,
    resolved: bool | None = None,
    evidence: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    return append_project_event(
        state,
        event_type,
        summary,
        result=result,
        refs=refs,
        resolved=resolved,
        evidence=evidence,
        extra=extra,
        include_sensitive=include_sensitive,
        retention_days=retention_days,
    )


def cmd_init(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    path = hulun_dir(root) / "state.json"
    if path.exists() and not args.force:
        raise SystemExit(f"State already exists: {path}. Use --force to replace it.")
    state = initial_state(
        args.objective,
        normalize_list(args.criterion),
        normalize_list(args.constraint),
        normalize_list(args.assumption),
        args.threshold,
    )
    append_event(state, "init", f"Initialized HulunGuard objective: {args.objective}", result="pass")
    save_state(root, state)
    print(f"Initialized HulunGuard at {path}")
    return 0


def cmd_add_criterion(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    item = {"id": next_id(criteria(state), "C"), "text": args.text.strip(), "status": "pending", "evidence": []}
    criteria(state).append(item)
    append_event(state, "plan", f"Added criterion {item['id']}: {item['text']}")
    save_state(root, state)
    print(f"Added criterion {item['id']}")
    return 0


def cmd_set_criterion(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    item = find_item(criteria(state), args.id, "criterion")
    item["status"] = require_status(args.status)
    if args.evidence:
        item["evidence"] = sort_ids(set(item.get("evidence", [])) | set(args.evidence))
    append_event(state, "criterion", f"Criterion {args.id} set to {args.status}", evidence=item.get("evidence", []))
    save_state(root, state)
    print(f"Updated criterion {args.id}")
    return 0


def cmd_add_step(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    step = {
        "id": next_id(state.setdefault("steps", []), "S"),
        "text": args.text.strip(),
        "status": require_status(args.status),
        "evidence": normalize_list(args.evidence),
    }
    state["steps"].append(step)
    append_event(state, "plan", f"Added step {step['id']}: {step['text']}", evidence=step["evidence"])
    save_state(root, state)
    print(f"Added step {step['id']}")
    return 0


def cmd_set_step(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    step = find_item(state.setdefault("steps", []), args.id, "step")
    step["status"] = require_status(args.status)
    if args.evidence:
        step["evidence"] = sort_ids(set(step.get("evidence", [])) | set(args.evidence))
    result = "pass" if args.status == "done" else "unknown"
    append_event(state, "step", f"Step {args.id} set to {args.status}", result=result, evidence=step.get("evidence", []))
    save_state(root, state)
    print(f"Updated step {args.id}")
    return 0


def cmd_record_evidence(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    target_path: Path | None = None
    sha256 = None
    refs: list[str] = []
    if args.path:
        candidate = Path(args.path)
        target_path = candidate if candidate.is_absolute() else root / candidate
        sha256 = hash_file(target_path)
        refs.append(str(target_path))
    if args.url:
        refs.append(args.url)
    if args.command:
        refs.append(args.command)
    evidence = {
        "id": next_id(state.setdefault("evidence", []), "E"),
        "kind": args.kind,
        "summary": args.summary.strip(),
        "created_at": utc_now(),
        "command": args.command,
        "path": str(target_path) if target_path else None,
        "url": args.url,
        "sha256": sha256,
        "notes": args.notes,
    }
    evidence = sanitize_evidence(evidence, include_sensitive=args.include_sensitive, retention_days=args.retention_days)
    state["evidence"].append({k: v for k, v in evidence.items() if v not in (None, "")})
    append_event(
        state,
        "evidence",
        f"{evidence['id']}: {args.summary}",
        result=args.result,
        refs=refs,
        evidence=[evidence["id"]],
        include_sensitive=args.include_sensitive,
        retention_days=args.retention_days,
    )
    save_state(root, state)
    print(f"Recorded evidence {evidence['id']}")
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    refs = normalize_list(args.ref)
    evidence = normalize_list(args.evidence)
    event = append_event(
        state,
        args.type,
        args.summary,
        result=args.result,
        refs=refs,
        resolved=args.resolved,
        evidence=evidence,
        include_sensitive=args.include_sensitive,
        retention_days=args.retention_days,
    )
    save_state(root, state)
    print(f"Recorded event {event['id']}")
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    extra = {
        "phase": require_phase(args.phase),
        "claims": normalize_list(args.claim),
        "source_platform": args.source_platform,
        "action_key": args.action_key,
        "prompt_tokens": args.prompt_tokens,
        "completion_tokens": args.completion_tokens,
        "cost": args.cost,
        "latency_ms": args.latency_ms,
        "model": args.model,
    }
    event = append_event(
        state,
        args.type,
        args.summary,
        result=args.result,
        refs=normalize_list(args.ref),
        resolved=args.resolved,
        evidence=normalize_list(args.evidence),
        extra=extra,
        include_sensitive=args.include_sensitive,
        retention_days=args.retention_days,
    )
    save_state(root, state)

    if args.scan:
        _state, risk, report_path = run_scan(args, final_attempt=args.final_attempt)
        if args.json:
            print(json.dumps({"event": event, "risk": risk, "report": str(report_path)}, ensure_ascii=False, indent=2))
        else:
            print(f"Observed {event['id']}: {args.type}")
            print(f"HulunIndex: {risk['slop_index']} / 100 ({risk['band']})")
            print(f"Required action: {risk['required_action']}")
        return 2 if risk["blocked"] and args.fail_on_threshold else 0

    if args.json:
        print(json.dumps(event, ensure_ascii=False, indent=2))
    else:
        print(f"Observed {event['id']}: {args.type}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    try:
        state = load_state(root)
    except SystemExit:
        if not args.init_if_missing:
            raise
        criterion = args.init_criterion or "Imported agent trace observations remain evidence-backed."
        state = initial_state(
            objective=args.init_objective or f"Monitor {args.format} agent runtime reliability",
            criteria=[criterion],
            constraints=[],
            assumptions=[],
            threshold=args.init_threshold,
        )
    imported_count = 0
    first_id = None
    last_id = None
    sample_events: list[dict[str, Any]] = []
    for observation in iter_observations(args.file, args.format, include_sensitive=args.include_sensitive, max_trace_bytes=args.max_trace_bytes):
        event = append_event(
            state,
            observation.get("type") or "observation",
            observation.get("summary") or "Imported observation.",
            result=observation.get("result") or "unknown",
            refs=observation.get("refs") or [],
            resolved=observation.get("resolved"),
            evidence=observation.get("evidence") or [],
            extra={
                "phase": require_phase(observation.get("phase")),
                "claims": observation.get("claims") or [],
                "source_platform": args.source_platform or observation.get("source_platform"),
                "action_key": observation.get("action_key"),
                "prompt_tokens": observation.get("prompt_tokens"),
                "completion_tokens": observation.get("completion_tokens"),
                "cost": observation.get("cost"),
                "latency_ms": observation.get("latency_ms"),
                "model": observation.get("model"),
            },
            include_sensitive=args.include_sensitive,
            retention_days=args.retention_days,
        )
        imported_count += 1
        first_id = first_id or event["id"]
        last_id = event["id"]
        if args.include_events:
            sample_events.append(event)
    save_state(root, state)

    payload: dict[str, Any] = {
        "imported": imported_count,
        "first_event_id": first_id,
        "last_event_id": last_id,
    }
    if args.include_events:
        payload["events"] = sample_events
    if args.scan:
        _state, risk, report_path = run_scan(args, final_attempt=args.final_attempt)
        payload["risk"] = risk
        payload["report"] = str(report_path)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Imported {imported_count} observations from {args.file}")
        if args.scan and payload.get("risk"):
            risk = payload["risk"]
            print(f"HulunIndex: {risk['slop_index']} / 100 ({risk['band']})")
            print(f"Required action: {risk['required_action']}")
    if args.scan and payload.get("risk"):
        risk = payload["risk"]
        return 2 if risk["blocked"] and args.fail_on_threshold else 0
    return 0


def cmd_export_otel(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    payload = export_opentelemetry(state, version=package_version())
    output = Path(args.output)
    output = output if output.is_absolute() else root / output
    write_json(output, payload)
    result = {"schema": EXPORT_OPENTELEMETRY_SCHEMA, "output": str(output), "spans": len(state.get("events", []))}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Exported {result['spans']} OpenTelemetry spans: {output}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    result = run_validation_suite()
    output_dir = hulun_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "validation_report.json"
    md_path = output_dir / "validation_report.md"
    json_path.write_text(validation_json(result), encoding="utf-8")
    md_path.write_text(build_validation_markdown(result), encoding="utf-8")

    if args.json:
        print(validation_json(result), end="")
    else:
        print(f"HulunGuard validation: {result['passes']} / {result['total']} scenarios matched expected bands.")
        print(f"Report: {md_path}")
    return 0 if result["passes"] == result["total"] else 2


def cmd_calibrate(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    result = run_trajectory_calibration(min_precision=args.min_precision, min_recall=args.min_recall)
    output_dir = hulun_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "calibration_report.json"
    md_path = output_dir / "calibration_report.md"
    json_path.write_text(calibration_json(result), encoding="utf-8")
    md_path.write_text(build_calibration_markdown(result), encoding="utf-8")

    if args.json:
        print(calibration_json(result), end="")
    else:
        gate = "passed" if result["gate"]["passed"] else "failed"
        print(f"HulunGuard calibration {gate}: {result['dataset']['size']} labeled trajectories.")
        print(f"Report: {md_path}")
    return 0 if result["gate"]["passed"] else 2


def cmd_calibration_drift(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    if not baseline_path.exists():
        payload = {
            "schema": CALIBRATION_DRIFT_ERROR_SCHEMA,
            "error": "baseline_not_found",
            "baseline": str(baseline_path),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"HulunGuard calibration drift failed: baseline not found: {baseline_path}", file=sys.stderr)
        return 2
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        payload = {
            "schema": CALIBRATION_DRIFT_ERROR_SCHEMA,
            "error": "baseline_json_invalid",
            "baseline": str(baseline_path),
            "detail": str(exc),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"HulunGuard calibration drift failed: invalid baseline JSON: {exc}", file=sys.stderr)
        return 2
    calibration = run_trajectory_calibration(min_precision=args.min_precision, min_recall=args.min_recall)
    result = compare_calibration_drift(calibration, baseline, rationale=args.rationale)
    output_dir = hulun_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "calibration_drift_report.json"
    md_path = output_dir / "calibration_drift_report.md"
    json_path.write_text(calibration_drift_json(result), encoding="utf-8")
    md_path.write_text(build_calibration_drift_markdown(result), encoding="utf-8")

    if args.json:
        print(calibration_drift_json(result), end="")
    else:
        print(
            "HulunGuard calibration drift "
            f"{result['gate']['status']}: {result['gate']['regression_count']} regressions against {baseline_path}."
        )
        print(f"Report: {md_path}")
    return 0 if result["gate"]["passed"] else 2


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import HulunMCPServer, serve_stdio

    serve_stdio(HulunMCPServer(root=args.root, include_sensitive=args.include_sensitive, retention_days=args.retention_days))
    return 0


def cmd_quickstart(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    objective = args.objective or "Complete a long-running task with proof-backed final claims"
    criterion = args.criterion or "Final answer has evidence"
    conversation = args.conversation or "agent-conversation"
    group = args.group or root.name or "default"
    commands = [
        f'python .\\hulun.py --root "{root}" init --objective "{objective}" --criterion "{criterion}"',
        f'python .\\hulun.py --root "{root}" open --conversation "{conversation}" --group "{group}" --widget',
        f'python .\\hulun.py --root "{root}" observe --type tool_result --phase verify --summary "pytest passed" --result pass --scan',
        f'python .\\hulun.py --root "{root}" record-evidence --kind test --summary "pytest passed" --command "python -m pytest -q"',
        f'python .\\hulun.py --root "{root}" scan',
        f'python .\\hulun.py --root "{root}" verify',
        f'python .\\hulun.py --root "{root}" dashboard',
        f'python .\\hulun.py --root "{root}" doctor',
    ]
    payload = {
        "version": package_version(),
        "root": str(root),
        "objective": objective,
        "criterion": criterion,
        "commands": commands,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"HulunGuard {payload['version']} quickstart")
        for command in commands:
            print(command)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add_check("version", "ok", package_version())
    add_check("root", "ok" if root.exists() else "error", str(root))
    state_file = hulun_dir(root) / "state.json"
    add_check("state", "ok" if state_file.exists() else "warn", str(state_file) if state_file.exists() else "No state yet. Run hulun init.")

    payload: dict[str, Any] = {"schema": DOCTOR_SCHEMA, "root": str(root), "checks": checks}
    if state_file.exists():
        try:
            state = load_state(root)
            scan = scan_state(state)
            payload["status"] = {
                "criteria": status_counts(criteria(state)),
                "steps": status_counts(state.get("steps", [])),
                "evidence": len(state.get("evidence", [])),
                "events": len(state.get("events", [])),
                "checkpoints": len(state.get("checkpoints", [])),
                "slop_index": scan["slop_index"],
                "band": scan["band"],
                "required_action": scan["required_action"],
            }
            if scan["band"] == "red":
                add_check("slop_index", "error", f"{scan['slop_index']} red; recover before final.")
            elif scan["band"] == "yellow":
                add_check("slop_index", "warn", f"{scan['slop_index']} yellow; checkpoint or add evidence.")
            else:
                add_check("slop_index", "ok", f"{scan['slop_index']} green.")
            if not state.get("checkpoints"):
                add_check("checkpoint", "warn", "No checkpoint recorded.")
            if not state.get("evidence"):
                add_check("evidence", "warn", "No evidence recorded.")
        except Exception as exc:
            add_check("state_parse", "error", str(exc))

    if args.run_validation:
        validation = run_validation_suite()
        payload["validation"] = validation
        status = "ok" if validation["passes"] == validation["total"] else "error"
        add_check("validation", status, f"{validation['passes']} / {validation['total']} scenarios.")
        schema_compatibility = run_schema_compatibility_check(default_schema_fixture_dir(root))
        payload["schema_compatibility"] = schema_compatibility
        schema_status = "ok" if schema_compatibility["gate"]["passed"] else "error"
        add_check("schema_compatibility", schema_status, f"{len(schema_compatibility['fixtures'])} fixtures.")
        threat_model = run_threat_model_check(root)
        payload["threat_model"] = threat_model
        threat_model_status = "ok" if threat_model["gate"]["passed"] else "error"
        add_check("threat_model", threat_model_status, f"{len(threat_model['checks'])} checks.")
        compatibility = compatibility_report()
        payload["agent_compatibility"] = compatibility
        compatibility_status = "ok" if compatibility["direct_or_standard_count"] >= 13 else "error"
        add_check("agent_compatibility", compatibility_status, f"{compatibility['entry_count']} entries.")
        with tempfile.TemporaryDirectory() as tmp:
            integration_kits = generate_integration_kits("all", Path(tmp), force=True, verify=True)
        payload["integration_kits"] = integration_kits
        integration_status = "ok" if integration_kits["gate"]["passed"] else "error"
        add_check("integration_kits", integration_status, f"{integration_kits['kit_count']} kits.")
        with tempfile.TemporaryDirectory() as tmp:
            onboarding = run_onboarding("all", Path(tmp), force=True)
        payload["onboarding"] = onboarding
        onboarding_status = "ok" if onboarding["gate"]["passed"] else "error"
        add_check("onboarding", onboarding_status, f"{onboarding['agent_count']} agents.")
        adapter_matrix = run_adapter_matrix()
        payload["adapter_matrix"] = adapter_matrix
        adapter_matrix_status = "ok" if adapter_matrix["gate"]["passed"] else "error"
        add_check("adapter_matrix", adapter_matrix_status, f"{adapter_matrix['gate']['case_count']} cases.")
        calibration = run_trajectory_calibration()
        payload["calibration"] = {key: value for key, value in calibration.items() if key != "trajectories"}
        calibration_status = "ok" if calibration["gate"]["passed"] else "error"
        add_check("calibration", calibration_status, f"{calibration['dataset']['size']} labeled trajectories.")

    has_error = any(check["status"] == "error" for check in checks)
    has_warn = any(check["status"] == "warn" for check in checks)
    payload["result"] = "error" if has_error else "warn" if has_warn else "ok"

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"HulunGuard doctor: {payload['result']}")
        for check in checks:
            print(f"[{check['status']}] {check['name']}: {check['detail']}")
    return 2 if has_error and args.fail_on_error else 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    dry_run = not args.apply
    result = run_retention_cleanup(
        root,
        dry_run=dry_run,
        include_conversations=not args.skip_conversations,
        include_reports=not args.skip_reports,
        default_retention_days=args.default_retention_days,
        write_report=args.write_report or args.apply,
    )
    if args.json:
        print(retention_cleanup_json(result), end="")
    else:
        mode = "dry-run" if result["dry_run"] else "apply"
        summary = result["summary"]
        print(f"HulunGuard cleanup: {mode}")
        print(f"Expired project events: {summary['expired_project_events']}")
        print(f"Expired project evidence: {summary['expired_project_evidence']}")
        print(f"Expired conversation events: {summary['expired_conversation_events']}")
        print(f"Report files deleted: {summary['report_files_deleted']}")
        if result["safety_violations"]:
            print("Safety violations:")
            for violation in result["safety_violations"]:
                print(f"- {violation['reason']}: {violation['path']}")
        if args.write_report or args.apply:
            report_dir = hulun_dir(root)
            print(f"Report: {report_dir / 'retention_cleanup_report.md'}")
    return 0 if result["gate"]["passed"] else 2


def cmd_schema_check(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    fixture_dir = Path(args.fixture_dir) if args.fixture_dir else default_schema_fixture_dir(root)
    if args.fixture_dir and not fixture_dir.is_absolute():
        fixture_dir = root / fixture_dir
    result = run_schema_compatibility_check(fixture_dir)
    if args.json:
        print(schema_compatibility_json(result), end="")
    else:
        gate = result["gate"]
        print(f"HulunGuard schema compatibility: {'pass' if gate['passed'] else 'fail'}")
        print(f"Fixtures: {len(result['fixtures'])}")
        print(f"Failures: {gate['failure_count']}")
        for failure in gate["failures"]:
            detail = ", ".join(f"{key}={value}" for key, value in failure.items())
            print(f"- {detail}")
    return 0 if result["gate"]["passed"] else 2


def cmd_threat_model_check(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    result = run_threat_model_check(root)
    if args.json:
        print(threat_model_check_json(result), end="")
    else:
        gate = result["gate"]
        print(f"HulunGuard threat model: {'pass' if gate['passed'] else 'fail'}")
        print(f"Checks: {len(result['checks'])}")
        print(f"Failures: {gate['failure_count']}")
        for failure in gate["failures"]:
            print(f"- {failure['name']}: {failure['detail']}")
    return 0 if result["gate"]["passed"] else 2


def cmd_adapter_matrix(args: argparse.Namespace) -> int:
    result = run_adapter_matrix()
    if args.json:
        print(adapter_matrix_json(result), end="")
    else:
        gate = result["gate"]
        print(f"HulunGuard adapter matrix: {'pass' if gate['passed'] else 'fail'}")
        print(f"Cases: {gate['case_count']}")
        print(f"Checks: {gate['check_count']}")
        print(f"Failures: {gate['failed_check_count']}")
        for failure in gate["failures"]:
            failed_names = ", ".join(check["name"] for check in failure["failed_checks"])
            print(f"- {failure['name']}: {failed_names}")
    return 0 if result["gate"]["passed"] else 2


def build_benchmark_state(event_count: int) -> dict[str, Any]:
    state = initial_state(
        "Benchmark HulunGuard scan performance",
        ["Benchmark has generated observations"],
        [],
        [],
        66,
    )
    state["evidence"].append({"id": "E1", "kind": "test", "summary": "benchmark synthetic evidence", "created_at": utc_now()})
    criteria(state)[0]["status"] = "done"
    criteria(state)[0]["evidence"] = ["E1"]
    state["checkpoints"].append({"id": "K1", "summary": "benchmark checkpoint", "created_at": utc_now()})
    event_types = ["command", "tool_result", "summary", "llm_call"]
    phases = ["explore", "implement", "summarize", "verify"]
    events = state.setdefault("events", [])
    for idx in range(1, event_count + 1):
        event_type = event_types[idx % len(event_types)]
        result = "fail" if idx % 97 == 0 else "pass"
        event = {
            "id": f"EV{idx}",
            "type": event_type,
            "summary": f"benchmark event {idx}",
            "result": result,
            "phase": phases[idx % len(phases)],
            "created_at": utc_now(),
            "refs": [],
            "evidence": ["E1"] if idx % 41 == 0 else [],
        }
        if result == "fail":
            event["action_key"] = "benchmark-retry"
        if event_type == "llm_call":
            event["prompt_tokens"] = 800
            event["completion_tokens"] = 200
            event["latency_ms"] = 500
        events.append(event)
    state["counters"] = {"events:EV": event_count}
    return state


def cmd_benchmark(args: argparse.Namespace) -> int:
    if args.suite == "real-world":
        root = project_root(args.root)
        result = run_real_world_benchmark(
            version=package_version(),
            max_case_ms=args.max_case_ms,
            max_case_bytes=args.max_case_bytes,
            max_total_bytes=args.max_total_bytes,
            min_component_stability=args.min_component_stability,
            max_false_positive_rate=args.max_false_positive_rate,
            max_false_negative_rate=args.max_false_negative_rate,
        )
        output_dir = hulun_dir(root)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "real_world_benchmark_report.json"
        markdown_path = output_dir / "real_world_benchmark_report.md"
        json_path.write_text(real_world_benchmark_json(result), encoding="utf-8")
        markdown_path.write_text(build_real_world_benchmark_markdown(result), encoding="utf-8")
        if args.json:
            print(real_world_benchmark_json(result), end="")
        else:
            metrics = result["metrics"]
            print(f"HulunGuard real-world benchmark: {result['case_count']} public-safe cases")
            print(f"Gate: {'pass' if result['gate']['passed'] else 'fail'}")
            print(f"Max scan latency: {metrics['scan_latency']['max_ms']} ms")
            print(f"Component stability: {metrics['component_stability']['rate']}")
            print(f"Report: {json_path}")
        return 0 if result["gate"]["passed"] else 2

    root = project_root(args.root)
    state = build_benchmark_state(args.events)
    started = time.perf_counter()
    risk = scan_state(state)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    events_per_second = args.events / max(elapsed_ms / 1000.0, 0.000001)
    result = {
        "schema": BENCHMARK_SCHEMA,
        "generated_at": utc_now(),
        "version": package_version(),
        "events": args.events,
        "scan_ms": round(elapsed_ms, 3),
        "events_per_second": round(events_per_second, 1),
        "score": risk["score"],
        "band": risk["band"],
        "passed": args.max_ms is None or elapsed_ms <= args.max_ms,
        "max_ms": args.max_ms,
    }
    output_dir = hulun_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"HulunGuard benchmark: {args.events} events scanned in {elapsed_ms:.2f} ms ({events_per_second:.0f} events/s)")
        print(f"Report: {report_path}")
    return 0 if result["passed"] else 2


def cmd_compatibility(args: argparse.Namespace) -> int:
    result = compatibility_report()
    if args.json:
        print(agent_compatibility_json(result), end="")
    else:
        print(f"HulunGuard agent compatibility: {result['entry_count']} entries")
        print(f"Direct or standards path: {result['direct_or_standard_count']}")
        print(result["coverage_statement"])
        for item in result["agents"]:
            print(f"- {item['name']}: {item['tier']} via {item['ingest_format']}")
    return 0


def cmd_integration_kit(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    if args.output:
        output_dir = Path(args.output)
    else:
        base = hulun_dir(root) / "integration-kits"
        output_dir = base if args.agent == "all" else base / args.agent
    try:
        result = generate_integration_kits(args.agent, output_dir, force=args.force, verify=args.verify)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.json:
        print(integration_kits_json(result), end="")
    else:
        print(f"HulunGuard integration kits: {result['kit_count']} generated")
        print(f"Output: {result['output_dir']}")
        if args.verify:
            print(f"Verified: {result['verified_count']} / {result['kit_count']}")
        for kit in result["kits"]:
            verification = kit["verification"]
            suffix = f", {verification['observation_count']} sample observations" if verification["passed"] else ""
            print(f"- {kit['agent']['name']}: {kit['agent']['ingest_format']} -> {kit['kit_dir']}{suffix}")
    return 0 if result["gate"]["passed"] else 2


def cmd_onboard(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    if args.output:
        output_dir = Path(args.output)
        if not output_dir.is_absolute():
            output_dir = root / output_dir
    else:
        output_dir = hulun_dir(root) / "onboarding"
    try:
        result = run_onboarding(args.agent, output_dir, force=args.force)
    except OnboardingError as exc:
        raise SystemExit(str(exc)) from None

    if args.json:
        print(onboarding_json(result), end="")
    else:
        print(f"HulunGuard onboarding: {'pass' if result['gate']['passed'] else 'fail'}")
        print(f"Agents: {result['agent_count']}")
        print(f"Output: {result['output_dir']}")
        for item in result["agents"]:
            sandbox = item["sandbox_import"]
            print(
                f"- {item['agent']['name']}: verified {item['verification']['observation_count']} observations, "
                f"sandbox imported {sandbox['imported']}, {sandbox['risk']['band']}"
            )
            print(f"  Next: {item['next_steps']['real_trace_command']}")
    return 0 if result["gate"]["passed"] else 2


def cmd_conversation_start(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    data = start_conversation(
        name=args.name,
        group=args.group,
        root=str(root),
        objective=args.objective,
        monitor=args.monitor or args.widget,
        widget=args.widget,
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        risk = data.get("last_scan", {})
        print(f"Started conversation {data['id']}: {data['name']}")
        print(f"HulunIndex: {risk.get('slop_index', 0)} / 100 ({risk.get('band', 'green')})")
        if data.get("monitor_id"):
            print(f"Monitor: {data['monitor_id']}")
    return 0


def cmd_conversation_event(args: argparse.Namespace) -> int:
    _data, event, risk = record_conversation_event(
        args.id,
        args.type,
        args.summary,
        result=args.result,
        phase=require_phase(args.phase),
        claims=normalize_list(args.claim),
        evidence=normalize_list(args.evidence),
        refs=normalize_list(args.ref),
        resolved=args.resolved,
        action_key=args.action_key,
        prompt_tokens=args.prompt_tokens,
        completion_tokens=args.completion_tokens,
        cost=args.cost,
        latency_ms=args.latency_ms,
        model=args.model,
        include_sensitive=args.include_sensitive,
        retention_days=args.retention_days,
    )
    payload = {"event": event, "risk": risk}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Conversation {args.id} event {event['id']}: {args.type}")
        print(f"HulunIndex: {risk['slop_index']} / 100 ({risk['band']})")
        print(f"Required action: {risk['required_action']}")
    return 2 if risk["band"] == "red" and args.fail_on_red else 0


def cmd_conversation_scan(args: argparse.Namespace) -> int:
    data, risk = refresh_conversation_scan(args.id, checkpoint_stale_minutes=args.checkpoint_stale_minutes)
    if args.json:
        print(json.dumps({"conversation": data, "risk": risk}, ensure_ascii=False, indent=2))
    else:
        print(f"Conversation {args.id}: {risk['slop_index']} / 100 ({risk['band']})")
        for reason in risk.get("reasons", []):
            print(f"- {reason}")
    return 2 if risk["band"] == "red" and args.fail_on_red else 0


def cmd_conversation_status(args: argparse.Namespace) -> int:
    data = load_conversation(args.id)
    payload = {
        "id": data["id"],
        "name": data.get("name"),
        "group": data.get("group"),
        "status": data.get("status"),
        "events": len(data.get("events", [])),
        "monitor_id": data.get("monitor_id"),
        "last_scan": data.get("last_scan"),
        "latest_events": data.get("events", [])[-args.tail :],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        scan = payload.get("last_scan") or {}
        print(f"Conversation {payload['id']}: {payload['name']}")
        print(f"Events: {payload['events']}")
        print(f"HulunIndex: {scan.get('slop_index', 0)} / 100 ({scan.get('band', 'unknown')})")
    return 0


def cmd_conversation_close(args: argparse.Namespace) -> int:
    data = close_conversation(args.id)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"Closed conversation {args.id}")
    return 0


def cmd_add_risk(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    risk = {"id": next_id(state.setdefault("risks", []), "R"), "text": args.text.strip(), "created_at": utc_now()}
    state["risks"].append(risk)
    append_event(state, "risk", f"{risk['id']}: {risk['text']}", result="unknown")
    save_state(root, state)
    print(f"Added risk {risk['id']}")
    return 0


def cmd_add_decision(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    decision = {
        "id": next_id(state.setdefault("decisions", []), "D"),
        "text": args.text.strip(),
        "reason": args.reason,
        "created_at": utc_now(),
    }
    state["decisions"].append({k: v for k, v in decision.items() if v not in (None, "")})
    append_event(state, "decision", f"{decision['id']}: {decision['text']}", result="pass")
    save_state(root, state)
    print(f"Added decision {decision['id']}")
    return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    checkpoint = {
        "id": next_id(state.setdefault("checkpoints", []), "K"),
        "created_at": utc_now(),
        "summary": args.summary.strip(),
        "next_action": args.next_action,
    }
    state["checkpoints"].append({k: v for k, v in checkpoint.items() if v not in (None, "")})
    append_event(state, "checkpoint", f"{checkpoint['id']}: {checkpoint['summary']}", result="pass")
    save_state(root, state)
    print(f"Created checkpoint {checkpoint['id']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    payload = {
        "objective": state.get("objective", ""),
        "criteria": status_counts(criteria(state)),
        "steps": status_counts(state.get("steps", [])),
        "evidence": len(state.get("evidence", [])),
        "events": len(state.get("events", [])),
        "checkpoints": len(state.get("checkpoints", [])),
        "last_scan": state.get("last_scan"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Objective: {payload['objective']}")
        print(f"Criteria: {payload['criteria']}")
        print(f"Steps: {payload['steps']}")
        print(f"Evidence: {payload['evidence']}")
        print(f"Events: {payload['events']}")
        print(f"Checkpoints: {payload['checkpoints']}")
        if payload["last_scan"]:
            print(f"HulunGauge: {payload['last_scan']['score']} {payload['last_scan']['band']}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    state = load_state(root)
    save_state(root, state)
    print(resume_path(root).read_text(encoding="utf-8"))
    return 0


def run_scan(args: argparse.Namespace, *, final_attempt: bool = False) -> tuple[dict[str, Any], dict[str, Any], Path]:
    root = project_root(args.root)
    state = load_state(root)
    risk = scan_state(
        state,
        threshold=args.threshold,
        final_attempt=final_attempt,
        checkpoint_stale_minutes=args.checkpoint_stale_minutes,
    )
    state["last_scan"] = risk
    save_state(root, state)
    write_json(risk_path(root), risk)
    report = build_risk_report(risk)
    report_path = hulun_dir(root) / RISK_REPORT_FILE
    report_path.write_text(report, encoding="utf-8")
    return state, risk, report_path


def build_risk_report(risk: dict[str, Any]) -> str:
    lines = ["# HulunGuard Risk Report", "", f"Score: {risk['score']} ({risk['band']})", ""]
    lines.append(f"Slop index: {risk.get('slop_index', risk['score'])}")
    lines.append(f"Threshold: {risk['threshold']}")
    lines.append(f"Required action: {risk['required_action']}")
    lines.extend(["", "## Components"])
    for key, value in risk.get("components", {}).items():
        weight = risk.get("weights", {}).get(key)
        suffix = f" / {weight}" if weight is not None else ""
        lines.append(f"- {key}: {value}{suffix}")
    lines.extend(["", "## Reasons"])
    lines.extend([f"- {reason}" for reason in risk.get("reasons", [])])
    return "\n".join(lines) + "\n"


def cmd_scan(args: argparse.Namespace) -> int:
    _state, risk, report_path = run_scan(args, final_attempt=args.final_attempt)
    if args.json:
        print(json.dumps(risk, ensure_ascii=False, indent=2))
    else:
        print(f"HulunGauge: {risk['score']} / 100 ({risk['band']})")
        print(f"Required action: {risk['required_action']}")
        for reason in risk.get("reasons", []):
            print(f"- {reason}")
        print(f"Report: {report_path}")
    return 2 if risk["blocked"] and args.fail_on_threshold else 0


def verify_state(state: dict[str, Any], risk: dict[str, Any], allow_pending: bool) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    items = criteria(state)
    evidence_ids = {item.get("id") for item in state.get("evidence", [])}

    if not state.get("objective", "").strip():
        failures.append("Missing objective.")
    if not items:
        failures.append("No success criteria recorded.")

    for item in items:
        cid = item.get("id")
        if item.get("status") != "done":
            failures.append(f"Criterion {cid} is not done: {item.get('text', '')}")
        if not item.get("evidence"):
            failures.append(f"Criterion {cid} has no evidence.")
        for evidence_id in item.get("evidence", []):
            if evidence_id not in evidence_ids:
                failures.append(f"Criterion {cid} references unknown evidence {evidence_id}.")

    for step in state.get("steps", []):
        sid = step.get("id")
        status = step.get("status")
        if status in {"pending", "in_progress", "blocked"} and not allow_pending:
            failures.append(f"Step {sid} is still {status}: {step.get('text', '')}")
        if status == "done" and not step.get("evidence"):
            warnings.append(f"Step {sid} is done but has no evidence.")
        for evidence_id in step.get("evidence", []):
            if evidence_id not in evidence_ids:
                failures.append(f"Step {sid} references unknown evidence {evidence_id}.")

    if not state.get("evidence"):
        failures.append("No evidence recorded.")
    if risk.get("blocked"):
        failures.append(f"HulunGauge is above threshold: {risk['score']} >= {risk['threshold']}.")
    if not state.get("checkpoints"):
        warnings.append("No checkpoints recorded.")

    return {"pass": not failures, "failures": failures, "warnings": warnings, "risk": risk}


def cmd_verify(args: argparse.Namespace) -> int:
    state, risk, _report_path = run_scan(args, final_attempt=True)
    result = verify_state(state, risk, args.allow_pending)
    state["last_verify"] = {
        "generated_at": utc_now(),
        "pass": result["pass"],
        "failures": result["failures"],
        "warnings": result["warnings"],
    }
    save_state(project_root(args.root), state)
    report = build_verify_markdown(result)
    verify_path(project_root(args.root)).write_text(report, encoding="utf-8")
    print(report if not args.json else json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 2


def cmd_dashboard(args: argparse.Namespace) -> int:
    state, risk, _report_path = run_scan(args, final_attempt=False)
    html = build_dashboard_html(state, risk)
    output = hulun_dir(project_root(args.root)) / DASHBOARD_FILE
    output.write_text(html, encoding="utf-8")
    print(f"Dashboard: {output}")
    return 0


def refresh_dashboard(root: Path, threshold: int | None, checkpoint_stale_minutes: int) -> Path:
    class ScanArgs:
        pass

    scan_args = ScanArgs()
    scan_args.root = str(root)
    scan_args.threshold = threshold
    scan_args.checkpoint_stale_minutes = checkpoint_stale_minutes
    state, risk, _report_path = run_scan(scan_args, final_attempt=False)
    output = hulun_dir(root) / DASHBOARD_FILE
    output.write_text(build_dashboard_html(state, risk), encoding="utf-8")
    return output


def cmd_serve(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    output = refresh_dashboard(root, args.threshold, args.checkpoint_stale_minutes)

    stop = threading.Event()

    def refresher() -> None:
        while not stop.wait(args.refresh_seconds):
            try:
                refresh_dashboard(root, args.threshold, args.checkpoint_stale_minutes)
            except Exception as exc:  # pragma: no cover - diagnostics for interactive runs
                print(f"Dashboard refresh failed: {exc}", file=sys.stderr)

    if args.refresh_seconds > 0:
        thread = threading.Thread(target=refresher, daemon=True)
        thread.start()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(hulun_dir(root)))
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as server:
        actual_host, actual_port = server.server_address
        host_for_url = host_for_browser_url(actual_host)
        url = f"http://{host_for_url}:{actual_port}/{DASHBOARD_FILE}"
        print(f"Dashboard file: {output}")
        print(f"Serving HulunGauge: {url}")
        print("Press Ctrl+C to stop.")
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped HulunGauge server.")
        finally:
            stop.set()
    return 0


def cmd_open_monitor(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    score = args.score
    reasons = ["Monitor opened."]
    try:
        if (hulun_dir(root) / "state.json").exists():
            state = load_state(root)
            risk = scan_state(state, threshold=None, final_attempt=False, checkpoint_stale_minutes=45)
            score = int(risk["score"]) if score is None else score
            reasons = risk.get("reasons", reasons)
    except Exception as exc:  # pragma: no cover - diagnostics for interactive monitor startup
        print(f"Monitor startup scan failed: {exc}", file=sys.stderr)
    if score is None:
        score = 30
    monitor = create_monitor(args.conversation, args.group, str(root), score, reasons=reasons)
    if args.widget:
        launch_widget(monitor["id"], x=args.x, y=args.y)
    print(json.dumps(monitor, ensure_ascii=False, indent=2) if args.json else f"Opened monitor {monitor['id']} ({monitor['conversation']}) score={monitor['score']} band={monitor['band']}")
    return 0


def cmd_update_monitor(args: argparse.Namespace) -> int:
    monitor = update_monitor(
        args.id,
        score=args.score,
        delta=args.delta,
        summary=args.summary,
        result=args.result,
        reason=args.reason,
        status=args.status,
        group=args.group,
        conversation=args.conversation,
    )
    print(json.dumps(monitor, ensure_ascii=False, indent=2) if args.json else f"Updated {monitor['id']}: {monitor['score']} {monitor['band']}")
    return 0


def cmd_close_monitor(args: argparse.Namespace) -> int:
    monitor = close_monitor(args.id)
    print(f"Closed {monitor['id']}")
    return 0


def cmd_widget(args: argparse.Namespace) -> int:
    if args.once:
        from .widget import HulunWidget

        HulunWidget(args.id, args.x, args.y, once=True).run()
    else:
        launch_widget(args.id, x=args.x, y=args.y)
        print(f"Widget launched for {args.id}")
    return 0


def write_board() -> Path:
    monitors = list_monitors()
    html = build_board_html(monitors, group_summary(monitors))
    output = board_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def cmd_board(args: argparse.Namespace) -> int:
    output = write_board()
    if args.serve:
        stop = threading.Event()

        def refresher() -> None:
            while not stop.wait(args.refresh_seconds):
                try:
                    write_board()
                except Exception as exc:  # pragma: no cover
                    print(f"Board refresh failed: {exc}", file=sys.stderr)

        if args.refresh_seconds > 0:
            threading.Thread(target=refresher, daemon=True).start()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(hulun_home()))
        with socketserver.ThreadingTCPServer((args.host, args.port), handler) as server:
            actual_host, actual_port = server.server_address
            host_for_url = host_for_browser_url(actual_host)
            url = f"http://{host_for_url}:{actual_port}/{output.name}"
            print(f"Board file: {output}")
            print(f"Serving HulunGuard Board: {url}")
            print("Press Ctrl+C to stop.")
            if args.open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nStopped HulunGuard board server.")
            finally:
                stop.set()
        return 0
    if args.json:
        payload = {"board": str(output), "monitors": list_monitors(), "groups": group_summary(list_monitors())}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.open:
        webbrowser.open(output.resolve().as_uri())
    print(f"Board: {output}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    root = project_root(args.root)
    text = f"""#HULUN_ON
Use HulunGuard for this conversation.

Run this first:
hulun open --root "{root}" --conversation "{args.conversation}" --group "{args.group}" --widget

During work:
- Record evidence after real progress.
- Run scan before major claims.
- Run verify before final answer.
- If HulunGauge is red or verify fails, do not claim completion.
"""
    print(text)
    return 0


def add_root(parent: argparse.ArgumentParser) -> None:
    parent.add_argument("--root", default=argparse.SUPPRESS, help="Project root. Defaults to current directory.")


def add_privacy_controls(parent: argparse.ArgumentParser) -> None:
    parent.add_argument(
        "--include-sensitive",
        action="store_true",
        help="Persist raw sensitive trace text instead of default redacted summaries. Use only in trusted local environments.",
    )
    parent.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Retention hint written to privacy metadata. Defaults to {DEFAULT_RETENTION_DAYS} days.",
    )


def build_parser() -> argparse.ArgumentParser:
    root_parent = argparse.ArgumentParser(add_help=False)
    add_root(root_parent)

    parser = argparse.ArgumentParser(prog="hulun", description="HulunGuard: proof-first reliability guard for long-running agents.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--version", action="version", version=f"hulun {package_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[root_parent])
    init.add_argument("--objective", required=True)
    init.add_argument("--criterion", action="append", default=[])
    init.add_argument("--constraint", action="append", default=[])
    init.add_argument("--assumption", action="append", default=[])
    init.add_argument("--threshold", type=int, default=66)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    add_criterion = sub.add_parser("add-criterion", parents=[root_parent])
    add_criterion.add_argument("--text", required=True)
    add_criterion.set_defaults(func=cmd_add_criterion)

    set_criterion = sub.add_parser("set-criterion", parents=[root_parent])
    set_criterion.add_argument("--id", required=True)
    set_criterion.add_argument("--status", required=True)
    set_criterion.add_argument("--evidence", action="append", default=[])
    set_criterion.set_defaults(func=cmd_set_criterion)

    add_step = sub.add_parser("add-step", parents=[root_parent])
    add_step.add_argument("--text", required=True)
    add_step.add_argument("--status", default="pending")
    add_step.add_argument("--evidence", action="append", default=[])
    add_step.set_defaults(func=cmd_add_step)

    set_step = sub.add_parser("set-step", parents=[root_parent])
    set_step.add_argument("--id", required=True)
    set_step.add_argument("--status", required=True)
    set_step.add_argument("--evidence", action="append", default=[])
    set_step.set_defaults(func=cmd_set_step)

    evidence = sub.add_parser("record-evidence", parents=[root_parent])
    evidence.add_argument("--kind", required=True, choices=["command", "file", "source", "test", "artifact", "decision", "approval", "other"])
    evidence.add_argument("--summary", required=True)
    evidence.add_argument("--command")
    evidence.add_argument("--path")
    evidence.add_argument("--url")
    evidence.add_argument("--notes")
    evidence.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    add_privacy_controls(evidence)
    evidence.set_defaults(func=cmd_record_evidence)

    event = sub.add_parser("event", parents=[root_parent])
    event.add_argument("--type", required=True)
    event.add_argument("--summary", required=True)
    event.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    event.add_argument("--ref", action="append", default=[])
    event.add_argument("--evidence", action="append", default=[])
    event.add_argument("--resolved", action="store_true")
    add_privacy_controls(event)
    event.set_defaults(func=cmd_event)

    quickstart = sub.add_parser("quickstart", parents=[root_parent])
    quickstart.add_argument("--objective")
    quickstart.add_argument("--criterion")
    quickstart.add_argument("--conversation")
    quickstart.add_argument("--group")
    quickstart.add_argument("--json", action="store_true")
    quickstart.set_defaults(func=cmd_quickstart)

    doctor = sub.add_parser("doctor", parents=[root_parent])
    doctor.add_argument("--run-validation", action="store_true")
    doctor.add_argument("--fail-on-error", action="store_true")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    cleanup = sub.add_parser("cleanup", parents=[root_parent])
    cleanup_mode = cleanup.add_mutually_exclusive_group()
    cleanup_mode.add_argument("--apply", action="store_true", help="Delete expired records and reports. Default is dry-run.")
    cleanup_mode.add_argument("--dry-run", action="store_true", help="Preview cleanup without changing files. This is the default.")
    cleanup.add_argument("--default-retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    cleanup.add_argument("--skip-conversations", action="store_true")
    cleanup.add_argument("--skip-reports", action="store_true")
    cleanup.add_argument("--write-report", action="store_true")
    cleanup.add_argument("--json", action="store_true")
    cleanup.set_defaults(func=cmd_cleanup)

    schema_check = sub.add_parser("schema-check", parents=[root_parent])
    schema_check.add_argument("--fixture-dir")
    schema_check.add_argument("--json", action="store_true")
    schema_check.set_defaults(func=cmd_schema_check)

    threat_model_check = sub.add_parser("threat-model-check", parents=[root_parent])
    threat_model_check.add_argument("--json", action="store_true")
    threat_model_check.set_defaults(func=cmd_threat_model_check)

    adapter_matrix = sub.add_parser("adapter-matrix", parents=[root_parent])
    adapter_matrix.add_argument("--json", action="store_true")
    adapter_matrix.set_defaults(func=cmd_adapter_matrix)

    benchmark = sub.add_parser("benchmark", parents=[root_parent])
    benchmark.add_argument("--suite", choices=["scan", "real-world"], default="scan")
    benchmark.add_argument("--events", type=int, default=10000)
    benchmark.add_argument("--max-ms", type=float)
    benchmark.add_argument("--max-case-ms", type=float, default=50.0)
    benchmark.add_argument("--max-case-bytes", type=int, default=65536)
    benchmark.add_argument("--max-total-bytes", type=int, default=524288)
    benchmark.add_argument("--min-component-stability", type=float, default=1.0)
    benchmark.add_argument("--max-false-positive-rate", type=float, default=0.0)
    benchmark.add_argument("--max-false-negative-rate", type=float, default=0.0)
    benchmark.add_argument("--json", action="store_true")
    benchmark.set_defaults(func=cmd_benchmark)

    compatibility = sub.add_parser("compatibility")
    compatibility.add_argument("--json", action="store_true")
    compatibility.set_defaults(func=cmd_compatibility)

    integration_kit = sub.add_parser("integration-kit", parents=[root_parent])
    integration_kit.add_argument("--agent", choices=["all", *supported_agent_ids()], required=True)
    integration_kit.add_argument("--output", help="Write the kit to this directory. Defaults to .hulun/integration-kits/<agent>.")
    integration_kit.add_argument("--force", action="store_true", help="Overwrite HulunGuard-generated kit files if they already exist.")
    integration_kit.add_argument("--verify", action="store_true", help="Parse generated sample traces through the matching ingest adapter.")
    integration_kit.add_argument("--json", action="store_true")
    integration_kit.set_defaults(func=cmd_integration_kit)

    onboard = sub.add_parser("onboard", parents=[root_parent], help="Generate and verify a first-run agent onboarding path.")
    onboard.add_argument("--agent", choices=["all", *supported_agent_ids()], required=True, help="Supported agent id or all.")
    onboard.add_argument("--output", help="Output directory. Defaults to .hulun/onboarding.")
    onboard.add_argument("--force", action="store_true", help="Overwrite HulunGuard-generated onboarding kit files.")
    onboard.add_argument("--json", action="store_true")
    onboard.set_defaults(func=cmd_onboard)

    conversation = sub.add_parser("conversation")
    conversation_sub = conversation.add_subparsers(dest="conversation_command", required=True)

    conversation_start = conversation_sub.add_parser("start", parents=[root_parent])
    conversation_start.add_argument("--name", required=True)
    conversation_start.add_argument("--group", default="default")
    conversation_start.add_argument("--objective")
    conversation_start.add_argument("--monitor", action="store_true")
    conversation_start.add_argument("--widget", action="store_true")
    conversation_start.add_argument("--json", action="store_true")
    conversation_start.set_defaults(func=cmd_conversation_start)

    conversation_event = conversation_sub.add_parser("event")
    conversation_event.add_argument("--id", required=True)
    conversation_event.add_argument("--type", required=True)
    conversation_event.add_argument("--summary", required=True)
    conversation_event.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    conversation_event.add_argument("--phase", choices=sorted(VALID_EVENT_PHASES))
    conversation_event.add_argument("--claim", action="append", default=[])
    conversation_event.add_argument("--evidence", action="append", default=[])
    conversation_event.add_argument("--ref", action="append", default=[])
    conversation_event.add_argument("--resolved", action="store_true")
    conversation_event.add_argument("--action-key")
    conversation_event.add_argument("--prompt-tokens", type=int)
    conversation_event.add_argument("--completion-tokens", type=int)
    conversation_event.add_argument("--cost", type=float)
    conversation_event.add_argument("--latency-ms", type=int)
    conversation_event.add_argument("--model")
    conversation_event.add_argument("--fail-on-red", action="store_true")
    add_privacy_controls(conversation_event)
    conversation_event.add_argument("--json", action="store_true")
    conversation_event.set_defaults(func=cmd_conversation_event)

    conversation_scan = conversation_sub.add_parser("scan")
    conversation_scan.add_argument("--id", required=True)
    conversation_scan.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    conversation_scan.add_argument("--fail-on-red", action="store_true")
    conversation_scan.add_argument("--json", action="store_true")
    conversation_scan.set_defaults(func=cmd_conversation_scan)

    conversation_status = conversation_sub.add_parser("status")
    conversation_status.add_argument("--id", required=True)
    conversation_status.add_argument("--tail", type=int, default=5)
    conversation_status.add_argument("--json", action="store_true")
    conversation_status.set_defaults(func=cmd_conversation_status)

    conversation_close = conversation_sub.add_parser("close")
    conversation_close.add_argument("--id", required=True)
    conversation_close.add_argument("--json", action="store_true")
    conversation_close.set_defaults(func=cmd_conversation_close)

    observe = sub.add_parser("observe", parents=[root_parent])
    observe.add_argument("--type", required=True, help="Runtime event type, such as tool_result, llm_call, final_attempt, or summary.")
    observe.add_argument("--summary", required=True)
    observe.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    observe.add_argument("--phase", choices=sorted(VALID_EVENT_PHASES))
    observe.add_argument("--claim", action="append", default=[], help="Completion or verification claim made by the agent.")
    observe.add_argument("--evidence", action="append", default=[], help="Evidence ids that support this observation.")
    observe.add_argument("--ref", action="append", default=[], help="Path, URL, trace id, or command reference.")
    observe.add_argument("--resolved", action="store_true")
    observe.add_argument("--source-platform", help="Adapter source, e.g. manual, langgraph, swe-agent, openhands, langfuse, phoenix.")
    observe.add_argument("--action-key", help="Stable action fingerprint for retry-loop detection.")
    observe.add_argument("--prompt-tokens", type=int)
    observe.add_argument("--completion-tokens", type=int)
    observe.add_argument("--cost", type=float)
    observe.add_argument("--latency-ms", type=int)
    observe.add_argument("--model")
    observe.add_argument("--scan", action="store_true", help="Scan immediately after recording the observation.")
    observe.add_argument("--threshold", type=int)
    observe.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    observe.add_argument("--final-attempt", action="store_true")
    observe.add_argument("--fail-on-threshold", action="store_true")
    add_privacy_controls(observe)
    observe.add_argument("--json", action="store_true")
    observe.set_defaults(func=cmd_observe)

    ingest = sub.add_parser("ingest", parents=[root_parent])
    ingest.add_argument("--file", required=True, help="JSON or JSONL trace file to import.")
    ingest.add_argument(
        "--format",
        choices=["auto", "generic", "opentelemetry", "openinference", "openhands", "swe-agent", "langgraph", "langsmith", "langfuse", "phoenix"],
        default="auto",
    )
    ingest.add_argument("--max-trace-bytes", type=int, default=MAX_TRACE_BYTES, help=f"Reject trace files larger than this many bytes. Defaults to {MAX_TRACE_BYTES}.")
    ingest.add_argument("--source-platform", help="Override source platform on imported events.")
    ingest.add_argument("--scan", action="store_true", help="Scan immediately after import.")
    ingest.add_argument("--threshold", type=int)
    ingest.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    ingest.add_argument("--final-attempt", action="store_true")
    ingest.add_argument("--fail-on-threshold", action="store_true")
    ingest.add_argument("--include-events", action="store_true")
    ingest.add_argument("--init-if-missing", action="store_true", help="Create a minimal HulunGuard project ledger before import if no state exists.")
    ingest.add_argument("--init-objective", help="Objective used with --init-if-missing.")
    ingest.add_argument("--init-criterion", help="Criterion used with --init-if-missing.")
    ingest.add_argument("--init-threshold", type=int, default=66, help="Risk threshold used with --init-if-missing.")
    add_privacy_controls(ingest)
    ingest.add_argument("--json", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    export_otel = sub.add_parser("export-otel", parents=[root_parent])
    export_otel.add_argument("--output", required=True, help="Write OpenTelemetry OTLP JSON to this file.")
    export_otel.add_argument("--json", action="store_true")
    export_otel.set_defaults(func=cmd_export_otel)

    validate = sub.add_parser("validate", parents=[root_parent])
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    calibrate = sub.add_parser("calibrate", parents=[root_parent])
    calibrate.add_argument("--min-precision", type=float, default=0.90)
    calibrate.add_argument("--min-recall", type=float, default=0.90)
    calibrate.add_argument("--json", action="store_true")
    calibrate.set_defaults(func=cmd_calibrate)

    calibration_drift = sub.add_parser("calibration-drift", parents=[root_parent])
    calibration_drift.add_argument("--baseline", default="docs/calibration_baseline.json")
    calibration_drift.add_argument("--min-precision", type=float, default=0.90)
    calibration_drift.add_argument("--min-recall", type=float, default=0.90)
    calibration_drift.add_argument("--rationale")
    calibration_drift.add_argument("--json", action="store_true")
    calibration_drift.set_defaults(func=cmd_calibration_drift)

    mcp = sub.add_parser("mcp", parents=[root_parent])
    add_privacy_controls(mcp)
    mcp.set_defaults(func=cmd_mcp)

    risk = sub.add_parser("add-risk", parents=[root_parent])
    risk.add_argument("--text", required=True)
    risk.set_defaults(func=cmd_add_risk)

    decision = sub.add_parser("add-decision", parents=[root_parent])
    decision.add_argument("--text", required=True)
    decision.add_argument("--reason")
    decision.set_defaults(func=cmd_add_decision)

    checkpoint = sub.add_parser("checkpoint", parents=[root_parent])
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--next-action")
    checkpoint.set_defaults(func=cmd_checkpoint)

    status = sub.add_parser("status", parents=[root_parent])
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    resume = sub.add_parser("resume", parents=[root_parent])
    resume.set_defaults(func=cmd_resume)

    scan = sub.add_parser("scan", parents=[root_parent])
    scan.add_argument("--threshold", type=int)
    scan.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    scan.add_argument("--final-attempt", action="store_true")
    scan.add_argument("--fail-on-threshold", action="store_true")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=cmd_scan)

    verify = sub.add_parser("verify", parents=[root_parent])
    verify.add_argument("--threshold", type=int)
    verify.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    verify.add_argument("--allow-pending", action="store_true")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    dashboard = sub.add_parser("dashboard", parents=[root_parent])
    dashboard.add_argument("--threshold", type=int)
    dashboard.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    dashboard.set_defaults(func=cmd_dashboard)

    serve = sub.add_parser("serve", parents=[root_parent])
    serve.add_argument("--threshold", type=int)
    serve.add_argument("--checkpoint-stale-minutes", type=int, default=45)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--refresh-seconds", type=int, default=5)
    serve.add_argument("--open", action="store_true")
    serve.set_defaults(func=cmd_serve)

    open_monitor = sub.add_parser("open", parents=[root_parent])
    open_monitor.add_argument("--conversation", required=True)
    open_monitor.add_argument("--group", default="default")
    open_monitor.add_argument("--score", type=int)
    open_monitor.add_argument("--widget", action="store_true")
    open_monitor.add_argument("--x", type=int)
    open_monitor.add_argument("--y", type=int)
    open_monitor.add_argument("--json", action="store_true")
    open_monitor.set_defaults(func=cmd_open_monitor)

    update = sub.add_parser("update")
    update.add_argument("--id", required=True)
    update.add_argument("--score", type=int)
    update.add_argument("--delta", type=int, default=0)
    update.add_argument("--summary")
    update.add_argument("--reason")
    update.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    update.add_argument("--status", choices=["active", "paused", "closed"])
    update.add_argument("--group")
    update.add_argument("--conversation")
    update.add_argument("--json", action="store_true")
    update.set_defaults(func=cmd_update_monitor)

    close = sub.add_parser("close")
    close.add_argument("--id", required=True)
    close.set_defaults(func=cmd_close_monitor)

    widget = sub.add_parser("widget")
    widget.add_argument("--id", required=True)
    widget.add_argument("--x", type=int)
    widget.add_argument("--y", type=int)
    widget.add_argument("--once", action="store_true")
    widget.set_defaults(func=cmd_widget)

    board = sub.add_parser("board")
    board.add_argument("--open", action="store_true")
    board.add_argument("--json", action="store_true")
    board.add_argument("--serve", action="store_true")
    board.add_argument("--host", default="127.0.0.1")
    board.add_argument("--port", type=int, default=8766)
    board.add_argument("--refresh-seconds", type=int, default=5)
    board.set_defaults(func=cmd_board)

    prompt = sub.add_parser("prompt", parents=[root_parent])
    prompt.add_argument("--conversation", default="agent-conversation")
    prompt.add_argument("--group", default="default")
    prompt.set_defaults(func=cmd_prompt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
