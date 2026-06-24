from __future__ import annotations

import hmac
import http.client
import json
import shlex
import tempfile
import threading
import time
from dataclasses import dataclass, field
from html import escape as xml_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .adapters import MAX_TRACE_BYTES, parse_trace_text
from .constants import RISK_REPORT_FILE
from .privacy import DEFAULT_RETENTION_DAYS
from .queue import BATCH_FLUSH_LIMIT, BatchIngestError, enqueue_payload, flush_queue, queue_status
from .risk import scan_state
from .schemas import COLLECTOR_SCHEMA
from .storage import hulun_dir, load_state, project_root, risk_path, save_state, write_json
from .util import utc_now

DEFAULT_COLLECTOR_HOST = "127.0.0.1"
DEFAULT_COLLECTOR_PORT = 4318
COLLECTOR_STATUS_FILE = "collector_status.json"
COLLECTOR_SERVICE_TEMPLATE_DIR = "collector-service"
SERVICE_TEMPLATE_TARGETS = ("systemd", "launchd", "windows-task")
OVERSIZE_DRAIN_HARD_LIMIT_BYTES = 8 * 1024 * 1024
TRACE_PAYLOAD_FORMATS = (
    "auto",
    "generic",
    "opentelemetry",
    "openinference",
    "openhands",
    "swe-agent",
    "langgraph",
    "langsmith",
    "langfuse",
    "phoenix",
    "openai-agents",
)
JSON_CONTENT_TYPES = {"", "application/json", "application/x-ndjson", "application/jsonl", "text/plain"}


class CollectorError(ValueError):
    """Raised when the local HTTP collector cannot start safely."""


@dataclass(frozen=True)
class CollectorConfig:
    root: str | Path | None = None
    host: str = DEFAULT_COLLECTOR_HOST
    port: int = DEFAULT_COLLECTOR_PORT
    token: str | None = None
    allow_remote: bool = False
    max_payload_bytes: int = MAX_TRACE_BYTES
    source_platform: str | None = None
    include_sensitive: bool = False
    retention_days: int = DEFAULT_RETENTION_DAYS
    flush_interval_seconds: int = 0
    flush_limit: int = BATCH_FLUSH_LIMIT
    scan_on_flush: bool = False
    init_if_missing: bool = False
    init_objective: str | None = None
    init_criterion: str | None = None
    init_threshold: int = 66
    threshold: int | None = None
    checkpoint_stale_minutes: int = 45
    write_status_file: bool = True


@dataclass
class CollectorRuntimeState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: str = field(default_factory=utc_now)
    flush_count: int = 0
    imported_total: int = 0
    last_flush: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None


class CollectorHTTPError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _resolved_root(root: str | Path | None) -> Path:
    return project_root(str(root) if root is not None else None)


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_collector_config(config: CollectorConfig) -> None:
    if int(config.port) < 0 or int(config.port) > 65535:
        raise CollectorError("collector port must be between 0 and 65535.")
    if int(config.max_payload_bytes) < 1:
        raise CollectorError("collector max_payload_bytes must be at least 1.")
    if int(config.flush_interval_seconds) < 0:
        raise CollectorError("collector flush_interval_seconds must be zero or greater.")
    if int(config.flush_limit) < 1:
        raise CollectorError("collector flush_limit must be at least 1.")
    if int(config.init_threshold) < 1:
        raise CollectorError("collector init_threshold must be at least 1.")
    if int(config.checkpoint_stale_minutes) < 1:
        raise CollectorError("collector checkpoint_stale_minutes must be at least 1.")
    if not _is_loopback_host(config.host):
        if not config.allow_remote:
            raise CollectorError("Refusing to bind the collector to a non-loopback host without --allow-remote.")
        if not config.token:
            raise CollectorError("Remote collector binding requires --token.")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def collector_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def collector_status_path(root: str | Path | None) -> Path:
    return hulun_dir(_resolved_root(root)) / COLLECTOR_STATUS_FILE


