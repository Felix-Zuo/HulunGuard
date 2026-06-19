from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

DEFAULT_RETENTION_DAYS = 30
MAX_PUBLIC_TEXT = 500

TRACE_TEXT_KEYS = [
    "arguments",
    "completion",
    "content",
    "input",
    "message",
    "messages",
    "observation",
    "output",
    "prompt",
    "response",
    "result_text",
    "text",
    "tool_arguments",
    "tool_result",
]

SENSITIVE_PAYLOAD_KEYS = set(TRACE_TEXT_KEYS)

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "[redacted:private-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[redacted:openai-key]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[redacted:github-token]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "[redacted:github-token]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), "[redacted:gitlab-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted:aws-key]"),
    (re.compile(r"(?i)\b(authorization\s*:\s*bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [redacted:bearer-token]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"), r"\1=[redacted:secret]"),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[redacted:email]"),
]


def fingerprint_text(text: str, *, prefix: str = "fp") -> str:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def redact_text(value: Any, *, include_sensitive: bool = False, max_length: int = MAX_PUBLIC_TEXT) -> str:
    text = "" if value is None else str(value)
    if include_sensitive:
        return text.strip()

    cleaned = text.strip()
    for pattern, replacement in SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    home = str(Path.home())
    if home:
        cleaned = cleaned.replace(home, "~")
        cleaned = cleaned.replace(home.replace("\\", "/"), "~")
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        cleaned = cleaned.replace(user_profile, "~")
        cleaned = cleaned.replace(user_profile.replace("\\", "/"), "~")

    if len(cleaned) > max_length:
        return cleaned[:max_length].rstrip() + " [truncated]"
    return cleaned


def redact_ref(value: Any, *, include_sensitive: bool = False) -> str:
    text = redact_text(value, include_sensitive=include_sensitive, max_length=MAX_PUBLIC_TEXT)
    if include_sensitive:
        return text
    parsed = urlsplit(text)
    if parsed.scheme and parsed.netloc:
        hostname = parsed.hostname or parsed.netloc
        netloc = hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    return text


def redact_list(values: list[Any] | None, *, include_sensitive: bool = False) -> list[str]:
    return [redact_text(value, include_sensitive=include_sensitive) for value in values or [] if str(value).strip()]


def redact_refs(values: list[Any] | None, *, include_sensitive: bool = False) -> list[str]:
    return [redact_ref(value, include_sensitive=include_sensitive) for value in values or [] if str(value).strip()]


def privacy_metadata(*, include_sensitive: bool = False, retention_days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
    return {
        "mode": "sensitive-opt-in" if include_sensitive else "redacted-default",
        "retention_days": max(1, int(retention_days)),
    }


def safe_summary_from_trace(item: dict[str, Any], *, include_sensitive: bool = False, fallback: str = "Imported observation.") -> str:
    summary = item.get("summary")
    if summary not in (None, ""):
        return redact_text(summary, include_sensitive=include_sensitive)
    if include_sensitive:
        for key in TRACE_TEXT_KEYS:
            value = item.get(key)
            if value not in (None, ""):
                return redact_text(value, include_sensitive=True)
    raw_type = item.get("type") or item.get("event_type") or item.get("class") or item.get("name")
    if raw_type:
        return f"Imported {redact_text(raw_type)} observation; sensitive payload withheld."
    for key in SENSITIVE_PAYLOAD_KEYS:
        if key in item and item.get(key) not in (None, ""):
            return f"Imported {key} payload; sensitive content withheld."
    return fallback


def sanitize_event(
    event: dict[str, Any],
    *,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    sanitized = dict(event)
    for key in ["summary", "action_key", "model"]:
        if key in sanitized:
            sanitized[key] = redact_text(sanitized[key], include_sensitive=include_sensitive)
    if "claims" in sanitized:
        sanitized["claims"] = redact_list(sanitized.get("claims"), include_sensitive=include_sensitive)
    if "refs" in sanitized:
        sanitized["refs"] = redact_refs(sanitized.get("refs"), include_sensitive=include_sensitive)
    sanitized["privacy"] = privacy_metadata(include_sensitive=include_sensitive, retention_days=retention_days)
    return sanitized


def sanitize_evidence(
    evidence: dict[str, Any],
    *,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    sanitized = dict(evidence)
    for key in ["summary", "command", "url", "notes"]:
        if key in sanitized:
            sanitized[key] = redact_ref(sanitized[key], include_sensitive=include_sensitive) if key == "url" else redact_text(
                sanitized[key], include_sensitive=include_sensitive
            )
    if "path" in sanitized:
        sanitized["path"] = redact_ref(sanitized["path"], include_sensitive=include_sensitive)
    sanitized["privacy"] = privacy_metadata(include_sensitive=include_sensitive, retention_days=retention_days)
    return sanitized
