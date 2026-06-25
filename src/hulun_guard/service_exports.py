from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .privacy import DEFAULT_RETENTION_DAYS, privacy_metadata, redact_ref, redact_text
from .schemas import SERVICE_EXPORT_SCHEMA
from .util import parse_time, utc_now

LANGSMITH_DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
LANGSMITH_RUNS_QUERY_PATH = "/v2/runs/query"
LANGSMITH_DEFAULT_PAGE_SIZE = 100
LANGSMITH_MAX_PAGE_SIZE = 1000
LANGSMITH_DEFAULT_MAX_RUNS = 100
LANGSMITH_DEFAULT_TIMEOUT_SECONDS = 30.0
LANGSMITH_SELECTS = (
    "ID",
    "NAME",
    "RUN_TYPE",
    "STATUS",
    "START_TIME",
    "END_TIME",
    "ERROR",
    "ERROR_PREVIEW",
    "PROJECT_ID",
    "TRACE_ID",
    "DOTTED_ORDER",
    "IS_ROOT",
    "TOTAL_TOKENS",
    "PROMPT_TOKENS",
    "COMPLETION_TOKENS",
    "TOTAL_COST",
)


@dataclass(frozen=True)
class JsonPostResponse:
    status: int
    body: bytes | str | dict[str, Any] | list[Any]
    headers: dict[str, str] | None = None


JsonPostTransport = Callable[[str, dict[str, str], dict[str, Any], float], JsonPostResponse]


@dataclass(frozen=True)
class LangSmithServiceConfig:
    endpoint: str
    api_key: str
    project_id: str
    output: Path
    page_size: int = LANGSMITH_DEFAULT_PAGE_SIZE
    max_runs: int = LANGSMITH_DEFAULT_MAX_RUNS
    min_start_time: str | None = None
    max_start_time: str | None = None
    filter: str | None = None
    run_type: str | None = None
    include_sensitive: bool = False
    retention_days: int = DEFAULT_RETENTION_DAYS
    timeout_seconds: float = LANGSMITH_DEFAULT_TIMEOUT_SECONDS
    overwrite: bool = False


class ServiceExportError(ValueError):
    """Raised when a native service export cannot be completed safely."""