def _content_type(headers: Any) -> str:
    raw = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    return raw


def _is_json_content_type(content_type: str) -> bool:
    return content_type in JSON_CONTENT_TYPES or content_type.endswith("+json")


def _authorized(headers: Any, token: str | None) -> bool:
    if not token:
        return True
    bearer = str(headers.get("Authorization") or "").strip()
    if bearer.lower().startswith("bearer ") and hmac.compare_digest(bearer[7:].strip(), token):
        return True
    supplied = str(headers.get("X-Hulun-Token") or "").strip()
    return hmac.compare_digest(supplied, token)


def _request_format(path: str, query: dict[str, list[str]]) -> str:
    if path == "/v1/traces":
        return "opentelemetry"
    if path == "/ingest":
        value = query.get("format", ["auto"])[0]
        source_format = str(value or "auto").strip().lower()
    elif path.startswith("/ingest/"):
        source_format = path.removeprefix("/ingest/").strip("/").lower()
    else:
        raise CollectorHTTPError(404, "not_found", "Supported endpoints are /v1/traces, /ingest, /ingest/<format>, /status, and /healthz.")
    if source_format not in TRACE_PAYLOAD_FORMATS:
        raise CollectorHTTPError(400, "unsupported_format", f"Unsupported trace format: {source_format}.")
    return source_format


def _read_request_payload(handler: BaseHTTPRequestHandler, *, max_payload_bytes: int) -> Any:
    content_type = _content_type(handler.headers)
    if "protobuf" in content_type or content_type == "application/octet-stream":
        raise CollectorHTTPError(415, "unsupported_media_type", "Only JSON OTLP/runtime payloads are accepted; protobuf OTLP is not parsed.")
    if not _is_json_content_type(content_type):
        raise CollectorHTTPError(415, "unsupported_media_type", f"Unsupported content type: {content_type}.")

    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise CollectorHTTPError(411, "length_required", "Content-Length is required.")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise CollectorHTTPError(400, "invalid_content_length", "Content-Length must be an integer.") from exc
    if length < 1:
        raise CollectorHTTPError(400, "empty_payload", "Request body must not be empty.")
    limit = max(1, int(max_payload_bytes))
    if length > limit:
        _drain_oversized_body(handler, length=length, limit=limit)
        raise CollectorHTTPError(413, "payload_too_large", f"Payload is too large: {length} bytes, limit is {limit} bytes.")
    raw = handler.rfile.read(length)
    if len(raw) > limit:
        raise CollectorHTTPError(413, "payload_too_large", f"Payload is too large: limit is {limit} bytes.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CollectorHTTPError(400, "invalid_utf8", "Request body must be UTF-8 JSON or JSONL.") from exc
    try:
        return parse_trace_text(text)
    except SystemExit as exc:
        raise CollectorHTTPError(400, "invalid_json", str(exc)) from exc


def _drain_oversized_body(handler: BaseHTTPRequestHandler, *, length: int, limit: int) -> None:
    drain_cap = min(max(limit + 65536, 1024 * 1024), OVERSIZE_DRAIN_HARD_LIMIT_BYTES)
    if length > drain_cap:
        return
    remaining = length
    while remaining > 0:
        chunk = handler.rfile.read(min(65536, remaining))
        if not chunk:
            break
        remaining -= len(chunk)


def _health_payload(config: CollectorConfig) -> dict[str, Any]:
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "healthz",
        "status": "ok",
        "endpoints": ["/v1/traces", "/ingest", "/ingest/<format>", "/status", "/healthz"],
        "formats": list(TRACE_PAYLOAD_FORMATS),
        "limits": {"max_payload_bytes": int(config.max_payload_bytes)},
        "auth_required": bool(config.token),
        "managed": {
            "enabled": int(config.flush_interval_seconds) > 0,
            "flush_interval_seconds": int(config.flush_interval_seconds),
            "scan_on_flush": bool(config.scan_on_flush),
        },
    }


