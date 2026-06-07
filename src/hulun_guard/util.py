from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_minutes(value: str | None) -> float | None:
    parsed = parse_time(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0)


def normalize_list(values: list[str] | None) -> list[str]:
    return [v.strip() for v in values or [] if v and v.strip()]


def next_id(items: list[dict[str, Any]], prefix: str) -> str:
    max_seen = 0
    for item in items:
        value = str(item.get("id", ""))
        if value.startswith(prefix):
            try:
                max_seen = max(max_seen, int(value[len(prefix) :]))
            except ValueError:
                pass
    return f"{prefix}{max_seen + 1}"


def sort_ids(values: set[str]) -> list[str]:
    def key(value: str) -> tuple[str, int, str]:
        prefix = value[:1]
        suffix = value[1:]
        number = int(suffix) if suffix.isdigit() else 10**9
        return (prefix, number, value)

    return sorted(values, key=key)


def hash_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in sorted({"pending", "in_progress", "done", "blocked", "dropped"})}
    for item in items:
        status = item.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
    return counts


def tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {part for part in normalized.split() if len(part) >= 3}


def overlap_ratio(reference: str, candidate: str) -> float:
    ref_tokens = tokens(reference)
    if not ref_tokens:
        return 1.0
    cand_tokens = tokens(candidate)
    if not cand_tokens:
        return 0.0
    return len(ref_tokens & cand_tokens) / len(ref_tokens)
