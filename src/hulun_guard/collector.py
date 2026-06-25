from __future__ import annotations

import hmac
import http.client
import json
import shlex
import signal
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
from .util import parse_time, utc_now

DEFAULT_COLLECTOR_HOST = "127.0.0.1"
DEFAULT_COLLECTOR_PORT = 4318
COLLECTOR_STATUS_FILE = "collector_status.json"
COLLECTOR_SERVICE_TEMPLATE_DIR = "collector-service"
COLLECTOR_SERVICE_LIFECYCLE_DIR = "collector-service-lifecycle"
COLLECTOR_ALERT_RULE_DIR = "collector-alerts"
COLLECTOR_ALERT_RULE_FILE = "hulunguard-collector.rules.yml"
SERVICE_TEMPLATE_TARGETS = ("systemd", "launchd", "windows-task")
SERVICE_LIFECYCLE_ACTIONS = ("install", "start", "stop", "restart", "status", "uninstall")
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
    lifecycle_state: str = "running"
    stopping_at: str | None = None
    stopped_at: str | None = None
    stop_reason: str | None = None
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
        raise CollectorHTTPError(404, "not_found", "Supported endpoints are /v1/traces, /ingest, /ingest/<format>, /status, /metrics, and /healthz.")
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
        "endpoints": ["/v1/traces", "/ingest", "/ingest/<format>", "/status", "/metrics", "/healthz"],
        "formats": list(TRACE_PAYLOAD_FORMATS),
        "limits": {"max_payload_bytes": int(config.max_payload_bytes)},
        "auth_required": bool(config.token),
        "managed": {
            "enabled": int(config.flush_interval_seconds) > 0,
            "flush_interval_seconds": int(config.flush_interval_seconds),
            "scan_on_flush": bool(config.scan_on_flush),
        },
    }


def _elapsed_seconds(started_at: str | None, ended_at: str | None = None) -> float | None:
    start = parse_time(started_at)
    end = parse_time(ended_at) or parse_time(utc_now())
    if not start or not end:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=end.tzinfo)
    return round(max(0.0, (end - start).total_seconds()), 3)