def _runtime_snapshot(runtime_state: CollectorRuntimeState | None) -> dict[str, Any]:
    if runtime_state is None:
        return {
            "started_at": None,
            "flush_count": 0,
            "imported_total": 0,
            "last_flush": None,
            "last_error": None,
        }
    with runtime_state.lock:
        return {
            "started_at": runtime_state.started_at,
            "flush_count": runtime_state.flush_count,
            "imported_total": runtime_state.imported_total,
            "last_flush": runtime_state.last_flush,
            "last_error": runtime_state.last_error,
        }


def collector_status(config: CollectorConfig, runtime_state: CollectorRuntimeState | None = None) -> dict[str, Any]:
    status = queue_status(_resolved_root(config.root))
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "status",
        "root": status["root"],
        "queue": status["queue"],
        "dead_letter": status["dead_letter"],
        "server": {
            "host": config.host,
            "port": int(config.port),
            "allow_remote": bool(config.allow_remote),
            "auth_required": bool(config.token),
            "max_payload_bytes": int(config.max_payload_bytes),
        },
        "managed": {
            "enabled": int(config.flush_interval_seconds) > 0,
            "flush_interval_seconds": int(config.flush_interval_seconds),
            "flush_limit": int(config.flush_limit),
            "scan_on_flush": bool(config.scan_on_flush),
            "init_if_missing": bool(config.init_if_missing),
            "status_file": str(collector_status_path(config.root)) if config.write_status_file else None,
            "runtime": _runtime_snapshot(runtime_state),
        },
    }


def write_collector_status(config: CollectorConfig, runtime_state: CollectorRuntimeState | None = None) -> Path | None:
    if not config.write_status_file:
        return None
    path = collector_status_path(config.root)
    write_json(path, collector_status(config, runtime_state))
    return path


