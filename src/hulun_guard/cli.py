from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from .constants import DASHBOARD_FILE, RISK_REPORT_FILE, VALID_STATUSES
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
from .reports import build_board_html, build_dashboard_html, build_verify_markdown
from .risk import scan_state
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


def require_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status '{status}'. Expected one of: {', '.join(sorted(VALID_STATUSES))}")
    return status


def append_event(
    state: dict[str, Any],
    event_type: str,
    summary: str,
    *,
    result: str = "pass",
    refs: list[str] | None = None,
    resolved: bool | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    event = {
        "id": next_id(state.setdefault("events", []), "EV"),
        "type": event_type,
        "summary": summary.strip(),
        "result": result,
        "refs": refs or [],
        "evidence": evidence or [],
        "created_at": utc_now(),
    }
    if resolved is not None:
        event["resolved"] = resolved
    state["events"].append(event)
    return event


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
    state["evidence"].append({k: v for k, v in evidence.items() if v not in (None, "")})
    append_event(state, "evidence", f"{evidence['id']}: {args.summary}", result=args.result, refs=refs, evidence=[evidence["id"]])
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
    )
    save_state(root, state)
    print(f"Recorded event {event['id']}")
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
    lines.append(f"Threshold: {risk['threshold']}")
    lines.append(f"Required action: {risk['required_action']}")
    lines.extend(["", "## Components"])
    for key, value in risk.get("components", {}).items():
        lines.append(f"- {key}: {value}")
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
        host_for_url = "127.0.0.1" if actual_host in {"0.0.0.0", ""} else actual_host
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
    except Exception:
        pass
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
            host_for_url = "127.0.0.1" if actual_host in {"0.0.0.0", ""} else actual_host
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


def build_parser() -> argparse.ArgumentParser:
    root_parent = argparse.ArgumentParser(add_help=False)
    add_root(root_parent)

    parser = argparse.ArgumentParser(prog="hulun", description="HulunGuard: proof-first reliability guard for long-running agents.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
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
    evidence.set_defaults(func=cmd_record_evidence)

    event = sub.add_parser("event", parents=[root_parent])
    event.add_argument("--type", required=True)
    event.add_argument("--summary", required=True)
    event.add_argument("--result", choices=["pass", "fail", "unknown"], default="pass")
    event.add_argument("--ref", action="append", default=[])
    event.add_argument("--evidence", action="append", default=[])
    event.add_argument("--resolved", action="store_true")
    event.set_defaults(func=cmd_event)

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