def _runtime_snapshot(runtime_state: CollectorRuntimeState | None) -> dict[str, Any]:
    if runtime_state is None:
        return {
            "lifecycle_state": "unknown",
            "started_at": None,
            "stopping_at": None,
            "stopped_at": None,
            "stop_reason": None,
            "uptime_seconds": None,
            "flush_count": 0,
            "imported_total": 0,
            "last_flush": None,
            "last_error": None,
        }
    with runtime_state.lock:
        uptime_end = runtime_state.stopped_at if runtime_state.lifecycle_state == "stopped" else None
        return {
            "lifecycle_state": runtime_state.lifecycle_state,
            "started_at": runtime_state.started_at,
            "stopping_at": runtime_state.stopping_at,
            "stopped_at": runtime_state.stopped_at,
            "stop_reason": runtime_state.stop_reason,
            "uptime_seconds": _elapsed_seconds(runtime_state.started_at, uptime_end),
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
    live_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = _resolved_root(root)
    status_file = collector_status_path(root_path)
    status_payload, status_parse_error = (live_status, None) if isinstance(live_status, dict) else _read_json_payload(status_file)
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
    if not status_file.exists() and not require_status_file and live_status is None:
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
            "source": "runtime" if live_status is not None else "file",
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


PROMETHEUS_METRIC_HELP = {
    "hulun_collector_up": "Collector operations gate status, 1 when passing.",
    "hulun_collector_gate_failures": "Number of collector operations gate failures.",
    "hulun_collector_warnings": "Number of collector operations warnings.",
    "hulun_collector_queue_pending": "Pending observations in the collector ingest queue.",
    "hulun_collector_queue_bytes": "Bytes currently stored in the collector ingest queue.",
    "hulun_collector_queue_parse_errors_total": "Malformed records detected while reading the collector ingest queue.",
    "hulun_collector_dead_letter_records": "Records currently stored in the collector ingest dead-letter queue.",
    "hulun_collector_status_file_present": "Collector managed status file presence, 1 when present.",
    "hulun_collector_status_file_stale": "Collector managed status stale flag, 1 when stale.",
    "hulun_collector_status_file_age_seconds": "Collector managed status file age in seconds.",
    "hulun_collector_managed_enabled": "Managed flush mode flag, 1 when enabled.",
    "hulun_collector_managed_flush_total": "Managed collector flush count.",
    "hulun_collector_managed_imported_total": "Total observations imported by managed collector flushes.",
    "hulun_collector_managed_last_error": "Managed collector runtime error flag, 1 when the last flush recorded an error.",
    "hulun_collector_runtime_uptime_seconds": "Collector runtime uptime in seconds.",
    "hulun_collector_runtime_state": "Collector runtime lifecycle state as one-hot labelled gauges.",
    "hulun_collector_risk_present": "Latest HulunIndex risk file presence, 1 when present.",
    "hulun_collector_risk_score": "Latest HulunIndex risk score.",
    "hulun_collector_risk_blocked": "Latest HulunIndex blocked flag, 1 when blocked.",
    "hulun_collector_risk_band": "Latest HulunIndex band as one-hot labelled gauges.",
}


def _metric_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        label_text = ",".join(f'{key}="{_metric_label(str(label_value))}"' for key, label_value in sorted(labels.items()))
        return f"{name}{{{label_text}}} {value:g}"
    return f"{name} {value:g}"


def collector_metrics_from_status(status: dict[str, Any]) -> list[dict[str, Any]]:
    gate = status.get("gate") if isinstance(status.get("gate"), dict) else {}
    queue = status.get("queue") if isinstance(status.get("queue"), dict) else {}
    dead_letter = status.get("dead_letter") if isinstance(status.get("dead_letter"), dict) else {}
    status_file = status.get("status_file") if isinstance(status.get("status_file"), dict) else {}
    managed = status.get("managed") if isinstance(status.get("managed"), dict) else {}
    runtime = managed.get("runtime") if isinstance(managed.get("runtime"), dict) else {}
    risk = status.get("risk") if isinstance(status.get("risk"), dict) else {}
    metrics: list[dict[str, Any]] = [
        {"name": "hulun_collector_up", "value": 1.0 if gate.get("passed") else 0.0},
        {"name": "hulun_collector_gate_failures", "value": _metric_number(gate.get("failure_count"))},
        {"name": "hulun_collector_warnings", "value": _metric_number(len(status.get("warnings") or []))},
        {"name": "hulun_collector_queue_pending", "value": _metric_number(queue.get("pending"))},
        {"name": "hulun_collector_queue_bytes", "value": _metric_number(queue.get("bytes"))},
        {"name": "hulun_collector_queue_parse_errors_total", "value": _metric_number(queue.get("parse_error_count"))},
        {"name": "hulun_collector_dead_letter_records", "value": _metric_number(dead_letter.get("records"))},
        {"name": "hulun_collector_status_file_present", "value": _metric_number(status_file.get("exists"))},
        {"name": "hulun_collector_status_file_stale", "value": _metric_number(status_file.get("stale"))},
        {"name": "hulun_collector_managed_enabled", "value": _metric_number(managed.get("enabled"))},
        {"name": "hulun_collector_managed_flush_total", "value": _metric_number(runtime.get("flush_count"))},
        {"name": "hulun_collector_managed_imported_total", "value": _metric_number(runtime.get("imported_total"))},
        {"name": "hulun_collector_managed_last_error", "value": 1.0 if runtime.get("last_error") else 0.0},
        {"name": "hulun_collector_runtime_uptime_seconds", "value": _metric_number(runtime.get("uptime_seconds"))},
        {"name": "hulun_collector_risk_present", "value": _metric_number(risk.get("exists"))},
        {"name": "hulun_collector_risk_blocked", "value": _metric_number(risk.get("blocked"))},
    ]
    active_state = str(runtime.get("lifecycle_state") or "unknown")
    for lifecycle_state in ("running", "stopping", "stopped", "unknown"):
        metrics.append({"name": "hulun_collector_runtime_state", "value": 1.0 if lifecycle_state == active_state else 0.0, "labels": {"state": lifecycle_state}})
    if status_file.get("age_seconds") is not None:
        metrics.append({"name": "hulun_collector_status_file_age_seconds", "value": _metric_number(status_file.get("age_seconds"))})
    if risk.get("score") is not None:
        metrics.append({"name": "hulun_collector_risk_score", "value": _metric_number(risk.get("score"))})
    active_band = str(risk.get("band") or "unknown")
    for band in ("green", "yellow", "red", "unknown"):
        metrics.append({"name": "hulun_collector_risk_band", "value": 1.0 if band == active_band else 0.0, "labels": {"band": band}})
    return metrics


def collector_metrics_text(metrics: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    emitted: set[str] = set()
    for metric in metrics:
        name = str(metric["name"])
        if name not in emitted:
            lines.append(f"# HELP {name} {PROMETHEUS_METRIC_HELP.get(name, 'HulunGuard collector metric.')}")
            lines.append(f"# TYPE {name} gauge")
            emitted.add(name)
        lines.append(_metric_line(name, _metric_number(metric.get("value")), metric.get("labels") if isinstance(metric.get("labels"), dict) else None))
    return "\n".join(lines) + "\n"


def collector_metrics_report(
    root: str | Path | None = None,
    *,
    stale_after_seconds: int = 60,
    require_status_file: bool = False,
    fail_on_stale: bool = False,
    live_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = collector_operations_status(
        root,
        stale_after_seconds=stale_after_seconds,
        require_status_file=require_status_file,
        fail_on_stale=fail_on_stale,
        live_status=live_status,
    )
    metrics = collector_metrics_from_status(status)
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "metrics",
        "root": status["root"],
        "format": "prometheus",
        "metrics": metrics,
        "text": collector_metrics_text(metrics),
        "status": status,
        "gate": status["gate"],
    }


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if value is None:
        return "null"
    return json.dumps(str(value), ensure_ascii=False)


def _alert_rules_yaml(group_name: str, rules: list[dict[str, Any]]) -> str:
    lines = ["groups:", f"  - name: {_yaml_scalar(group_name)}", "    rules:"]
    for rule in rules:
        lines.append(f"      - alert: {_yaml_scalar(rule['alert'])}")
        lines.append(f"        expr: {_yaml_scalar(rule['expr'])}")
        lines.append(f"        for: {_yaml_scalar(rule['for'])}")
        labels = rule.get("labels") if isinstance(rule.get("labels"), dict) else {}
        if labels:
            lines.append("        labels:")
            for key, value in sorted(labels.items()):
                lines.append(f"          {key}: {_yaml_scalar(value)}")
        annotations = rule.get("annotations") if isinstance(rule.get("annotations"), dict) else {}
        if annotations:
            lines.append("        annotations:")
            for key, value in sorted(annotations.items()):
                lines.append(f"          {key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _collector_alert_rule(
    *,
    alert: str,
    expr: str,
    duration: str,
    severity: str,
    summary: str,
    description: str,
) -> dict[str, Any]:
    return {
        "alert": alert,
        "expr": expr,
        "for": duration,
        "labels": {"hulun_component": "collector", "severity": severity},
        "annotations": {"description": description, "summary": summary},
    }


def _collector_alert_rules(
    *,
    queue_pending_threshold: int,
    status_stale_seconds: int,
    risk_red_threshold: int,
    dead_letter_threshold: int,
    include_warning_alerts: bool,
) -> list[dict[str, Any]]:
    rules = [
        _collector_alert_rule(
            alert="HulunCollectorGateFailing",
            expr="hulun_collector_up == 0",
            duration="1m",
            severity="critical",
            summary="HulunGuard collector operations gate is failing",
            description="The collector status gate reports one or more failed runtime, queue, status, or risk checks.",
        ),
        _collector_alert_rule(
            alert="HulunCollectorRuntimeError",
            expr="hulun_collector_managed_last_error == 1",
            duration="1m",
            severity="critical",
            summary="HulunGuard managed collector recorded a runtime error",
            description="The managed flush loop recorded an error during its latest collector cycle.",
        ),
        _collector_alert_rule(
            alert="HulunCollectorStatusMissing",
            expr="hulun_collector_status_file_present == 0",
            duration="2m",
            severity="warning",
            summary="HulunGuard collector status file is missing",
            description="Managed collector status is absent, so external monitors may not see fresh runtime counters.",
        ),
        _collector_alert_rule(
            alert="HulunCollectorStatusStale",
            expr=f"hulun_collector_status_file_stale == 1 or hulun_collector_status_file_age_seconds > {int(status_stale_seconds)}",
            duration="2m",
            severity="warning",
            summary="HulunGuard collector status is stale",
            description="Managed collector status has not refreshed within the configured freshness window.",
        ),
        _collector_alert_rule(
            alert="HulunCollectorDeadLetters",
            expr=f"hulun_collector_dead_letter_records > {int(dead_letter_threshold)}",
            duration="1m",
            severity="warning",
            summary="HulunGuard collector has dead-lettered records",
            description="One or more queued collector records could not be imported and require operator review.",
        ),
        _collector_alert_rule(
            alert="HulunCollectorQueueBacklog",
            expr=f"hulun_collector_queue_pending > {int(queue_pending_threshold)}",
            duration="5m",
            severity="warning",
            summary="HulunGuard collector queue backlog is growing",
            description="Pending collector observations exceed the configured queue threshold.",
        ),
        _collector_alert_rule(
            alert="HulunIndexBlocked",
            expr="hulun_collector_risk_blocked == 1",
            duration="1m",
            severity="critical",
            summary="HulunGuard blocked the current agent state",
            description="The latest HulunIndex risk report requires intervention before the monitored agent continues.",
        ),
        _collector_alert_rule(
            alert="HulunIndexRed",
            expr=f"hulun_collector_risk_score >= {int(risk_red_threshold)}",
            duration="5m",
            severity="warning",
            summary="HulunGuard risk score is red",
            description="The latest HulunIndex risk score is at or above the configured red-band threshold.",
        ),
    ]
    if include_warning_alerts:
        rules.append(
            _collector_alert_rule(
                alert="HulunCollectorWarnings",
                expr="hulun_collector_warnings > 0",
                duration="5m",
                severity="info",
                summary="HulunGuard collector has advisory warnings",
                description="The collector status report includes non-fatal warnings that may affect operations visibility.",
            )
        )
    return rules


def _alert_rules_readme(rule_file: str, group_name: str, rule_count: int) -> str:
    return "\n".join(
        [
            "# HulunGuard Collector Alert Rules",
            "",
            "This directory contains generated Prometheus alerting rules for HulunGuard collector metrics.",
            "",
            "Files:",
            f"- `{rule_file}`: Prometheus rule group `{group_name}` with {rule_count} alerts.",
            "",
            "Check the rules before deployment:",
            "",
            "```text",
            f"promtool check rules {rule_file}",
            "```",
            "",
            "The generator writes files only. It does not install Prometheus rules, change Alertmanager routing, or embed local paths or authentication tokens.",
            "",
        ]
    )


def _ensure_alert_rule_paths_writable(paths: list[Path], *, force: bool) -> None:
    if force:
        return
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise CollectorError(f"Refusing to overwrite existing collector alert rule files: {', '.join(existing)}. Use --force.")


def _write_alert_rule_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def collector_alert_rules(
    root: str | Path | None = None,
    *,
    output: str | Path | None = None,
    group_name: str = "hulunguard-collector",
    queue_pending_threshold: int = 100,
    status_stale_seconds: int = 120,
    risk_red_threshold: int = 66,
    dead_letter_threshold: int = 0,
    include_warning_alerts: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    root_path = _resolved_root(root)
    group_name = str(group_name or "").strip()
    if not group_name:
        raise CollectorError("collector alert rules require a non-empty --group-name.")
    if int(queue_pending_threshold) < 0:
        raise CollectorError("collector alert rules require --queue-pending-threshold >= 0.")
    if int(status_stale_seconds) < 1:
        raise CollectorError("collector alert rules require --status-stale-seconds >= 1.")
    if int(risk_red_threshold) < 1 or int(risk_red_threshold) > 100:
        raise CollectorError("collector alert rules require --risk-red-threshold between 1 and 100.")
    if int(dead_letter_threshold) < 0:
        raise CollectorError("collector alert rules require --dead-letter-threshold >= 0.")

    output_dir = Path(output) if output else hulun_dir(root_path) / COLLECTOR_ALERT_RULE_DIR
    if not output_dir.is_absolute():
        output_dir = root_path / output_dir
    output_dir = output_dir.resolve()
    rule_path = output_dir / COLLECTOR_ALERT_RULE_FILE
    readme_path = output_dir / "README.md"
    rules = _collector_alert_rules(
        queue_pending_threshold=int(queue_pending_threshold),
        status_stale_seconds=int(status_stale_seconds),
        risk_red_threshold=int(risk_red_threshold),
        dead_letter_threshold=int(dead_letter_threshold),
        include_warning_alerts=include_warning_alerts,
    )
    rule_text = _alert_rules_yaml(group_name, rules)
    readme_text = _alert_rules_readme(COLLECTOR_ALERT_RULE_FILE, group_name, len(rules))
    _ensure_alert_rule_paths_writable([rule_path, readme_path], force=force)
    _write_alert_rule_file(rule_path, rule_text)
    _write_alert_rule_file(readme_path, readme_text)
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "alert_rules",
        "root": str(root_path),
        "format": "prometheus-rule-yaml",
        "output_dir": str(output_dir),
        "group_name": group_name,
        "rule_count": len(rules),
        "thresholds": {
            "queue_pending": int(queue_pending_threshold),
            "status_stale_seconds": int(status_stale_seconds),
            "risk_red": int(risk_red_threshold),
            "dead_letter_records": int(dead_letter_threshold),
        },
        "include_warning_alerts": include_warning_alerts,
        "rules": rules,
        "text": rule_text,
        "files": [
            {"target": "prometheus_rules", "path": str(rule_path)},
            {"target": "readme", "path": str(readme_path)},
        ],
        "gate": {"passed": True, "failure_count": 0, "failures": []},
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


def _selected_service_targets(target: str) -> list[str]:
    targets = list(SERVICE_TEMPLATE_TARGETS) if target == "all" else [target]
    unknown = [value for value in targets if value not in SERVICE_TEMPLATE_TARGETS]
    if unknown:
        raise CollectorError(f"Unsupported collector service target: {', '.join(unknown)}.")
    return targets


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
    targets = _selected_service_targets(target)

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


def _systemd_lifecycle_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "set -eu",
            'SERVICE_NAME="hulun-collector.service"',
            'SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
            'SOURCE_UNIT="$SOURCE_DIR/hulun-collector.service"',
            'TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"',
            'TARGET_UNIT="$TARGET_DIR/$SERVICE_NAME"',
            'ACTION="${1:-status}"',
            "",
            "case \"$ACTION\" in",
            "  install)",
            '    mkdir -p "$TARGET_DIR"',
            '    cp "$SOURCE_UNIT" "$TARGET_UNIT"',
            "    systemctl --user daemon-reload",
            '    systemctl --user enable "$SERVICE_NAME"',
            '    systemctl --user start "$SERVICE_NAME"',
            "    ;;",
            "  start)",
            '    systemctl --user start "$SERVICE_NAME"',
            "    ;;",
            "  stop)",
            '    systemctl --user stop "$SERVICE_NAME"',
            "    ;;",
            "  restart)",
            '    systemctl --user restart "$SERVICE_NAME"',
            "    ;;",
            "  status)",
            '    systemctl --user status "$SERVICE_NAME"',
            "    ;;",
            "  uninstall)",
            '    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true',
            '    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true',
            '    rm -f "$TARGET_UNIT"',
            "    systemctl --user daemon-reload",
            "    ;;",
            "  *)",
            '    echo "Usage: $0 {install|start|stop|restart|status|uninstall}" >&2',
            "    exit 2",
            "    ;;",
            "esac",
            "",
        ]
    )


def _launchd_lifecycle_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "set -eu",
            'LABEL="dev.hulunguard.collector"',
            'SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
            'SOURCE_PLIST="$SOURCE_DIR/dev.hulunguard.collector.plist"',
            'TARGET_DIR="$HOME/Library/LaunchAgents"',
            'TARGET_PLIST="$TARGET_DIR/$LABEL.plist"',
            'DOMAIN="gui/$(id -u)"',
            'ACTION="${1:-status}"',
            "",
            "case \"$ACTION\" in",
            "  install)",
            '    mkdir -p "$TARGET_DIR"',
            '    cp "$SOURCE_PLIST" "$TARGET_PLIST"',
            '    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true',
            '    launchctl bootstrap "$DOMAIN" "$TARGET_PLIST"',
            '    launchctl kickstart -k "$DOMAIN/$LABEL"',
            "    ;;",
            "  start)",
            '    launchctl kickstart -k "$DOMAIN/$LABEL"',
            "    ;;",
            "  stop)",
            '    launchctl kill TERM "$DOMAIN/$LABEL"',
            "    ;;",
            "  restart)",
            '    launchctl kill TERM "$DOMAIN/$LABEL" 2>/dev/null || true',
            '    launchctl kickstart -k "$DOMAIN/$LABEL"',
            "    ;;",
            "  status)",
            '    launchctl print "$DOMAIN/$LABEL"',
            "    ;;",
            "  uninstall)",
            '    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true',
            '    rm -f "$TARGET_PLIST"',
            "    ;;",
            "  *)",
            '    echo "Usage: $0 {install|start|stop|restart|status|uninstall}" >&2',
            "    exit 2",
            "    ;;",
            "esac",
            "",
        ]
    )