def _read_json_payload(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "JSON payload must be an object."
    return data, None


def _file_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _round_age(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def collector_operations_status(
    root: str | Path | None = None,
    *,
    stale_after_seconds: int = 60,
    require_status_file: bool = False,
    fail_on_stale: bool = False,
) -> dict[str, Any]:
    root_path = _resolved_root(root)
    status_file = collector_status_path(root_path)
    status_payload, status_parse_error = _read_json_payload(status_file)
    status_age = _file_age_seconds(status_file)
    stale_limit = max(1, int(stale_after_seconds))
    status_stale = bool(status_file.exists() and status_age is not None and status_age > stale_limit)

    risk_file = risk_path(root_path)
    risk_payload, risk_parse_error = _read_json_payload(risk_file)
    queue = queue_status(root_path)
    managed = status_payload.get("managed") if isinstance(status_payload, dict) else None
    runtime = managed.get("runtime") if isinstance(managed, dict) else None
    last_error = runtime.get("last_error") if isinstance(runtime, dict) else None

    failures: list[str] = []
    warnings: list[str] = []
    if int(queue["queue"].get("parse_error_count") or 0) > 0:
        failures.append(f"Queue has parse errors: {queue['queue']['parse_error_count']}.")
    if int(queue["dead_letter"].get("records") or 0) > 0:
        failures.append(f"Dead-letter records exist: {queue['dead_letter']['records']}.")
    if require_status_file and not status_file.exists():
        failures.append(f"Collector status file is missing: {status_file}.")
    if status_parse_error:
        failures.append(f"Collector status file is not valid JSON: {status_parse_error}.")
    if risk_parse_error:
        failures.append(f"Risk file is not valid JSON: {risk_parse_error}.")
    if status_stale:
        message = f"Collector status file is stale: {_round_age(status_age)}s > {stale_limit}s."
        if fail_on_stale:
            failures.append(message)
        else:
            warnings.append(message)
    if last_error:
        failures.append(f"Managed collector reported last_error: {last_error}.")
    if risk_payload and risk_payload.get("blocked"):
        warnings.append(f"HulunIndex is blocked: {risk_payload.get('score')} >= {risk_payload.get('threshold')}.")
    if not status_file.exists() and not require_status_file:
        warnings.append("Collector status file is absent; run managed collector mode to publish runtime counters.")

    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "operations_status",
        "root": str(root_path),
        "queue": queue["queue"],
        "dead_letter": queue["dead_letter"],
        "status_file": {
            "path": str(status_file),
            "exists": status_file.exists(),
            "age_seconds": _round_age(status_age),
            "stale_after_seconds": stale_limit,
            "stale": status_stale,
            "parse_error": status_parse_error,
        },
        "managed": managed,
        "risk": {
            "path": str(risk_file),
            "exists": risk_file.exists(),
            "parse_error": risk_parse_error,
            "score": risk_payload.get("score") if risk_payload else None,
            "slop_index": risk_payload.get("slop_index") if risk_payload else None,
            "band": risk_payload.get("band") if risk_payload else None,
            "blocked": risk_payload.get("blocked") if risk_payload else None,
            "required_action": risk_payload.get("required_action") if risk_payload else None,
        },
        "warnings": warnings,
        "gate": {"passed": not failures, "failure_count": len(failures), "failures": failures},
    }


def _collector_service_command(
    *,
    python_executable: str,
    root_path: Path,
    host: str,
    port: int,
    flush_interval_seconds: int,
    flush_limit: int,
    scan_on_flush: bool,
    init_if_missing: bool,
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "hulun_guard",
        "--root",
        str(root_path),
        "collector",
        "serve",
        "--host",
        host,
        "--port",
        str(int(port)),
        "--flush-interval-seconds",
        str(int(flush_interval_seconds)),
        "--flush-limit",
        str(int(flush_limit)),
    ]
    if scan_on_flush:
        command.append("--scan-on-flush")
    if init_if_missing:
        command.append("--init-if-missing")
    return command


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cmd_arg(value: str) -> str:
    if not value or any(ch.isspace() or ch in value for ch in '"&()[]{}^=;!%\',`'):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _write_template(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise CollectorError(f"Refusing to overwrite existing collector service template: {path}. Use --force.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _systemd_template(command: list[str], root_path: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=HulunGuard Collector",
            "After=network.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={shlex.quote(str(root_path))}",
            f"ExecStart={shlex.join(command)}",
            "Restart=on-failure",
            "RestartSec=5",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def _launchd_template(command: list[str], root_path: Path) -> str:
    arguments = "\n".join(f"    <string>{xml_escape(value)}</string>" for value in command)
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
            '<plist version="1.0">',
            "<dict>",
            "  <key>Label</key>",
            "  <string>dev.hulunguard.collector</string>",
            "  <key>WorkingDirectory</key>",
            f"  <string>{xml_escape(str(root_path))}</string>",
            "  <key>ProgramArguments</key>",
            "  <array>",
            arguments,
            "  </array>",
            "  <key>RunAtLoad</key>",
            "  <true/>",
            "  <key>KeepAlive</key>",
            "  <true/>",
            "</dict>",
            "</plist>",
            "",
        ]
    )


def _windows_task_template(command: list[str], root_path: Path) -> str:
    execute = command[0]
    arguments = " ".join(_cmd_arg(value) for value in command[1:])
    return "\n".join(
        [
            "$TaskName = 'HulunGuard Collector'",
            f"$Action = New-ScheduledTaskAction -Execute {_ps_literal(execute)} -Argument {_ps_literal(arguments)} -WorkingDirectory {_ps_literal(str(root_path))}",
            "$Trigger = New-ScheduledTaskTrigger -AtLogOn",
            "$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -StartWhenAvailable",
            "Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Run the local HulunGuard collector in managed mode.'",
            "",
        ]
    )


def _service_template_readme(command: list[str], targets: list[str]) -> str:
    return "\n".join(
        [
            "# HulunGuard Collector Service Templates",
            "",
            "These files are generated templates. Review paths, users, permissions, and host policy before installing them.",
            "",
            "Generated command:",
            "",
            "```text",
            shlex.join(command),
            "```",
            "",
            "Targets:",
            *[f"- {target}" for target in targets],
            "",
            "The templates do not include authentication tokens. Keep the collector bound to loopback unless the host environment provides a private network boundary and a local token.",
            "",
        ]
    )


def collector_service_templates(
    root: str | Path | None = None,
    *,
    output: str | Path | None = None,
    target: str = "all",
    python_executable: str = "python",
    host: str = DEFAULT_COLLECTOR_HOST,
    port: int = DEFAULT_COLLECTOR_PORT,
    flush_interval_seconds: int = 5,
    flush_limit: int = BATCH_FLUSH_LIMIT,
    scan_on_flush: bool = True,
    init_if_missing: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    root_path = _resolved_root(root)
    if int(flush_interval_seconds) < 1:
        raise CollectorError("collector service templates require --flush-interval-seconds >= 1.")
    if int(flush_limit) < 1:
        raise CollectorError("collector service templates require --flush-limit >= 1.")
    if not _is_loopback_host(host):
        raise CollectorError("collector service templates only generate loopback-bound commands because templates do not embed tokens.")
    targets = list(SERVICE_TEMPLATE_TARGETS) if target == "all" else [target]
    unknown = [value for value in targets if value not in SERVICE_TEMPLATE_TARGETS]
    if unknown:
        raise CollectorError(f"Unsupported collector service template target: {', '.join(unknown)}.")

    output_dir = Path(output) if output else hulun_dir(root_path) / COLLECTOR_SERVICE_TEMPLATE_DIR
    if not output_dir.is_absolute():
        output_dir = root_path / output_dir
    output_dir = output_dir.resolve()
    command = _collector_service_command(
        python_executable=python_executable,
        root_path=root_path,
        host=host,
        port=port,
        flush_interval_seconds=flush_interval_seconds,
        flush_limit=flush_limit,
        scan_on_flush=scan_on_flush,
        init_if_missing=init_if_missing,
    )
    writers = {
        "systemd": ("hulun-collector.service", _systemd_template(command, root_path)),
        "launchd": ("dev.hulunguard.collector.plist", _launchd_template(command, root_path)),
        "windows-task": ("Register-HulunCollectorTask.ps1", _windows_task_template(command, root_path)),
    }
    files: list[dict[str, str]] = []
    for template_target in targets:
        name, text = writers[template_target]
        path = output_dir / name
        _write_template(path, text, force=force)
        files.append({"target": template_target, "path": str(path)})
    readme_path = output_dir / "README.md"
    _write_template(readme_path, _service_template_readme(command, targets), force=force)
    files.append({"target": "readme", "path": str(readme_path)})
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "service_template",
        "root": str(root_path),
        "output_dir": str(output_dir),
        "target": target,
        "targets": targets,
        "command": command,
        "files": files,
        "gate": {"passed": True, "failure_count": 0, "failures": []},
    }


def _risk_markdown(risk: dict[str, Any]) -> str:
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


def _scan_after_flush(config: CollectorConfig) -> dict[str, Any]:
    root = _resolved_root(config.root)
    state = load_state(root)
    risk = scan_state(
        state,
        threshold=config.threshold,
        final_attempt=False,
        checkpoint_stale_minutes=config.checkpoint_stale_minutes,
    )
    state["last_scan"] = risk
    save_state(root, state)
    write_json(risk_path(root), risk)
    report_path = hulun_dir(root) / RISK_REPORT_FILE
    report_path.write_text(_risk_markdown(risk), encoding="utf-8")
    return risk


def _record_runtime_flush(runtime_state: CollectorRuntimeState | None, payload: dict[str, Any]) -> None:
    if runtime_state is None:
        return
    with runtime_state.lock:
        runtime_state.flush_count += 1
        runtime_state.imported_total += int(payload.get("imported") or 0)
        runtime_state.last_flush = payload
        runtime_state.last_error = None if payload.get("gate", {}).get("passed", True) else payload.get("error")


def _record_runtime_error(runtime_state: CollectorRuntimeState | None, *, code: str, message: str) -> None:
    if runtime_state is None:
        return
    with runtime_state.lock:
        runtime_state.last_error = {"code": code, "message": message, "generated_at": utc_now()}


def collector_flush_once(config: CollectorConfig, runtime_state: CollectorRuntimeState | None = None) -> dict[str, Any]:
    root = _resolved_root(config.root)
    pending_before = int(queue_status(root)["queue"]["pending"])
    payload: dict[str, Any] = {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "managed_flush",
        "root": str(root),
        "requested_limit": int(config.flush_limit),
        "pending_before": pending_before,
        "imported": 0,
        "scanned": False,
        "batch": None,
        "risk": None,
        "gate": {"passed": True, "failure_count": 0, "failures": []},
    }
    if pending_before < 1:
        payload["queue"] = queue_status(root)["queue"]
        _record_runtime_flush(runtime_state, payload)
        write_collector_status(config, runtime_state)
        return payload
    try:
        batch = flush_queue(
            root,
            limit=int(config.flush_limit),
            init_if_missing=config.init_if_missing,
            init_objective=config.init_objective,
            init_criterion=config.init_criterion,
            init_threshold=config.init_threshold,
            include_sensitive=config.include_sensitive,
            retention_days=config.retention_days,
        )
        payload["batch"] = batch
        payload["imported"] = int(batch.get("imported") or 0)
        payload["queue"] = batch["queue"]
        payload["dead_letter"] = batch["dead_letter"]
        if config.scan_on_flush and payload["imported"]:
            payload["risk"] = _scan_after_flush(config)
            payload["scanned"] = True
    except (BatchIngestError, SystemExit, OSError, ValueError) as exc:
        payload["gate"] = {"passed": False, "failure_count": 1, "failures": [str(exc)]}
        payload["error"] = {"code": "managed_flush_failed", "message": str(exc)}
        payload["queue"] = queue_status(root)["queue"]
        payload["dead_letter"] = queue_status(root)["dead_letter"]
    _record_runtime_flush(runtime_state, payload)
    write_collector_status(config, runtime_state)
    return payload


def _ingest_payload(config: CollectorConfig, *, endpoint: str, source_format: str, payload: Any) -> dict[str, Any]:
    batch = enqueue_payload(
        _resolved_root(config.root),
        payload,
        source_format=source_format,
        source_name=f"http:{endpoint}",
        source_platform=config.source_platform or source_format,
        include_sensitive=config.include_sensitive,
        retention_days=config.retention_days,
        max_payload_bytes=config.max_payload_bytes,
    )
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "ingest",
        "endpoint": endpoint,
        "format": source_format,
        "accepted": int(batch["queued"]),
        "queued": int(batch["queued"]),
        "record_ids": batch["record_ids"],
        "queue": batch["queue"],
        "dead_letter": batch["dead_letter"],
        "batch_schema": batch["schema"],
    }


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = _json_bytes(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _write_error(handler: BaseHTTPRequestHandler, exc: CollectorHTTPError) -> None:
    _write_json(
        handler,
        exc.status,
        {
            "schema": COLLECTOR_SCHEMA,
            "generated_at": utc_now(),
            "operation": "error",
            "error": {"code": exc.code, "message": exc.message},
        },
    )


@dataclass
class CollectorManager:
    stop_event: threading.Event
    thread: threading.Thread
    flush_interval_seconds: int

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(5, 2 * int(self.flush_interval_seconds or 1)))


