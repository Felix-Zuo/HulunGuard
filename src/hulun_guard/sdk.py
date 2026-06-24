from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import VALID_EVENT_PHASES
from .conversation import (
    close_conversation,
    load_conversation,
    record_conversation_event,
    refresh_conversation_scan,
    start_conversation,
)
from .privacy import DEFAULT_RETENTION_DAYS, sanitize_event
from .risk import scan_state
from .storage import hulun_dir, initial_state, load_state, project_root, risk_path, save_state, write_json
from .util import next_counter_id, normalize_list, utc_now

VALID_RESULTS = {"pass", "fail", "unknown"}


class HulunGuardError(RuntimeError):
    """Raised when the public SDK cannot complete a HulunGuard operation."""


def require_sdk_phase(phase: str | None) -> str | None:
    if phase is None:
        return None
    if phase not in VALID_EVENT_PHASES:
        raise HulunGuardError(f"Invalid phase '{phase}'. Expected one of: {', '.join(sorted(VALID_EVENT_PHASES))}")
    return phase


def require_sdk_result(result: str) -> str:
    if result not in VALID_RESULTS:
        raise HulunGuardError(f"Invalid result '{result}'. Expected one of: {', '.join(sorted(VALID_RESULTS))}")
    return result


def normalize_sdk_list(values: Any, *, field: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return normalize_list([values])
    if not isinstance(values, (list, tuple, set)):
        raise HulunGuardError(f"{field} must be a string or a list of strings.")
    return normalize_list([str(value) for value in values])


def append_project_event(
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
    event = {
        "id": next_counter_id(state, "events", "EV"),
        "type": event_type,
        "summary": str(summary).strip(),
        "result": result,
        "refs": refs or [],
        "evidence": evidence or [],
        "created_at": utc_now(),
    }
    if resolved is not None:
        event["resolved"] = resolved
    for key, value in (extra or {}).items():
        if value not in (None, "", []):
            event[key] = value
    event = sanitize_event(event, include_sensitive=include_sensitive, retention_days=retention_days)
    state.setdefault("events", []).append(event)
    return event


def append_observation_to_state(
    state: dict[str, Any],
    observation: dict[str, Any],
    *,
    source_platform: str | None = None,
    include_sensitive: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    queue_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = {
        "phase": require_sdk_phase(observation.get("phase")),
        "claims": normalize_sdk_list(observation.get("claims") or [], field="claims"),
        "source_platform": source_platform or observation.get("source_platform"),
        "action_key": observation.get("action_key"),
        "prompt_tokens": observation.get("prompt_tokens"),
        "completion_tokens": observation.get("completion_tokens"),
        "cost": observation.get("cost"),
        "latency_ms": observation.get("latency_ms"),
        "model": observation.get("model"),
    }
    if queue_metadata:
        extra["queue_id"] = queue_metadata.get("queue_id")
        extra["queued_at"] = queue_metadata.get("queued_at")
    return append_project_event(
        state,
        str(observation.get("type") or "observation"),
        str(observation.get("summary") or "Imported observation."),
        result=require_sdk_result(str(observation.get("result") or "unknown")),
        refs=normalize_sdk_list(observation.get("refs") or [], field="refs"),
        resolved=observation.get("resolved"),
        evidence=normalize_sdk_list(observation.get("evidence") or [], field="evidence"),
        extra=extra,
        include_sensitive=include_sensitive,
        retention_days=retention_days,
    )


class HulunGuardClient:
    """Stable local adapter SDK for recording agent runtime state."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        include_sensitive: bool = False,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.root = project_root(str(root))
        self.include_sensitive = include_sensitive
        self.retention_days = retention_days

    def init(
        self,
        *,
        objective: str,
        criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        assumptions: list[str] | None = None,
        threshold: int = 66,
        force: bool = False,
    ) -> dict[str, Any]:
        state_file = hulun_dir(self.root) / "state.json"
        if state_file.exists() and not force:
            raise HulunGuardError(f"State already exists: {state_file}. Use force=True to replace it.")
        state = initial_state(
            objective,
            normalize_sdk_list(criteria, field="criteria"),
            normalize_sdk_list(constraints, field="constraints"),
            normalize_sdk_list(assumptions, field="assumptions"),
            threshold,
        )
        append_project_event(
            state,
            "init",
            f"Initialized HulunGuard objective: {objective}",
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
        )
        save_state(self.root, state)
        return state

    def load_state(self) -> dict[str, Any]:
        try:
            return load_state(self.root)
        except SystemExit as exc:
            raise HulunGuardError(str(exc)) from None

    def observe(
        self,
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
        scan: bool = False,
        threshold: int | None = None,
        checkpoint_stale_minutes: int = 45,
        final_attempt: bool = False,
    ) -> dict[str, Any]:
        state = self.load_state()
        event = append_project_event(
            state,
            event_type,
            summary,
            result=require_sdk_result(result),
            refs=normalize_sdk_list(refs, field="refs"),
            resolved=resolved,
            evidence=normalize_sdk_list(evidence, field="evidence"),
            extra={
                "phase": require_sdk_phase(phase),
                "claims": normalize_sdk_list(claims, field="claims"),
                "source_platform": source_platform,
                "action_key": action_key,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
                "latency_ms": latency_ms,
                "model": model,
            },
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
        )
        payload: dict[str, Any] = {"event": event}
        if scan:
            risk = scan_state(
                state,
                threshold=threshold,
                final_attempt=final_attempt,
                checkpoint_stale_minutes=checkpoint_stale_minutes,
            )
            state["last_scan"] = risk
            write_json(risk_path(self.root), risk)
            payload["risk"] = risk
        save_state(self.root, state)
        return payload

    def enqueue(
        self,
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
    ) -> dict[str, Any]:
        from .queue import enqueue_observations, make_observation

        observation = make_observation(
            event_type=event_type,
            summary=summary,
            result=require_sdk_result(result),
            phase=require_sdk_phase(phase),
            claims=normalize_sdk_list(claims, field="claims"),
            evidence=normalize_sdk_list(evidence, field="evidence"),
            refs=normalize_sdk_list(refs, field="refs"),
            resolved=resolved,
            source_platform=source_platform,
            action_key=action_key,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            latency_ms=latency_ms,
            model=model,
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
        )
        return enqueue_observations(
            self.root,
            [observation],
            source_format="sdk",
            source_platform=source_platform,
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
        )

    def enqueue_trace_file(
        self,
        *,
        file: str | Path,
        source_format: str = "auto",
        source_platform: str | None = None,
        max_trace_bytes: int | None = None,
    ) -> dict[str, Any]:
        from .adapters import MAX_TRACE_BYTES
        from .queue import enqueue_trace_file

        return enqueue_trace_file(
            self.root,
            file,
            source_format,
            source_platform=source_platform,
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
            max_trace_bytes=max_trace_bytes or MAX_TRACE_BYTES,
        )

    def queue_status(self) -> dict[str, Any]:
        from .queue import queue_status

        return queue_status(self.root)

    def flush_queue(
        self,
        *,
        limit: int = 500,
        scan: bool = False,
        threshold: int | None = None,
        checkpoint_stale_minutes: int = 45,
        final_attempt: bool = False,
        init_if_missing: bool = False,
        init_objective: str | None = None,
        init_criterion: str | None = None,
        init_threshold: int = 66,
    ) -> dict[str, Any]:
        from .queue import flush_queue

        payload = flush_queue(
            self.root,
            limit=limit,
            init_if_missing=init_if_missing,
            init_objective=init_objective,
            init_criterion=init_criterion,
            init_threshold=init_threshold,
            include_sensitive=self.include_sensitive,
            retention_days=self.retention_days,
        )
        if scan:
            state = self.load_state()
            risk = scan_state(
                state,
                threshold=threshold,
                final_attempt=final_attempt,
                checkpoint_stale_minutes=checkpoint_stale_minutes,
            )
            state["last_scan"] = risk
            save_state(self.root, state)
            write_json(risk_path(self.root), risk)
            payload["risk"] = risk
        return payload

    def scan(
        self,
        *,
        threshold: int | None = None,
        final_attempt: bool = False,
        checkpoint_stale_minutes: int = 45,
    ) -> dict[str, Any]:
        state = self.load_state()
        risk = scan_state(
            state,
            threshold=threshold,
            final_attempt=final_attempt,
            checkpoint_stale_minutes=checkpoint_stale_minutes,
        )
        state["last_scan"] = risk
        save_state(self.root, state)
        write_json(risk_path(self.root), risk)
        return risk

    def start_conversation(
        self,
        *,
        name: str,
        group: str = "default",
        objective: str | None = None,
        monitor: bool = False,
        widget: bool = False,
    ) -> dict[str, Any]:
        return start_conversation(
            name=name,
            group=group,
            root=str(self.root),
            objective=objective,
            monitor=monitor or widget,
            widget=widget,
        )

    def conversation_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        summary: str,
        result: str = "pass",
        phase: str | None = None,
        claims: list[str] | None = None,
        evidence: list[str] | None = None,
        refs: list[str] | None = None,
        resolved: bool | None = None,
        action_key: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost: float | None = None,
        latency_ms: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        try:
            _data, event, risk = record_conversation_event(
                conversation_id,
                event_type,
                summary,
                result=require_sdk_result(result),
                phase=require_sdk_phase(phase),
                claims=normalize_sdk_list(claims, field="claims"),
                evidence=normalize_sdk_list(evidence, field="evidence"),
                refs=normalize_sdk_list(refs, field="refs"),
                resolved=resolved,
                action_key=action_key,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=latency_ms,
                model=model,
                include_sensitive=self.include_sensitive,
                retention_days=self.retention_days,
            )
        except SystemExit as exc:
            raise HulunGuardError(str(exc)) from None
        return {"event": event, "risk": risk}

    def conversation_scan(self, *, conversation_id: str, checkpoint_stale_minutes: int = 45) -> dict[str, Any]:
        try:
            data, risk = refresh_conversation_scan(
                conversation_id,
                checkpoint_stale_minutes=checkpoint_stale_minutes,
            )
        except SystemExit as exc:
            raise HulunGuardError(str(exc)) from None
        return {"conversation": data, "risk": risk}

    def conversation_status(self, *, conversation_id: str) -> dict[str, Any]:
        try:
            return load_conversation(conversation_id)
        except SystemExit as exc:
            raise HulunGuardError(str(exc)) from None

    def close_conversation(self, *, conversation_id: str) -> dict[str, Any]:
        try:
            return close_conversation(conversation_id)
        except SystemExit as exc:
            raise HulunGuardError(str(exc)) from None


__all__ = [
    "HulunGuardClient",
    "HulunGuardError",
    "append_observation_to_state",
    "append_project_event",
    "normalize_sdk_list",
    "require_sdk_phase",
    "require_sdk_result",
]