def service_export_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def _clean_endpoint(endpoint: str) -> str:
    text = str(endpoint or "").strip().rstrip("/")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ServiceExportError("LangSmith endpoint must use http or https.")
    if not parsed.hostname:
        raise ServiceExportError("LangSmith endpoint must include a host.")
    if parsed.username or parsed.password:
        raise ServiceExportError("LangSmith endpoint must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ServiceExportError("LangSmith endpoint must not contain query strings or fragments.")
    return text


def _validated_config(config: LangSmithServiceConfig) -> LangSmithServiceConfig:
    endpoint = _clean_endpoint(config.endpoint)
    api_key = str(config.api_key or "").strip()
    project_id = str(config.project_id or "").strip()
    if not api_key:
        raise ServiceExportError("LangSmith API key is required and must be supplied explicitly.")
    if not project_id:
        raise ServiceExportError("LangSmith project id is required.")
    if not (1 <= int(config.page_size) <= LANGSMITH_MAX_PAGE_SIZE):
        raise ServiceExportError(f"LangSmith page size must be between 1 and {LANGSMITH_MAX_PAGE_SIZE}.")
    if int(config.max_runs) < 1:
        raise ServiceExportError("LangSmith max-runs must be at least 1.")
    if float(config.timeout_seconds) <= 0:
        raise ServiceExportError("LangSmith timeout-seconds must be greater than zero.")
    return LangSmithServiceConfig(
        endpoint=endpoint,
        api_key=api_key,
        project_id=project_id,
        output=Path(config.output),
        page_size=int(config.page_size),
        max_runs=int(config.max_runs),
        min_start_time=config.min_start_time,
        max_start_time=config.max_start_time,
        filter=config.filter,
        run_type=config.run_type,
        include_sensitive=bool(config.include_sensitive),
        retention_days=max(1, int(config.retention_days)),
        timeout_seconds=float(config.timeout_seconds),
        overwrite=bool(config.overwrite),
    )


def _langsmith_query_body(config: LangSmithServiceConfig, *, cursor: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_ids": [config.project_id],
        "page_size": min(config.page_size, config.max_runs),
        "selects": list(LANGSMITH_SELECTS),
    }
    if cursor:
        body["cursor"] = cursor
    if config.min_start_time:
        body["min_start_time"] = config.min_start_time
    if config.max_start_time:
        body["max_start_time"] = config.max_start_time
    if config.filter:
        body["filter"] = config.filter
    if config.run_type:
        body["run_type"] = config.run_type
    return body


def _default_json_post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float) -> JsonPostResponse:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ServiceExportError("LangSmith request URL must use http or https and include a host.")
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **headers,
    }
    connection = connection_cls(parsed.hostname, parsed.port, timeout=timeout_seconds)
    try:
        connection.request("POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        return JsonPostResponse(status=response.status, body=response.read(), headers=dict(response.getheaders()))
    except OSError as exc:
        raise ServiceExportError(f"LangSmith request failed: {redact_text(exc)}") from None
    finally:
        connection.close()


def _decode_response_body(response: JsonPostResponse) -> dict[str, Any] | list[Any]:
    if isinstance(response.body, (dict, list)):
        return response.body
    raw = response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceExportError(f"LangSmith returned malformed JSON: {exc.msg}") from None
    if not isinstance(payload, (dict, list)):
        raise ServiceExportError("LangSmith response must be a JSON object or array.")
    return payload


def _response_runs(payload: dict[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(payload, list):
        runs = payload
        cursor = None
    else:
        if isinstance(payload.get("runs"), list):
            runs = payload["runs"]
        elif isinstance(payload.get("items"), list):
            runs = payload["items"]
        else:
            raise ServiceExportError("LangSmith response is missing a runs/items list.")
        cursor_value = payload.get("next_cursor") or payload.get("next") or payload.get("cursor")
        cursor = str(cursor_value) if cursor_value else None
    invalid_count = sum(1 for item in runs if not isinstance(item, dict))
    if invalid_count:
        raise ServiceExportError("LangSmith response contains non-object run items.")
    return [item for item in runs if isinstance(item, dict)], cursor


def _field(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
        lowered = name.lower()
        if lowered in item:
            return item[lowered]
    return None


def _text(value: Any, *, include_sensitive: bool) -> str | None:
    if value in (None, ""):
        return None
    return redact_text(value, include_sensitive=include_sensitive)


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def _latency_ms(start_time: Any, end_time: Any) -> int | None:
    start = parse_time(str(start_time)) if start_time else None
    end = parse_time(str(end_time)) if end_time else None
    if not start or not end:
        return None
    return max(0, int(round((end - start).total_seconds() * 1000)))


def _result_from_status(status: Any, error: Any) -> str:
    if error not in (None, ""):
        return "fail"
    text = str(status or "").strip().lower()
    if text in {"success", "succeeded", "complete", "completed", "pass", "passed"}:
        return "pass"
    if text in {"error", "errored", "failed", "failure", "cancelled", "canceled", "timeout", "timed_out"}:
        return "fail"
    return "unknown"


def sanitize_langsmith_run(item: dict[str, Any], *, include_sensitive: bool = False) -> dict[str, Any]:
    error = _field(item, "error", "ERROR", "error_preview", "ERROR_PREVIEW")
    status = _field(item, "status", "STATUS")
    start_time = _field(item, "start_time", "START_TIME", "startTime")
    end_time = _field(item, "end_time", "END_TIME", "endTime")
    sanitized: dict[str, Any] = {
        "id": _text(_field(item, "id", "ID", "run_id", "RUN_ID"), include_sensitive=include_sensitive),
        "trace_id": _text(_field(item, "trace_id", "TRACE_ID", "traceId"), include_sensitive=include_sensitive),
        "run_type": _text(_field(item, "run_type", "RUN_TYPE", "type", "TYPE"), include_sensitive=include_sensitive),
        "name": _text(_field(item, "name", "NAME", "display_name", "DISPLAY_NAME"), include_sensitive=include_sensitive),
        "dotted_order": _text(_field(item, "dotted_order", "DOTTED_ORDER"), include_sensitive=include_sensitive),
        "status": _text(status, include_sensitive=include_sensitive),
        "result": _result_from_status(status, error),
        "start_time": _text(start_time, include_sensitive=include_sensitive),
        "end_time": _text(end_time, include_sensitive=include_sensitive),
        "error": _text(_field(item, "error", "ERROR"), include_sensitive=include_sensitive),
        "error_preview": _text(_field(item, "error_preview", "ERROR_PREVIEW"), include_sensitive=include_sensitive),
        "project_id": _text(_field(item, "project_id", "PROJECT_ID"), include_sensitive=include_sensitive),
        "prompt_tokens": _number(_field(item, "prompt_tokens", "PROMPT_TOKENS")),
        "completion_tokens": _number(_field(item, "completion_tokens", "COMPLETION_TOKENS")),
        "total_tokens": _number(_field(item, "total_tokens", "TOTAL_TOKENS")),
        "cost": _number(_field(item, "total_cost", "TOTAL_COST", "cost", "COST")),
        "latency_ms": _number(_field(item, "latency_ms", "LATENCY_MS")) or _latency_ms(start_time, end_time),
    }
    is_root = _field(item, "is_root", "IS_ROOT")
    if isinstance(is_root, bool):
        sanitized["is_root"] = is_root
    return {key: value for key, value in sanitized.items() if value not in (None, "", [])}


def _request_summary(config: LangSmithServiceConfig) -> dict[str, Any]:
    filters = {
        "min_start_time": config.min_start_time,
        "max_start_time": config.max_start_time,
        "filter": config.filter,
        "run_type": config.run_type,
    }
    return {
        "endpoint": redact_ref(config.endpoint),
        "path": LANGSMITH_RUNS_QUERY_PATH,
        "project_id": config.project_id,
        "page_size": config.page_size,
        "max_runs": config.max_runs,
        "selects": list(LANGSMITH_SELECTS),
        "filters": {key: value for key, value in filters.items() if value},
        "auth": "explicit-api-key",
    }


def _trace_doctor_command(output: Path) -> str:
    rendered = str(output).replace('"', '\\"')
    return f'python -m hulun_guard trace-doctor --format langsmith --file "{rendered}" --json'


def _ingest_command(output: Path) -> str:
    rendered = str(output).replace('"', '\\"')
    return f'python -m hulun_guard ingest --format langsmith --file "{rendered}" --scan --init-if-missing'


def export_langsmith_runs(
    config: LangSmithServiceConfig,
    *,
    transport: JsonPostTransport | None = None,
) -> dict[str, Any]:
    config = _validated_config(config)
    output = config.output
    if output.exists() and not config.overwrite:
        raise ServiceExportError(f"Output already exists: {output}. Use --force to overwrite.")
    output.parent.mkdir(parents=True, exist_ok=True)

    url = f"{config.endpoint}{LANGSMITH_RUNS_QUERY_PATH}"
    headers = {"X-Api-Key": config.api_key}
    post = transport or _default_json_post
    runs: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    pages_fetched = 0
    truncated = False
    response_key = "unknown"

    while len(runs) < config.max_runs:
        body = _langsmith_query_body(config, cursor=cursor)
        response = post(url, headers, body, config.timeout_seconds)
        pages_fetched += 1
        if response.status in {401, 403}:
            raise ServiceExportError("LangSmith authentication failed. Check the explicit API key and project access.")
        if response.status == 429:
            raise ServiceExportError("LangSmith rate limit was reached. Retry later or lower --page-size.")
        if response.status < 200 or response.status >= 300:
            raise ServiceExportError(f"LangSmith export failed with HTTP {response.status}.")

        payload = _decode_response_body(response)
        page_runs, cursor = _response_runs(payload)
        if cursor:
            if cursor in seen_cursors:
                raise ServiceExportError("LangSmith pagination cursor repeated without completing the export.")
            seen_cursors.add(cursor)
        if cursor and not page_runs:
            raise ServiceExportError("LangSmith pagination did not advance; response contained a cursor but no runs.")
        if isinstance(payload, dict):
            response_key = "runs" if isinstance(payload.get("runs"), list) else "items" if isinstance(payload.get("items"), list) else response_key
        remaining = config.max_runs - len(runs)
        runs.extend(sanitize_langsmith_run(item, include_sensitive=config.include_sensitive) for item in page_runs[:remaining])
        if len(page_runs) > remaining or (cursor and len(runs) >= config.max_runs):
            truncated = True
            break
        if not cursor:
            break

    export_payload = {
        "schema": SERVICE_EXPORT_SCHEMA,
        "generated_at": utc_now(),
        "provider": "langsmith",
        "source": {
            "endpoint": redact_ref(config.endpoint),
            "path": LANGSMITH_RUNS_QUERY_PATH,
            "project_id": config.project_id,
            "response_key": response_key,
        },
        "privacy": privacy_metadata(include_sensitive=config.include_sensitive, retention_days=config.retention_days),
        "runs": runs,
    }
    tmp_path = output.with_name(f"{output.name}.tmp")
    tmp_path.write_text(service_export_json(export_payload), encoding="utf-8")
    tmp_path.replace(output)

    result = {
        "schema": SERVICE_EXPORT_SCHEMA,
        "generated_at": utc_now(),
        "provider": "langsmith",
        "operation": "export",
        "output": str(output),
        "request": _request_summary(config),
        "pagination": {
            "pages_fetched": pages_fetched,
            "truncated": truncated,
            "next_cursor_present": bool(cursor),
        },
        "exported": {
            "run_count": len(runs),
            "format": "langsmith",
            "trace_doctor_command": _trace_doctor_command(output),
            "ingest_command": _ingest_command(output),
        },
        "privacy": privacy_metadata(include_sensitive=config.include_sensitive, retention_days=config.retention_days),
        "gate": {
            "passed": True,
            "failure_count": 0,
            "failures": [],
        },
    }
    return result