def _windows_lifecycle_script(command: list[str], root_path: Path) -> str:
    execute = command[0]
    arguments = " ".join(_cmd_arg(value) for value in command[1:])
    return "\n".join(
        [
            "param(",
            "  [ValidateSet('install','start','stop','restart','status','uninstall')]",
            "  [string]$Action = 'status',",
            "  [switch]$Force",
            ")",
            "$ErrorActionPreference = 'Stop'",
            "$TaskName = 'HulunGuard Collector'",
            f"$Execute = {_ps_literal(execute)}",
            f"$Arguments = {_ps_literal(arguments)}",
            f"$WorkingDirectory = {_ps_literal(str(root_path))}",
            "",
            "function Get-HulunTask {",
            "  Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue",
            "}",
            "",
            "function Install-HulunTask {",
            "  $Existing = Get-HulunTask",
            "  if ($Existing -and -not $Force) {",
            "    throw \"Scheduled task '$TaskName' already exists. Re-run with -Force to replace it.\"",
            "  }",
            "  if ($Existing) {",
            "    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false",
            "  }",
            "  $ActionDef = New-ScheduledTaskAction -Execute $Execute -Argument $Arguments -WorkingDirectory $WorkingDirectory",
            "  $Trigger = New-ScheduledTaskTrigger -AtLogOn",
            "  $Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -StartWhenAvailable",
            "  Register-ScheduledTask -TaskName $TaskName -Action $ActionDef -Trigger $Trigger -Settings $Settings -Description 'Run the local HulunGuard collector in managed mode.' | Out-Null",
            "  Start-ScheduledTask -TaskName $TaskName",
            "}",
            "",
            "switch ($Action) {",
            "  'install' { Install-HulunTask }",
            "  'start' { Start-ScheduledTask -TaskName $TaskName }",
            "  'stop' { Stop-ScheduledTask -TaskName $TaskName }",
            "  'restart' { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName $TaskName }",
            "  'status' { Get-ScheduledTask -TaskName $TaskName | Format-List TaskName,State,TaskPath }",
            "  'uninstall' { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }",
            "}",
            "",
        ]
    )


