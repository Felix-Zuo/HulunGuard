from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import (
    LEGACY_STATE_DIR,
    RESUME_FILE,
    RISK_FILE,
    STATE_DIR,
    STATE_FILE,
    VERIFY_FILE,
)
from .reports import build_resume_markdown
from .schemas import STATE_SCHEMA, normalize_state
from .util import utc_now


def project_root(value: str | None) -> Path:
    return Path(value or ".").resolve()


def hulun_dir(root: Path) -> Path:
    return root / STATE_DIR


def legacy_dir(root: Path) -> Path:
    return root / LEGACY_STATE_DIR


def state_path(root: Path) -> Path:
    return hulun_dir(root) / STATE_FILE


def legacy_state_path(root: Path) -> Path:
    return legacy_dir(root) / STATE_FILE


def resume_path(root: Path) -> Path:
    return hulun_dir(root) / RESUME_FILE


def verify_path(root: Path) -> Path:
    return hulun_dir(root) / VERIFY_FILE


def risk_path(root: Path) -> Path:
    return hulun_dir(root) / RISK_FILE


def load_state(root: Path, allow_legacy: bool = True) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists() and allow_legacy and legacy_state_path(root).exists():
        state = json.loads(legacy_state_path(root).read_text(encoding="utf-8"))
        state = normalize_state(state, source=str(legacy_state_path(root)))
        state["migrated_from"] = str(legacy_state_path(root))
        return state
    if not path.exists():
        raise SystemExit(f"No HulunGuard state found: {path}. Run init first.")
    return normalize_state(json.loads(path.read_text(encoding="utf-8")), source=str(path))


def save_state(root: Path, state: dict[str, Any], write_resume: bool = True) -> None:
    state = normalize_state(state, source=str(state_path(root)))
    state["updated_at"] = utc_now()
    state["schema"] = STATE_SCHEMA
    hulun_dir(root).mkdir(parents=True, exist_ok=True)
    state_path(root).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if write_resume:
        resume_path(root).write_text(build_resume_markdown(state), encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_item(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise SystemExit(f"Unknown {label} id: {item_id}")


def initial_state(
    objective: str,
    criteria: list[str],
    constraints: list[str],
    assumptions: list[str],
    threshold: int,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": STATE_SCHEMA,
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "objective": objective.strip(),
        "threshold": threshold,
        "criteria": [
            {"id": f"C{idx}", "text": text, "status": "pending", "evidence": []}
            for idx, text in enumerate(criteria, start=1)
        ],
        "success_criteria": [],
        "constraints": constraints,
        "assumptions": assumptions,
        "steps": [],
        "evidence": [],
        "events": [],
        "risks": [],
        "decisions": [],
        "checkpoints": [],
        "last_scan": None,
        "last_verify": None,
    }


def criteria(state: dict[str, Any]) -> list[dict[str, Any]]:
    if state.get("criteria"):
        return state["criteria"]
    return state.setdefault("success_criteria", [])


def all_items_with_evidence(state: dict[str, Any]) -> list[dict[str, Any]]:
    return criteria(state) + state.get("steps", [])
