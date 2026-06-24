from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .adapters import MAX_TRACE_BYTES, iter_observations, iter_payload_observations
from .constants import INGEST_DEAD_LETTER_FILE, INGEST_QUEUE_FILE
from .privacy import DEFAULT_RETENTION_DAYS, fingerprint_text, redact_text, sanitize_event
from .schemas import BATCH_INGEST_SCHEMA
from .sdk import HulunGuardError, append_observation_to_state
from .storage import hulun_dir, initial_state, load_state, project_root, save_state
from .util import utc_now

BATCH_FLUSH_LIMIT = 500
QUEUE_RECORD_SCHEMA = "hulun.ingest_queue_record.v1"
DEAD_LETTER_SCHEMA = "hulun.ingest_dead_letter.v1"


class BatchIngestError(HulunGuardError):
    """Raised when batched ingestion cannot safely continue."""


def _root(value: str | Path | None) -> Path:
    return project_root(str(value) if value is not None else None)


def queue_path(root: str | Path | None = None) -> Path:
    return hulun_dir(_root(root)) / INGEST_QUEUE_FILE


def dead_letter_path(root: str | Path | None = None) -> Path:
    return hulun_dir(_root(root)) / INGEST_DEAD_LETTER_FILE


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _new_queue_id() -> str:
    return f"Q{utc_now().replace('-', '').replace(':', '').replace('+', 'Z')}-{uuid.uuid4().hex[:12]}"


def _record_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json_line(payload).encode("utf-8")).hexdigest()


def _source_metadata(source_file: str | None) -> dict[str, Any] | None:
    if not source_file:
        return None
    path = Path(str(source_file))
    return {
        "name": redact_text(path.name),
        "fingerprint": fingerprint_text(str(source_file), prefix="source"),
    }


def _payload_source_metadata(source_name: str | None, payload: Any) -> dict[str, Any]:
    name = source_name or "runtime-payload"
    try:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise BatchIngestError(f"Runtime payload must be JSON-serializable: {exc}") from exc
    return {
        "name": redact_text(name),
        "fingerprint": fingerprint_text(serialized, prefix="payload"),
        "bytes": len(serialized.encode("utf-8")),
    }


def _check_payload_size(payload: Any, *, max_payload_bytes: int) -> None:
    try:
        size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise BatchIngestError(f"Runtime payload must be JSON-serializable: {exc}") from exc
    limit = max(1, int(max_payload_bytes))
    if size > limit:
        raise BatchIngestError(f"Runtime payload is too large: {size} bytes, limit is {limit} bytes.")


def _append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    items = list(records)
    if not items:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(_json_line(item))
    return len(items)


def _replace_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for item in records:
            handle.write(_json_line(item))
    os.replace(temp_path, path)


def _dead_letter(reason: str, *, record: dict[str, Any] | None = None, line_number: int | None = None, raw_line: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": DEAD_LETTER_SCHEMA,
        "id": _new_queue_id().replace("Q", "DL", 1),
        "created_at": utc_now(),
        "reason": reason,
    }
    if line_number is not None:
        payload["line_number"] = line_number
    if record is not None:
        payload["queue_id"] = record.get("id")
        payload["record_sha256"] = _record_hash(record)
        observation = record.get("observation")
        if isinstance(observation, dict):
            payload["summary"] = redact_text(observation.get("summary") or "")
            payload["type"] = observation.get("type")
            payload["source_platform"] = observation.get("source_platform")
    if raw_line is not None:
        payload["raw_sha256"] = hashlib.sha256(raw_line.encode("utf-8", errors="replace")).hexdigest()
        payload["raw_bytes"] = len(raw_line.encode("utf-8", errors="replace"))
    return payload


def _sanitize_observation(observation: dict[str, Any], *, include_sensitive: bool, retention_days: int) -> dict[str, Any]:
    sanitized = sanitize_event(observation, include_sensitive=include_sensitive, retention_days=retention_days)
    sanitized.pop("id", None)
    sanitized.pop("created_at", None)
    return sanitized