def _service_lifecycle_readme(command: list[str], targets: list[str]) -> str:
    return "\n".join(
        [
            "# HulunGuard Collector Service Lifecycle",
            "",
            "These files provide reviewed lifecycle controls for running HulunGuard collector as a local managed service.",
            "",
            "Generated command:",
            "",
            "```text",
            shlex.join(command),
            "```",
            "",
            "Actions:",
            *[f"- `{action}`" for action in SERVICE_LIFECYCLE_ACTIONS],
            "",
            "Targets:",
            *[f"- {target}" for target in targets],
            "",
            "The lifecycle scripts do not embed authentication tokens and keep the collector bound to loopback. Review paths, users, privileges, and host policy before running an install action.",
            "",
        ]
    )


def collector_service_lifecycle(
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
        raise CollectorError("collector service lifecycle requires --flush-interval-seconds >= 1.")
    if int(flush_limit) < 1:
        raise CollectorError("collector service lifecycle requires --flush-limit >= 1.")
    if not _is_loopback_host(host):
        raise CollectorError("collector service lifecycle only generates loopback-bound commands because lifecycle scripts do not embed tokens.")
    targets = _selected_service_targets(target)
    output_dir = Path(output) if output else hulun_dir(root_path) / COLLECTOR_SERVICE_LIFECYCLE_DIR
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
        "systemd": [
            ("systemd/hulun-collector.service", _systemd_template(command, root_path), "service"),
            ("systemd/hulun-collector-systemd.sh", _systemd_lifecycle_script(), "lifecycle"),
        ],
        "launchd": [
            ("launchd/dev.hulunguard.collector.plist", _launchd_template(command, root_path), "service"),
            ("launchd/hulun-collector-launchd.sh", _launchd_lifecycle_script(), "lifecycle"),
        ],
        "windows-task": [
            ("windows-task/Register-HulunCollectorLifecycle.ps1", _windows_lifecycle_script(command, root_path), "lifecycle"),
        ],
    }
    files: list[dict[str, str]] = []
    for template_target in targets:
        for relative_path, text, role in writers[template_target]:
            path = output_dir / relative_path
            _write_template(path, text, force=force)
            files.append({"target": template_target, "role": role, "path": str(path)})
    readme_path = output_dir / "README.md"
    _write_template(readme_path, _service_lifecycle_readme(command, targets), force=force)
    files.append({"target": "readme", "role": "readme", "path": str(readme_path)})
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "service_lifecycle",
        "root": str(root_path),
        "output_dir": str(output_dir),
        "target": target,
        "targets": targets,
        "actions": list(SERVICE_LIFECYCLE_ACTIONS),
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


