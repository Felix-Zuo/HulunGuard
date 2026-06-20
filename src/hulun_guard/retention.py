from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CONVERSATIONS_DIR
from .monitor import hulun_home
from .privacy import DEFAULT_RETENTION_DAYS
from .schemas import RETENTION_CLEANUP_SCHEMA
from .storage import hulun_dir, load_state, save_state
from .util import parse_time, utc_now

GENERATED_REPORT_FILES = (
    "risk.json",
    "risk_report.md",
    "validation_report.json",
    "validation_report.md",
    "calibration_report.json",
    "calibration_report.md",
    "calibration_drift_report.json",
    "calibration_drift_report.md",
    "benchmark_report.json",
    "real_world_benchmark_report.json",
    "real_world_benchmark_report.md",
    "verification_report.md",
    "dashboard.html",
    "resume.md",
    "retention_cleanup_report.json",
    "retention_cleanup_report.md",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(value: str | None, *, now: datetime) -> float | None:
    parsed = parse_time(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _retention_days(record: dict[str, Any], default_retention_days: int) -> int:
    privacy = record.get("privacy") if isinstance(record.get("privacy"), dict) else {}
    value = privacy.get("retention_days") if isinstance(privacy, dict) else None
    try:
        return max(1, int(value if value not in (None, "") else default_retention_days))
    except (TypeError, ValueError):
        return max(1, int(default_retention_days))


def _record_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _id_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _record_id(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    value = record.get("id")
    return str(value) if value else None


def _is_expired(record: dict[str, Any], *, now: datetime, default_retention_days: int) -> bool:
    age = _age_days(record.get("created_at"), now=now)
    return age is not None and age > _retention_days(record, default_retention_days)


def _scan_is_expired(scan: dict[str, Any] | None, *, now: datetime, default_retention_days: int) -> bool:
    if not isinstance(scan, dict):
        return False
    age = _age_days(scan.get("generated_at"), now=now)
    return age is not None and age > max(1, int(default_retention_days))


def _resolve_under(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _project_base_is_safe(root: Path, project_dir: Path, violations: list[dict[str, Any]]) -> bool:
    if project_dir.exists() and project_dir.is_symlink():
        violations.append({"path": str(project_dir), "allowed_base": str(root), "reason": "project_state_dir_symlink"})
        return False
    if project_dir.exists() and not _resolve_under(project_dir, root):
        violations.append({"path": str(project_dir), "allowed_base": str(root), "reason": "project_state_dir_outside_root"})
        return False
    return True


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _file_age_days(path: Path, *, now: datetime) -> float | None:
    payload = _load_json(path) if path.suffix.lower() == ".json" else None
    if payload:
        generated_at = payload.get("generated_at")
        if isinstance(generated_at, str):
            age = _age_days(generated_at, now=now)
            if age is not None:
                return age
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return max(0.0, (now - modified).total_seconds() / 86400.0)


def _safe_delete(path: Path, *, allowed_base: Path, dry_run: bool, violations: list[dict[str, Any]]) -> bool:
    if not _resolve_under(path, allowed_base):
        violations.append({"path": str(path), "allowed_base": str(allowed_base), "reason": "path_outside_allowed_base"})
        return False
    if not path.exists() or not path.is_file():
        return False
    if not dry_run:
        path.unlink()
    return True


def _safe_write_json(path: Path, payload: dict[str, Any], *, allowed_base: Path, dry_run: bool, violations: list[dict[str, Any]]) -> bool:
    if not _resolve_under(path, allowed_base):
        violations.append({"path": str(path), "allowed_base": str(allowed_base), "reason": "write_outside_allowed_base"})
        return False
    if dry_run:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def _clean_project_state(
    root: Path,
    *,
    now: datetime,
    dry_run: bool,
    default_retention_days: int,
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    project_dir = hulun_dir(root)
    project_result: dict[str, Any] = {
        "state_found": False,
        "state_updated": False,
        "expired_events": [],
        "expired_evidence": [],
        "last_scan_removed": False,
        "references_cleaned": 0,
    }
    if not _project_base_is_safe(root, project_dir, violations):
        return project_result
    state_file = project_dir / "state.json"
    if not state_file.exists():
        return project_result
    if not _resolve_under(state_file, project_dir):
        violations.append({"path": str(state_file), "allowed_base": str(project_dir), "reason": "state_outside_project_dir"})
        return project_result

    state = load_state(root)
    project_result["state_found"] = True
    events = _record_list(state.get("events"))
    evidence_records = _record_list(state.get("evidence"))
    expired_events = [event for event in events if isinstance(event, dict) and _is_expired(event, now=now, default_retention_days=default_retention_days)]
    expired_evidence = [
        evidence for evidence in evidence_records if isinstance(evidence, dict) and _is_expired(evidence, now=now, default_retention_days=default_retention_days)
    ]
    expired_event_ids = {event_id for event in expired_events if (event_id := _record_id(event))}
    expired_evidence_ids = {evidence_id for evidence in expired_evidence if (evidence_id := _record_id(evidence))}

    project_result["expired_events"] = sorted(expired_event_ids)
    project_result["expired_evidence"] = sorted(expired_evidence_ids)

    changed = bool(expired_event_ids or expired_evidence_ids)
    if expired_event_ids:
        state["events"] = [event for event in events if _record_id(event) not in expired_event_ids]
    if expired_evidence_ids:
        state["evidence"] = [evidence for evidence in evidence_records if _record_id(evidence) not in expired_evidence_ids]
        for collection_name in ("criteria", "success_criteria", "steps"):
            for item in _record_list(state.get(collection_name)):
                if not isinstance(item, dict):
                    continue
                original = _id_list(item.get("evidence"))
                cleaned = [evidence_id for evidence_id in original if str(evidence_id) not in expired_evidence_ids]
                if cleaned != original:
                    item["evidence"] = cleaned
                    project_result["references_cleaned"] += len(original) - len(cleaned)
                    changed = True
        for event in _record_list(state.get("events")):
            if not isinstance(event, dict):
                continue
            original = _id_list(event.get("evidence"))
            cleaned = [evidence_id for evidence_id in original if str(evidence_id) not in expired_evidence_ids]
            if cleaned != original:
                event["evidence"] = cleaned
                project_result["references_cleaned"] += len(original) - len(cleaned)
                changed = True

    if _scan_is_expired(state.get("last_scan"), now=now, default_retention_days=default_retention_days):
        state["last_scan"] = None
        project_result["last_scan_removed"] = True
        changed = True

    if changed:
        project_result["state_updated"] = True
        if not dry_run:
            save_state(root, state)
    return project_result


def _clean_conversations(
    *,
    now: datetime,
    dry_run: bool,
    default_retention_days: int,
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    home = hulun_home()
    conversations = home / CONVERSATIONS_DIR
    result: dict[str, Any] = {
        "home": str(home),
        "directory": str(conversations),
        "files_scanned": 0,
        "files_updated": 0,
        "expired_events": 0,
        "items": [],
    }
    if not conversations.exists():
        return result
    for path in sorted(conversations.glob("*.json")):
        result["files_scanned"] += 1
        item: dict[str, Any] = {
            "path": str(path),
            "id": path.stem,
            "expired_events": [],
            "remaining_events": None,
            "last_scan_removed": False,
            "updated": False,
        }
        if not _resolve_under(path, conversations):
            violations.append({"path": str(path), "allowed_base": str(conversations), "reason": "conversation_outside_directory"})
            result["items"].append(item)
            continue
        payload = _load_json(path)
        if payload is None:
            item["error"] = "invalid_json"
            result["items"].append(item)
            continue
        events = _record_list(payload.get("events"))
        expired_events = [event for event in events if isinstance(event, dict) and _is_expired(event, now=now, default_retention_days=default_retention_days)]
        expired_event_ids = {event_id for event in expired_events if (event_id := _record_id(event))}
        if expired_event_ids:
            payload["events"] = [event for event in events if _record_id(event) not in expired_event_ids]
        if _scan_is_expired(payload.get("last_scan"), now=now, default_retention_days=default_retention_days):
            payload["last_scan"] = None
            item["last_scan_removed"] = True
        item["expired_events"] = sorted(expired_event_ids)
        item["remaining_events"] = len(_record_list(payload.get("events")))
        changed = bool(expired_event_ids) or item["last_scan_removed"]
        item["updated"] = changed
        if changed:
            result["files_updated"] += 1
            result["expired_events"] += len(expired_event_ids)
            if not dry_run:
                payload["updated_at"] = utc_now()
                _safe_write_json(path, payload, allowed_base=conversations, dry_run=dry_run, violations=violations)
        result["items"].append(item)
    return result


def _clean_reports(
    root: Path,
    *,
    now: datetime,
    dry_run: bool,
    default_retention_days: int,
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    project_dir = hulun_dir(root)
    reports: list[dict[str, Any]] = []
    deleted = 0
    if not _project_base_is_safe(root, project_dir, violations):
        return {"files_scanned": 0, "files_deleted": 0, "items": reports}
    for relative in GENERATED_REPORT_FILES:
        path = project_dir / relative
        item = {"path": str(path), "name": relative, "expired": False, "action": "none"}
        if not _resolve_under(path, project_dir):
            violations.append({"path": str(path), "allowed_base": str(project_dir), "reason": "report_outside_project_dir"})
            item["action"] = "blocked"
            reports.append(item)
            continue
        if not path.exists() or not path.is_file():
            reports.append(item)
            continue
        age = _file_age_days(path, now=now)
        item["age_days"] = round(age, 4) if age is not None else None
        if age is not None and age > max(1, int(default_retention_days)):
            item["expired"] = True
            item["action"] = "would_delete" if dry_run else "deleted"
            if _safe_delete(path, allowed_base=project_dir, dry_run=dry_run, violations=violations):
                deleted += 1
        reports.append(item)
    return {"files_scanned": len(reports), "files_deleted": deleted, "items": reports}


def build_retention_cleanup_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# HulunGuard Retention Cleanup Report",
        "",
        f"Mode: {'dry-run' if result['dry_run'] else 'apply'}",
        f"Root: {result['root']}",
        f"Default retention: {result['default_retention_days']} days",
        "",
        "## Summary",
        "",
        f"- Expired project events: {summary['expired_project_events']}",
        f"- Expired project evidence: {summary['expired_project_evidence']}",
        f"- Expired conversation events: {summary['expired_conversation_events']}",
        f"- Report files deleted: {summary['report_files_deleted']}",
        f"- Safety violations: {summary['safety_violations']}",
    ]
    if result["safety_violations"]:
        lines.extend(["", "## Safety Violations", ""])
        for violation in result["safety_violations"]:
            detail = ", ".join(f"{key}={value}" for key, value in violation.items())
            lines.append(f"- {detail}")
    return "\n".join(lines) + "\n"


def retention_cleanup_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def run_retention_cleanup(
    root: Path,
    *,
    dry_run: bool = True,
    include_conversations: bool = True,
    include_reports: bool = True,
    default_retention_days: int = DEFAULT_RETENTION_DAYS,
    write_report: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    now = _now()
    violations: list[dict[str, Any]] = []
    project = _clean_project_state(root, now=now, dry_run=dry_run, default_retention_days=default_retention_days, violations=violations)
    conversations = (
        _clean_conversations(now=now, dry_run=dry_run, default_retention_days=default_retention_days, violations=violations)
        if include_conversations
        else {"skipped": True, "files_scanned": 0, "files_updated": 0, "expired_events": 0, "items": []}
    )
    reports = (
        _clean_reports(root, now=now, dry_run=dry_run, default_retention_days=default_retention_days, violations=violations)
        if include_reports
        else {"skipped": True, "files_scanned": 0, "files_deleted": 0, "items": []}
    )
    result: dict[str, Any] = {
        "schema": RETENTION_CLEANUP_SCHEMA,
        "generated_at": utc_now(),
        "root": str(root),
        "hulun_dir": str(hulun_dir(root)),
        "dry_run": dry_run,
        "applied": not dry_run,
        "default_retention_days": max(1, int(default_retention_days)),
        "project": project,
        "conversations": conversations,
        "reports": reports,
        "safety_violations": violations,
    }
    result["summary"] = {
        "expired_project_events": len(project["expired_events"]),
        "expired_project_evidence": len(project["expired_evidence"]),
        "expired_conversation_events": conversations.get("expired_events", 0),
        "conversation_files_scanned": conversations.get("files_scanned", 0),
        "report_files_deleted": reports.get("files_deleted", 0),
        "safety_violations": len(violations),
    }
    result["gate"] = {"passed": not violations, "failure_count": len(violations)}

    if write_report:
        project_dir = hulun_dir(root)
        if not _project_base_is_safe(root, project_dir, violations):
            result["summary"]["safety_violations"] = len(violations)
            result["gate"] = {"passed": not violations, "failure_count": len(violations)}
            return result
        json_path = project_dir / "retention_cleanup_report.json"
        markdown_path = project_dir / "retention_cleanup_report.md"
        _safe_write_json(json_path, result, allowed_base=project_dir, dry_run=False, violations=violations)
        if _resolve_under(markdown_path, project_dir):
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(build_retention_cleanup_markdown(result), encoding="utf-8")
        else:
            violations.append({"path": str(markdown_path), "allowed_base": str(project_dir), "reason": "write_outside_allowed_base"})
        result["summary"]["safety_violations"] = len(violations)
        result["gate"] = {"passed": not violations, "failure_count": len(violations)}
    return result