def _flush_loop(config: CollectorConfig, runtime_state: CollectorRuntimeState, stop_event: threading.Event) -> None:
    interval = max(1, int(config.flush_interval_seconds))
    while not stop_event.wait(interval):
        try:
            collector_flush_once(config, runtime_state)
        except Exception as exc:
            _record_runtime_error(runtime_state, code="managed_loop_failed", message=str(exc))
            try:
                write_collector_status(config, runtime_state)
            except OSError:
                pass


def start_collector_manager(config: CollectorConfig, runtime_state: CollectorRuntimeState) -> CollectorManager | None:
    if int(config.flush_interval_seconds) < 1:
        return None
    stop_event = threading.Event()
    thread = threading.Thread(target=_flush_loop, args=(config, runtime_state, stop_event), name="hulun-collector-flush", daemon=True)
    thread.start()
    write_collector_status(config, runtime_state)
    return CollectorManager(stop_event=stop_event, thread=thread, flush_interval_seconds=int(config.flush_interval_seconds))


def make_collector_handler(config: CollectorConfig, runtime_state: CollectorRuntimeState | None = None) -> type[BaseHTTPRequestHandler]:
    class HulunCollectorHandler(BaseHTTPRequestHandler):
        server_version = "HulunGuardCollector/0.36"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/healthz":
                    _write_json(self, 200, _health_payload(config))
                    return
                if path == "/status":
                    if not _authorized(self.headers, config.token):
                        raise CollectorHTTPError(401, "unauthorized", "A valid HulunGuard collector token is required.")
                    _write_json(self, 200, collector_status(config, runtime_state))
                    return
                raise CollectorHTTPError(404, "not_found", "Supported GET endpoints are /healthz and /status.")
            except CollectorHTTPError as exc:
                _write_error(self, exc)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            try:
                if not _authorized(self.headers, config.token):
                    raise CollectorHTTPError(401, "unauthorized", "A valid HulunGuard collector token is required.")
                source_format = _request_format(path, query)
                payload = _read_request_payload(self, max_payload_bytes=config.max_payload_bytes)
                report = _ingest_payload(config, endpoint=path, source_format=source_format, payload=payload)
                _write_json(self, 202, report)
            except CollectorHTTPError as exc:
                _write_error(self, exc)
            except BatchIngestError as exc:
                _write_error(self, CollectorHTTPError(400, "ingest_failed", str(exc)))

        def do_PUT(self) -> None:
            _write_error(self, CollectorHTTPError(405, "method_not_allowed", "Use POST for ingestion."))

        def do_PATCH(self) -> None:
            _write_error(self, CollectorHTTPError(405, "method_not_allowed", "Use POST for ingestion."))

        def do_DELETE(self) -> None:
            _write_error(self, CollectorHTTPError(405, "method_not_allowed", "Use POST for ingestion."))

    return HulunCollectorHandler