def _mark_runtime_stopping(runtime_state: CollectorRuntimeState | None, *, reason: str) -> None:
    if runtime_state is None:
        return
    with runtime_state.lock:
        if runtime_state.lifecycle_state != "stopped":
            runtime_state.lifecycle_state = "stopping"
        runtime_state.stop_reason = runtime_state.stop_reason or reason
        runtime_state.stopping_at = runtime_state.stopping_at or utc_now()


def _mark_runtime_stopped(runtime_state: CollectorRuntimeState | None, *, reason: str) -> None:
    if runtime_state is None:
        return
    with runtime_state.lock:
        runtime_state.lifecycle_state = "stopped"
        runtime_state.stop_reason = runtime_state.stop_reason or reason
        runtime_state.stopping_at = runtime_state.stopping_at or utc_now()
        runtime_state.stopped_at = runtime_state.stopped_at or utc_now()


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


def _write_text(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
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
                if path == "/metrics":
                    if not _authorized(self.headers, config.token):
                        raise CollectorHTTPError(401, "unauthorized", "A valid HulunGuard collector token is required.")
                    live_status = collector_status(config, runtime_state)
                    metrics = collector_metrics_report(config.root, live_status=live_status)
                    _write_text(self, 200, metrics["text"], "text/plain; version=0.0.4; charset=utf-8")
                    return
                raise CollectorHTTPError(404, "not_found", "Supported GET endpoints are /healthz, /status, and /metrics.")
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


def request_collector_shutdown(config: CollectorConfig, runtime_state: CollectorRuntimeState, server: ThreadingHTTPServer, *, reason: str) -> None:
    _mark_runtime_stopping(runtime_state, reason=reason)
    try:
        write_collector_status(config, runtime_state)
    except OSError:
        pass
    threading.Thread(target=server.shutdown, name="hulun-collector-shutdown", daemon=True).start()


def _request_server_shutdown(server: ThreadingHTTPServer, *, timeout_seconds: float) -> bool:
    thread = threading.Thread(target=server.shutdown, name="hulun-collector-shutdown", daemon=True)
    thread.start()
    thread.join(timeout=max(0.1, float(timeout_seconds)))
    return not thread.is_alive()


def _close_collector_runtime(
    config: CollectorConfig,
    runtime_state: CollectorRuntimeState,
    server: ThreadingHTTPServer,
    manager: CollectorManager | None,
    *,
    reason: str,
    request_shutdown: bool = False,
    serve_thread: threading.Thread | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    _mark_runtime_stopping(runtime_state, reason=reason)
    try:
        write_collector_status(config, runtime_state)
    except OSError:
        pass
    shutdown_completed = True
    if request_shutdown:
        if serve_thread is not None and not serve_thread.is_alive():
            shutdown_completed = True
        else:
            shutdown_completed = _request_server_shutdown(server, timeout_seconds=timeout_seconds)
    if serve_thread:
        serve_thread.join(timeout=max(0.1, float(timeout_seconds)))
    if manager:
        manager.stop()
    server.server_close()
    _mark_runtime_stopped(runtime_state, reason=reason)
    status_path = write_collector_status(config, runtime_state)
    runtime = _runtime_snapshot(runtime_state)
    failures: list[str] = []
    if request_shutdown and not shutdown_completed:
        failures.append("collector server shutdown request did not finish before timeout.")
    if serve_thread and serve_thread.is_alive():
        failures.append("collector serve thread did not stop before timeout.")
    if runtime.get("lifecycle_state") != "stopped":
        failures.append(f"expected runtime lifecycle_state stopped, got {runtime.get('lifecycle_state')}.")
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "shutdown",
        "root": str(_resolved_root(config.root)),
        "reason": runtime.get("stop_reason") or reason,
        "status_file": str(status_path) if status_path else None,
        "runtime": runtime,
        "server": {"shutdown_requested": bool(request_shutdown), "shutdown_completed": bool(shutdown_completed)},
        "manager": {"enabled": manager is not None, "stopped": manager is None or not manager.thread.is_alive()},
        "serve_thread": {"provided": serve_thread is not None, "stopped": serve_thread is None or not serve_thread.is_alive()},
        "gate": {"passed": not failures, "failure_count": len(failures), "failures": failures},
    }


def _install_collector_signal_handlers(config: CollectorConfig, runtime_state: CollectorRuntimeState, server: ThreadingHTTPServer) -> dict[int, Any]:
    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: dict[int, Any] = {}
    for signal_name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        previous[signum] = signal.getsignal(signum)

        def _handler(_signum: int, _frame: Any, *, reason: str = f"signal:{signal_name.lower()}") -> None:
            request_collector_shutdown(config, runtime_state, server, reason=reason)

        signal.signal(signum, _handler)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def serve_collector(config: CollectorConfig) -> None:
    runtime_state = CollectorRuntimeState()
    server = build_collector_server(config, runtime_state)
    manager = start_collector_manager(config, runtime_state)
    previous_handlers = _install_collector_signal_handlers(config, runtime_state, server)
    try:
        write_collector_status(config, runtime_state)
        server.serve_forever()
    finally:
        _restore_signal_handlers(previous_handlers)
        _close_collector_runtime(
            config,
            runtime_state,
            server,
            manager,
            reason=runtime_state.stop_reason or "serve_exit",
            request_shutdown=False,
        )


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


def collector_shutdown_check(
    root: str | Path | None = None,
    *,
    token: str | None = None,
    max_payload_bytes: int = MAX_TRACE_BYTES,
    managed: bool = True,
    scan: bool = False,
    init_if_missing: bool = True,
) -> dict[str, Any]:
    if root is None:
        with tempfile.TemporaryDirectory(prefix="hulun-collector-shutdown-") as tmp:
            return collector_shutdown_check(tmp, token=token, max_payload_bytes=max_payload_bytes, managed=managed, scan=scan, init_if_missing=init_if_missing)

    root_path = _resolved_root(root)
    config = CollectorConfig(
        root=root_path,
        host=DEFAULT_COLLECTOR_HOST,
        port=0,
        token=token,
        max_payload_bytes=max_payload_bytes,
        flush_interval_seconds=1 if managed else 0,
        scan_on_flush=scan,
        init_if_missing=init_if_missing,
        init_objective="Monitor collector graceful shutdown",
        init_criterion="Collector writes a stopped runtime status after shutdown.",
    )
    runtime_state = CollectorRuntimeState()
    server = build_collector_server(config, runtime_state)
    manager = start_collector_manager(config, runtime_state)
    thread = threading.Thread(target=server.serve_forever, name="hulun-collector-shutdown-check", daemon=True)
    thread.start()
    response_status = 0
    response_body: dict[str, Any] = {}
    managed_flush: dict[str, Any] | None = None
    failures: list[str] = []
    try:
        write_collector_status(config, runtime_state)
        host, port = server.server_address[:2]
        response_status, response_body = _post_json(f"http://{host}:{port}/v1/traces", _smoke_payload(), token=token)
        if managed:
            managed_flush = collector_flush_once(config, runtime_state)
    except (OSError, TimeoutError, http.client.HTTPException, json.JSONDecodeError) as exc:
        failures.append(str(exc))
    shutdown = _close_collector_runtime(
        config,
        runtime_state,
        server,
        manager,
        reason="shutdown_check",
        request_shutdown=True,
        serve_thread=thread,
    )
    final_status, final_status_error = _read_json_payload(collector_status_path(root_path))
    final_runtime = (
        final_status.get("managed", {}).get("runtime")
        if isinstance(final_status, dict) and isinstance(final_status.get("managed"), dict)
        else None
    )
    after = queue_status(root_path)
    if response_status != 202:
        failures.append(f"expected HTTP 202, got {response_status}")
    if int(response_body.get("queued") or 0) != 1:
        failures.append("collector response did not queue exactly one observation")
    if managed:
        if not managed_flush or not managed_flush.get("gate", {}).get("passed"):
            failures.append("managed collector flush did not pass before shutdown")
        expected_pending = int((managed_flush or {}).get("queue", {}).get("pending") or 0)
        if int(after["queue"]["pending"]) != expected_pending:
            failures.append(f"expected pending queue {expected_pending}, got {after['queue']['pending']}")
    if not shutdown.get("gate", {}).get("passed"):
        failures.extend(str(item) for item in shutdown.get("gate", {}).get("failures", []))
    if final_status_error:
        failures.append(f"final collector status file is not valid JSON: {final_status_error}")
    if not isinstance(final_runtime, dict):
        failures.append("final collector status does not include runtime state")
    else:
        if final_runtime.get("lifecycle_state") != "stopped":
            failures.append(f"expected final lifecycle_state stopped, got {final_runtime.get('lifecycle_state')}")
        if final_runtime.get("stop_reason") != "shutdown_check":
            failures.append(f"expected final stop_reason shutdown_check, got {final_runtime.get('stop_reason')}")
        if not final_runtime.get("stopped_at"):
            failures.append("final runtime state did not record stopped_at")
    return {
        "schema": COLLECTOR_SCHEMA,
        "generated_at": utc_now(),
        "operation": "shutdown_check",
        "root": str(root_path),
        "managed": managed,
        "response_status": response_status,
        "response": response_body,
        "managed_flush": managed_flush,
        "shutdown": shutdown,
        "final_status": final_status,
        "queue": after["queue"],
        "dead_letter": after["dead_letter"],
        "gate": {"passed": not failures, "failure_count": len(failures), "failures": failures},
    }
