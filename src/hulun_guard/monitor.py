from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .constants import BOARD_FILE, MONITORS_DIR
from .risk import band_for
from .risk import scan_state
from .storage import hulun_dir, load_state
from .util import clamp_score, next_id, utc_now


def hulun_home() -> Path:
    configured = os.environ.get("HULUN_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".hulun").resolve()


def monitors_dir() -> Path:
    path = hulun_home() / MONITORS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def monitor_path(monitor_id: str) -> Path:
    return monitors_dir() / f"{monitor_id}.json"


def board_path() -> Path:
    return hulun_home() / BOARD_FILE


def new_monitor_id() -> str:
    existing = [{"id": path.stem} for path in monitors_dir().glob("M*.json")]
    return next_id(existing, "M")


def load_monitor(monitor_id: str) -> dict[str, Any]:
    path = monitor_path(monitor_id)
    if not path.exists():
        raise SystemExit(f"Unknown monitor id: {monitor_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def sync_monitor_from_root(monitor_id: str) -> dict[str, Any]:
    data = load_monitor(monitor_id)
    root = Path(data.get("root", "."))
    if not (hulun_dir(root) / "state.json").exists():
        return data
    try:
        state = load_state(root)
        risk = scan_state(state, threshold=None, final_attempt=False, checkpoint_stale_minutes=45)
    except Exception:
        return data
    data["score"] = int(risk.get("score", data.get("score", 0)))
    data["band"] = risk.get("band", band_for(data["score"]))
    data["reasons"] = risk.get("reasons", data.get("reasons", []))
    data["last_scan"] = risk.get("generated_at")
    save_monitor(data)
    return data


def save_monitor(data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    monitor_path(data["id"]).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_monitors() -> list[dict[str, Any]]:
    items = []
    for path in sorted(monitors_dir().glob("*.json")):
        try:
            monitor_id = path.stem
            items.append(sync_monitor_from_root(monitor_id))
        except json.JSONDecodeError:
            continue
        except SystemExit:
            continue
    return items


def create_monitor(
    conversation: str,
    group: str,
    root: str,
    score: int,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    score = clamp_score(score)
    data = {
        "schema": "hulun.monitor.v1",
        "id": new_monitor_id(),
        "conversation": conversation,
        "group": group,
        "root": str(Path(root).resolve()),
        "created_at": now,
        "updated_at": now,
        "score": score,
        "band": band_for(score),
        "status": "active",
        "reasons": reasons or ["Monitor created."],
        "events": [
            {
                "id": "EV1",
                "type": "open",
                "summary": "Monitor opened.",
                "result": "pass",
                "created_at": now,
            }
        ],
    }
    save_monitor(data)
    return data


def update_monitor(
    monitor_id: str,
    *,
    score: int | None = None,
    delta: int = 0,
    summary: str | None = None,
    result: str = "pass",
    reason: str | None = None,
    status: str | None = None,
    group: str | None = None,
    conversation: str | None = None,
) -> dict[str, Any]:
    data = load_monitor(monitor_id)
    if score is None:
        score = int(data.get("score", 0)) + delta
    score = clamp_score(score)
    data["score"] = score
    data["band"] = band_for(score)
    if status:
        data["status"] = status
    if group:
        data["group"] = group
    if conversation:
        data["conversation"] = conversation
    if reason:
        data.setdefault("reasons", []).insert(0, reason)
        data["reasons"] = data["reasons"][:8]
    if summary:
        event = {
            "id": next_id(data.setdefault("events", []), "EV"),
            "type": "update",
            "summary": summary,
            "result": result,
            "created_at": utc_now(),
        }
        data["events"].append(event)
        data["events"] = data["events"][-40:]
    save_monitor(data)
    return data


def close_monitor(monitor_id: str) -> dict[str, Any]:
    data = update_monitor(monitor_id, status="closed", summary="Monitor closed.", reason="Closed by user.")
    return data


def launch_widget(monitor_id: str, *, x: int | None = None, y: int | None = None) -> subprocess.Popen[Any]:
    args = [sys.executable, "-m", "hulun_guard.widget", "--id", monitor_id]
    if x is not None:
        args.extend(["--x", str(x)])
    if y is not None:
        args.extend(["--y", str(y)])
    kwargs: dict[str, Any] = {}
    env = os.environ.copy()
    src_dir = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    kwargs["env"] = env
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(args, cwd=str(Path(__file__).resolve().parents[2]), **kwargs)


def group_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("status") == "closed":
            continue
        groups.setdefault(item.get("group") or "default", []).append(item)
    summary: dict[str, dict[str, Any]] = {}
    for group, monitors in groups.items():
        if not monitors:
            continue
        score = round(sum(int(m.get("score", 0)) for m in monitors) / len(monitors))
        summary[group] = {"score": score, "band": band_for(score), "count": len(monitors)}
    return summary