def build_collector_server(config: CollectorConfig, runtime_state: CollectorRuntimeState | None = None) -> ThreadingHTTPServer:
    validate_collector_config(config)
    handler = make_collector_handler(config, runtime_state)
    return ThreadingHTTPServer((config.host, int(config.port)), handler)


def serve_collector(config: CollectorConfig) -> None:
    runtime_state = CollectorRuntimeState()
    server = build_collector_server(config, runtime_state)
    manager = start_collector_manager(config, runtime_state)
    try:
        server.serve_forever()
    finally:
        if manager:
            manager.stop()
        server.server_close()


def _smoke_payload() -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "scope": {"name": "hulun_guard.collector.smoke", "version": "0.36"},
                        "spans": [
                            {
                                "traceId": "11111111111111111111111111111111",
                                "spanId": "2222222222222222",
                                "name": "hulun.collector.smoke",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000100000000",
                                "attributes": [
                                    {"key": "hulun.event.type", "value": {"stringValue": "tool_result"}},
                                    {"key": "hulun.event.phase", "value": {"stringValue": "verify"}},
                                    {"key": "hulun.event.summary", "value": {"stringValue": "collector smoke accepted OTLP JSON"}},
                                    {"key": "hulun.event.evidence", "value": {"stringValue": "collector-smoke"}},
                                    {"key": "hulun.action_key", "value": {"stringValue": "collector-smoke"}},
                                    {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "8"}},
                                    {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "5"}},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }


def _post_json(url: str, payload: dict[str, Any], *, token: str | None) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    parsed = urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise CollectorError(f"collector smoke requires a local http URL, got {url}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        return int(response.status), body
    finally:
        connection.close()


def collector_smoke(
    root: str | Path | None = None,
    *,
    token: str | None = None,
    max_payload_bytes: int = MAX_TRACE_BYTES,
    managed: bool = False,
    scan: bool = False,
    init_if_missing: bool = False,
) -> dict[str, Any]:
    if root is None:
        with tempfile.TemporaryDirectory(prefix="hulun-collector-smoke-") as tmp:
            return collector_smoke(tmp, token=token, max_payload_bytes=max_payload_bytes, managed=managed, scan=scan, init_if_missing=init_if_missing)

    root_path = _resolved_root(root)
    before = queue_status(root_path)
    config = CollectorConfig(
        root=root_path,
        host=DEFAULT_COLLECTOR_HOST,
        port=0,
        token=token,
        max_payload_bytes=max_payload_bytes,
        flush_interval_seconds=0,
        scan_on_flush=scan,
        init_if_missing=init_if_missing,
        init_objective="Monitor managed collector runtime reliability",
        init_criterion="Managed collector imports live traces into the project ledger.",
    )
    runtime_state = CollectorRuntimeState()
    server = build_collector_server(config, runtime_state)
    thread = threading.Thread(target=server.serve_forever, name="hulun-collector-smoke", daemon=True)
    thread.start()
    response_status = 0
    response_body: dict[str, Any] = {}
    managed_flush: dict[str, Any] | None = None
    failures: list[str] = []
    try:
        host, port = server.server_address[:2]
        response_status, response_body = _post_json(f"http://{host}:{port}/v1/traces", _smoke_payload(), token=token)
        if managed:
            managed_flush = collector_flush_once(config, runtime_state)
    except (OSError, TimeoutError, http.client.HTTPException, json.JSONDecodeError) as exc:
        failures.append(str(exc))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    after = queue_status(root_path)
    if response_status != 202:
        failures.append(f"expected HTTP 202, got {response_status}")
    if int(response_body.get("queued") or 0) != 1:
        failures.append("collector response did not queue exactly one observation")
    if managed:
        if not managed_flush or not managed_flush.get("gate", {}).get("passed"):
            failures.append("managed collector flush did not pass")
        expected_pending = int((managed_flush or {}).get("queue", {}).get("pending") or 0)
        if int(after["queue"]["pending"]) != expected_pending:
            failures.append(f"expected managed pending queue {expected_pending}, got {after['queue']['pending']}")
        if scan and not (managed_flush or {}).get("risk"):
            failures.append("managed collector smoke expected a risk scan")
    else:
        expected_pending = int(before["queue"]["pending"]) + 1
        if int(after["queue"]["pending"]) != expected_pending:
            failures.append(f"expected pending queue {expected_pending}, got {after['queue']['pending']}")
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "smoke",
        "root": str(root_path),
        "endpoint": "/v1/traces",
        "managed": managed,
        "response_status": response_status,
        "response": response_body,
        "managed_flush": managed_flush,
        "queue_before": before["queue"],
        "queue": after["queue"],
        "dead_letter": after["dead_letter"],
        "gate": {"passed": not failures, "failure_count": len(failures), "failures": failures},
    }
