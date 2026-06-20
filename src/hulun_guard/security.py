from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import MAX_TRACE_BYTES
from .schemas import THREAT_MODEL_CHECK_SCHEMA
from .util import utc_now

THREAT_MODEL_DOC = Path("docs/THREAT_MODEL.md")
PACKAGED_THREAT_MODEL_DOC = Path(__file__).with_name("security_docs") / "THREAT_MODEL.md"
MAX_ALLOWED_TRACE_BYTES = 10 * 1024 * 1024

REQUIRED_LINK_FILES = (
    Path("README.md"),
    Path("SECURITY.md"),
    Path("RELEASING.md"),
    Path("docs/SUPPLY_CHAIN.md"),
    Path("docs/RELEASE_POLICY.md"),
)

REQUIRED_SECTIONS = (
    "# HulunGuard Threat Model",
    "## Security Boundary",
    "## Local Data",
    "## Remote Behavior",
    "## Adapter Inputs",
    "## Sensitive Data",
    "## Retention And Cleanup",
    "## Threat Scenarios",
    "## Safe Usage Modes",
    "## Release Rules",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() and path.is_file() else ""


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "ok" if passed else "error", "detail": detail}


def _threat_model_source(root: Path) -> tuple[Path, str]:
    source_doc = root / THREAT_MODEL_DOC
    if source_doc.exists() and source_doc.is_file():
        return source_doc, _read_text(source_doc)
    return PACKAGED_THREAT_MODEL_DOC, _read_text(PACKAGED_THREAT_MODEL_DOC)


def _is_hulunguard_source_checkout(root: Path) -> bool:
    return (root / "pyproject.toml").exists() and (root / "src" / "hulun_guard").is_dir()


def run_threat_model_check(root: Path) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    threat_model_path, threat_model_text = _threat_model_source(root)

    checks.append(_check("threat_model_doc", bool(threat_model_text), str(threat_model_path)))
    for section in REQUIRED_SECTIONS:
        checks.append(_check(f"section:{section}", section in threat_model_text, section))

    link_target = THREAT_MODEL_DOC.as_posix()
    if _is_hulunguard_source_checkout(root):
        for relative_path in REQUIRED_LINK_FILES:
            text = _read_text(root / relative_path)
            checks.append(_check(f"link:{relative_path.as_posix()}", link_target in text, f"{relative_path.as_posix()} links {link_target}"))
    else:
        checks.append(_check("release_doc_links", True, "Skipped outside a HulunGuard source checkout."))

    source_doc = root / THREAT_MODEL_DOC
    if source_doc.exists() and PACKAGED_THREAT_MODEL_DOC.exists():
        checks.append(
            _check(
                "packaged_threat_model_sync",
                _read_text(source_doc) == _read_text(PACKAGED_THREAT_MODEL_DOC),
                "Package threat model copy matches docs/THREAT_MODEL.md.",
            )
        )

    trace_limit_ok = 0 < MAX_TRACE_BYTES <= MAX_ALLOWED_TRACE_BYTES
    checks.append(
        _check(
            "trace_size_cap",
            trace_limit_ok,
            f"MAX_TRACE_BYTES={MAX_TRACE_BYTES}, allowed_max={MAX_ALLOWED_TRACE_BYTES}",
        )
    )

    failures = [check for check in checks if check["status"] != "ok"]
    return {
        "schema": THREAT_MODEL_CHECK_SCHEMA,
        "generated_at": utc_now(),
        "root": str(root),
        "document": str(threat_model_path),
        "checks": checks,
        "gate": {"passed": not failures, "failure_count": len(failures), "failures": failures},
    }


def threat_model_check_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