def make_observation(
    *,
    event_type: str,
    summary: str,
    result: str = "pass",
    phase: str | None = None,
    claims: list[str] | None = None,
    evidence: list[str] | None = None,
    refs: list[str] | None = None,
    resolved: bool | None = None,
    source_platform: str | None = None,
    action_key: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost: float | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "type": event_type,
        "summary": summary,
        "result": result,
        "phase": phase,
        "claims": claims or [],
        "evidence": evidence or [],
        "refs": refs or [],
        "resolved": resolved,
        "source_platform": source_platform,
        "action_key": action_key,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
        "latency_ms": latency_ms,
        "model": model,
    }
    return _sanitize_observation(observation, include_sensitive=include_sensitive, retention_days=retention_days)


def enqueue_observations(
    root: str | Path | None,
    observations: Iterable[dict[str, Any]],
    *,
    source_file: str | None = None,
    source: dict[str, Any] | None = None,
    source_format: str | None = None,
    source_platform: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    root_path = _root(root)
    queued_at = utc_now()
    path = queue_path(root_path)
    source = source or _source_metadata(source_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    queued_count = 0
    record_ids: list[str] = []
    with path.open("a", encoding="utf-8") as handle:
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            sanitized = _sanitize_observation(observation, include_sensitive=include_sensitive, retention_days=retention_days)
            if source_platform:
                sanitized["source_platform"] = source_platform
            record = {
                "schema": QUEUE_RECORD_SCHEMA,
                "id": _new_queue_id(),
                "queued_at": queued_at,
                "source": source,
                "source_format": source_format,
                "observation": sanitized,
            }
            record = {key: value for key, value in record.items() if value not in (None, "", [])}
            handle.write(_json_line(record))
            queued_count += 1
            record_ids.append(record["id"])
    status = queue_status(root_path)
    return {
        "schema": BATCH_INGEST_SCHEMA,
        "generated_at": utc_now(),
        "operation": "enqueue",
        "root": str(root_path),
        "queued": queued_count,
        "record_ids": record_ids,
        "queue": status["queue"],
        "dead_letter": status["dead_letter"],
    }


def enqueue_trace_file(
    root: str | Path | None,
    file: str | Path,
    source_format: str = "auto",
    *,
    source_platform: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_trace_bytes: int = MAX_TRACE_BYTES,
) -> dict[str, Any]:
    trace_path = Path(file)
    if not trace_path.is_absolute():
        trace_path = _root(root) / trace_path
    observations = iter_observations(trace_path, source_format, include_sensitive=include_sensitive, max_trace_bytes=max_trace_bytes)
    return enqueue_observations(
        root,
        observations,
        source_file=str(trace_path),
        source_format=source_format,
        source_platform=source_platform,
        include_sensitive=include_sensitive,
        retention_days=retention_days,
    )


def enqueue_payload(
    root: str | Path | None,
    payload: Any,
    source_format: str = "auto",
    *,
    source_name: str | None = None,
    source_platform: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_payload_bytes: int = MAX_TRACE_BYTES,
) -> dict[str, Any]:
    _check_payload_size(payload, max_payload_bytes=max_payload_bytes)
    observations = iter_payload_observations(payload, source_format, include_sensitive=include_sensitive)
    return enqueue_observations(
        root,
        observations,
        source=_payload_source_metadata(source_name, payload),
        source_format=source_format,
        source_platform=source_platform,
        include_sensitive=include_sensitive,
        retention_days=retention_days,
    )


def _read_queue(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    dead_letters: list[dict[str, Any]] = []
    if not path.exists():
        return records, dead_letters
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                dead_letters.append(_dead_letter("invalid_json", line_number=line_number, raw_line=line))
                continue
            if not isinstance(payload, dict):
                dead_letters.append(_dead_letter("record_not_object", line_number=line_number, raw_line=line))
                continue
            observation = payload.get("observation")
            if not isinstance(observation, dict):
                dead_letters.append(_dead_letter("observation_not_object", record=payload, line_number=line_number))
                continue
            records.append(payload)
    return records, dead_letters


def _dead_letter_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def queue_status(root: str | Path | None = None) -> dict[str, Any]:
    root_path = _root(root)
    path = queue_path(root_path)
    records, parse_dead_letters = _read_queue(path)
    queued_times = [str(record.get("queued_at")) for record in records if record.get("queued_at")]
    size = path.stat().st_size if path.exists() else 0
    dead_path = dead_letter_path(root_path)
    dead_count = _dead_letter_count(dead_path) + len(parse_dead_letters)
    return {
        "schema": BATCH_INGEST_SCHEMA,
        "generated_at": utc_now(),
        "operation": "status",
        "root": str(root_path),
        "queue": {
            "path": str(path),
            "pending": len(records),
            "bytes": size,
            "oldest_queued_at": min(queued_times) if queued_times else None,
            "newest_queued_at": max(queued_times) if queued_times else None,
            "parse_error_count": len(parse_dead_letters),
        },
        "dead_letter": {
            "path": str(dead_path),
            "records": dead_count,
        },
    }


def _load_or_init_state(
    root: Path,
    *,
    init_if_missing: bool,
    init_objective: str | None,
    init_criterion: str | None,
    init_threshold: int,
) -> dict[str, Any]:
    try:
        return load_state(root)
    except SystemExit:
        if not init_if_missing:
            raise
        return initial_state(
            objective=init_objective or "Monitor batched agent runtime reliability",
            criteria=[init_criterion or "Queued agent observations remain evidence-backed."],
            constraints=[],
            assumptions=[],
            threshold=init_threshold,
        )


def flush_queue(
    root: str | Path | None = None,
    *,
    limit: int = BATCH_FLUSH_LIMIT,
    include_events: bool = False,
    init_if_missing: bool = False,
    init_objective: str | None = None,
    init_criterion: str | None = None,
    init_threshold: int = 66,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    if limit < 1:
        raise BatchIngestError("limit must be at least 1.")
    root_path = _root(root)
    path = queue_path(root_path)
    records, dead_letters = _read_queue(path)
    state = _load_or_init_state(
        root_path,
        init_if_missing=init_if_missing,
        init_objective=init_objective,
        init_criterion=init_criterion,
        init_threshold=init_threshold,
    )
    processed_records = records[:limit]
    remaining_records = records[limit:]
    imported_count = 0
    first_id = None
    last_id = None
    sample_events: list[dict[str, Any]] = []
    for record in processed_records:
        observation = record.get("observation")
        if not isinstance(observation, dict):
            dead_letters.append(_dead_letter("observation_not_object", record=record))
            continue
        queue_metadata = {"queue_id": record.get("id"), "queued_at": record.get("queued_at")}
        try:
            event = append_observation_to_state(
                state,
                observation,
                include_sensitive=include_sensitive,
                retention_days=retention_days,
                queue_metadata=queue_metadata,
            )
        except HulunGuardError as exc:
            dead_letters.append(_dead_letter(f"append_failed:{exc}", record=record))
            continue
        imported_count += 1
        first_id = first_id or event["id"]
        last_id = event["id"]
        if include_events:
            sample_events.append(event)

    save_state(root_path, state)
    _replace_jsonl(path, remaining_records)
    _append_jsonl(dead_letter_path(root_path), dead_letters)
    status = queue_status(root_path)
    payload: dict[str, Any] = {
        "schema": BATCH_INGEST_SCHEMA,
        "generated_at": utc_now(),
        "operation": "flush",
        "root": str(root_path),
        "requested_limit": limit,
        "imported": imported_count,
        "first_event_id": first_id,
        "last_event_id": last_id,
        "dead_lettered": len(dead_letters),
        "queue": status["queue"],
        "dead_letter": status["dead_letter"],
    }
    if include_events:
        payload["events"] = sample_events
    return payload
