from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path
from typing import Any


class ArtifactSmokeError(RuntimeError):
    """Raised when a release artifact fails the clean-environment smoke test."""


def project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ArtifactSmokeError(f"Cannot find project.version in {pyproject}")
    return match.group(1)


def require_file(path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise ArtifactSmokeError(f"Missing release artifact: {path}")
    return path


def require_archive_members(archive_path: Path, members: set[str], *, archive_type: str) -> None:
    if archive_type == "wheel":
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
    elif archive_type == "sdist":
        with tarfile.open(archive_path, "r:gz") as archive:
            names = set(archive.getnames())
    else:
        raise ArtifactSmokeError(f"Unsupported archive type: {archive_type}")

    missing = sorted(member for member in members if member not in names)
    if missing:
        raise ArtifactSmokeError(f"{archive_path.name} is missing archive members: {', '.join(missing)}")


def python_executable(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def script_executable(venv_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def clean_env(tmp_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["HULUN_HOME"] = str(tmp_root / "hulun-home")
    env["PYTHONUTF8"] = "1"
    return env


def run_command(command: list[str], *, cwd: Path, env: dict[str, str], input_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        rendered = " ".join(command)
        raise ArtifactSmokeError(
            f"Command failed with exit code {result.returncode}: {rendered}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def run_json_command(command: list[str], *, cwd: Path, env: dict[str, str], input_text: str | None = None) -> dict[str, Any]:
    output = run_command(command, cwd=cwd, env=env, input_text=input_text)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ArtifactSmokeError(f"Expected JSON from {' '.join(command)}: {exc}\n{output}") from exc
    if not isinstance(payload, dict):
        raise ArtifactSmokeError(f"Expected JSON object from {' '.join(command)}")
    return payload


def verify_installed_commands(
    python_path: Path,
    hulun_path: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    version: str,
    release_asset_dir: Path,
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []

    module_version = run_command([str(python_path), "-m", "hulun_guard", "--version"], cwd=cwd, env=env).strip()
    if version not in module_version:
        raise ArtifactSmokeError(f"Installed module version mismatch: {module_version}, expected {version}")
    commands.append({"name": "python -m hulun_guard --version", "status": "ok", "detail": module_version})

    script_version = run_command([str(hulun_path), "--version"], cwd=cwd, env=env).strip()
    if version not in script_version:
        raise ArtifactSmokeError(f"Installed console script version mismatch: {script_version}, expected {version}")
    commands.append({"name": "hulun --version", "status": "ok", "detail": script_version})

    doctor = run_json_command([str(hulun_path), "doctor", "--json"], cwd=cwd, env=env)
    if doctor.get("schema") != "hulun.doctor.v1":
        raise ArtifactSmokeError("doctor --json returned an unexpected schema")
    commands.append({"name": "hulun doctor --json", "status": "ok", "detail": doctor.get("result")})

    validation = run_json_command([str(hulun_path), "validate", "--json"], cwd=cwd, env=env)
    if validation.get("passes") != validation.get("total"):
        raise ArtifactSmokeError("validate --json did not pass every scenario")
    commands.append({"name": "hulun validate --json", "status": "ok", "detail": f"{validation.get('passes')} / {validation.get('total')}"})

    schema = run_json_command([str(hulun_path), "schema-check", "--json"], cwd=cwd, env=env)
    if not schema.get("gate", {}).get("passed"):
        raise ArtifactSmokeError("schema-check --json failed from the installed wheel")
    commands.append({"name": "hulun schema-check --json", "status": "ok", "detail": schema.get("fixture_dir")})

    threat_model = run_json_command([str(hulun_path), "threat-model-check", "--json"], cwd=cwd, env=env)
    if not threat_model.get("gate", {}).get("passed"):
        raise ArtifactSmokeError("threat-model-check --json failed from the installed wheel")
    commands.append({"name": "hulun threat-model-check --json", "status": "ok", "detail": threat_model.get("document")})

    compatibility = run_json_command([str(hulun_path), "compatibility", "--json"], cwd=cwd, env=env)
    if int(compatibility.get("direct_or_standard_count", 0)) < 13:
        raise ArtifactSmokeError("compatibility --json reported insufficient direct or standard coverage")
    commands.append({"name": "hulun compatibility --json", "status": "ok", "detail": f"{compatibility.get('entry_count')} agents"})

    onboarding_dir = cwd / "onboarding"
    onboarding = run_json_command([str(hulun_path), "onboard", "--agent", "langgraph", "--output", str(onboarding_dir), "--json"], cwd=cwd, env=env)
    if not onboarding.get("gate", {}).get("passed") or onboarding.get("verified_count") != 1:
        raise ArtifactSmokeError("onboard --agent langgraph failed from the installed wheel")
    commands.append({"name": "hulun onboard --agent langgraph --json", "status": "ok", "detail": str(onboarding_dir)})

    collector_root = cwd / "collector-root"
    collector = run_json_command([str(hulun_path), "--root", str(collector_root), "collector", "smoke", "--json"], cwd=cwd, env=env)
    if collector.get("schema") != "hulun.collector.v1" or not collector.get("gate", {}).get("passed"):
        raise ArtifactSmokeError("collector smoke failed from the installed wheel")
    managed_collector_root = cwd / "managed-collector-root"
    managed_collector = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "smoke", "--managed", "--scan", "--init-if-missing", "--json"],
        cwd=cwd,
        env=env,
    )
    if (
        managed_collector.get("schema") != "hulun.collector.v1"
        or not managed_collector.get("gate", {}).get("passed")
        or not managed_collector.get("managed_flush", {}).get("scanned")
    ):
        raise ArtifactSmokeError("managed collector smoke failed from the installed wheel")
    collector_status = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "status", "--require-status-file", "--json"],
        cwd=cwd,
        env=env,
    )
    if collector_status.get("schema") != "hulun.collector.v1" or not collector_status.get("gate", {}).get("passed"):
        raise ArtifactSmokeError("collector status failed from the installed wheel")
    collector_metrics = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "metrics", "--require-status-file", "--json"],
        cwd=cwd,
        env=env,
    )
    if (
        collector_metrics.get("schema") != "hulun.collector.v1"
        or collector_metrics.get("operation") != "metrics"
        or not collector_metrics.get("gate", {}).get("passed")
        or "hulun_collector_up 1" not in str(collector_metrics.get("text") or "")
    ):
        raise ArtifactSmokeError("collector metrics failed from the installed wheel")
    alert_rule_dir = cwd / "collector-alert-rules"
    alert_rules = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "alert-rules", "--output", str(alert_rule_dir), "--force", "--json"],
        cwd=cwd,
        env=env,
    )
    if (
        alert_rules.get("schema") != "hulun.collector.v1"
        or alert_rules.get("operation") != "alert_rules"
        or len(alert_rules.get("files", [])) < 2
        or "HulunCollectorGateFailing" not in str(alert_rules.get("text") or "")
    ):
        raise ArtifactSmokeError("collector alert-rules failed from the installed wheel")
    service_template_dir = cwd / "collector-service-templates"
    service_template = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "service-template", "--output", str(service_template_dir), "--force", "--json"],
        cwd=cwd,
        env=env,
    )
    if service_template.get("schema") != "hulun.collector.v1" or len(service_template.get("files", [])) < 4:
        raise ArtifactSmokeError("collector service-template failed from the installed wheel")
    service_lifecycle_dir = cwd / "collector-service-lifecycle"
    service_lifecycle = run_json_command(
        [str(hulun_path), "--root", str(managed_collector_root), "collector", "service-lifecycle", "--output", str(service_lifecycle_dir), "--force", "--json"],
        cwd=cwd,
        env=env,
    )
    if (
        service_lifecycle.get("schema") != "hulun.collector.v1"
        or service_lifecycle.get("operation") != "service_lifecycle"
        or len(service_lifecycle.get("files", [])) < 6
        or "uninstall" not in service_lifecycle.get("actions", [])
    ):
        raise ArtifactSmokeError("collector service-lifecycle failed from the installed wheel")
    commands.append({"name": "hulun collector smoke --json", "status": "ok", "detail": str(collector_root)})
    commands.append({"name": "hulun collector smoke --managed --scan --json", "status": "ok", "detail": str(managed_collector_root)})
    commands.append({"name": "hulun collector status --json", "status": "ok", "detail": str(managed_collector_root)})
    commands.append({"name": "hulun collector metrics --json", "status": "ok", "detail": str(managed_collector_root)})
    commands.append({"name": "hulun collector alert-rules --json", "status": "ok", "detail": str(alert_rule_dir)})
    commands.append({"name": "hulun collector service-template --json", "status": "ok", "detail": str(service_template_dir)})
    commands.append({"name": "hulun collector service-lifecycle --json", "status": "ok", "detail": str(service_lifecycle_dir)})

    batch_root = cwd / "batch-root"
    batch_root.mkdir()
    batch_enqueue = run_json_command(
        [
            str(hulun_path),
            "--root",
            str(batch_root),
            "batch",
            "enqueue",
            "--type",
            "tool_result",
            "--phase",
            "verify",
            "--summary",
            "installed batch smoke passed",
            "--result",
            "pass",
            "--json",
        ],
        cwd=cwd,
        env=env,
    )
    if batch_enqueue.get("schema") != "hulun.batch_ingest.v1" or batch_enqueue.get("queued") != 1:
        raise ArtifactSmokeError("batch enqueue failed from the installed wheel")
    batch_stdin = run_json_command(
        [
            str(hulun_path),
            "--root",
            str(batch_root),
            "batch",
            "ingest-stdin",
            "--format",
            "generic",
            "--json",
        ],
        cwd=cwd,
        env=env,
        input_text='{"type":"tool_result","phase":"verify","summary":"installed stdin smoke passed","result":"pass","action_key":"stdin-smoke"}\n',
    )
    if batch_stdin.get("schema") != "hulun.batch_ingest.v1" or batch_stdin.get("queued") != 1:
        raise ArtifactSmokeError("batch ingest-stdin failed from the installed wheel")
    batch_status = run_json_command([str(hulun_path), "--root", str(batch_root), "batch", "status", "--json"], cwd=cwd, env=env)
    if batch_status.get("queue", {}).get("pending") != 2:
        raise ArtifactSmokeError("batch status did not report the queued installed-wheel event")
    batch_flush = run_json_command(
        [str(hulun_path), "--root", str(batch_root), "batch", "flush", "--scan", "--init-if-missing", "--json"],
        cwd=cwd,
        env=env,
    )
    if batch_flush.get("imported") != 2 or batch_flush.get("queue", {}).get("pending") != 0 or "risk" not in batch_flush:
        raise ArtifactSmokeError("batch flush failed from the installed wheel")
    commands.append({"name": "hulun batch enqueue/ingest-stdin/status/flush", "status": "ok", "detail": str(batch_root)})

    release_verify = run_json_command([str(hulun_path), "release-verify", "--asset-dir", str(release_asset_dir), "--skip-attestation", "--json"], cwd=cwd, env=env)
    if release_verify.get("schema") != "hulun.github_release_verification.v1" or not release_verify.get("gate", {}).get("passed"):
        raise ArtifactSmokeError("release-verify --asset-dir failed from the installed wheel")
    commands.append({"name": "hulun release-verify --asset-dir --json", "status": "ok", "detail": release_verify.get("tag")})

    return commands


def verify_artifacts(root: Path, dist_dir: Path, version: str) -> dict[str, Any]:
    wheel = require_file(dist_dir / f"hulun_guard-{version}-py3-none-any.whl")
    sdist = require_file(dist_dir / f"hulun_guard-{version}.tar.gz")
    sbom = require_file(dist_dir / f"hulun_guard-{version}-sbom.cdx.json")
    checksums = require_file(dist_dir / "SHA256SUMS")

    require_archive_members(
        wheel,
        {
            "hulun_guard/__init__.py",
            "hulun_guard/cli.py",
            "hulun_guard/collector.py",
            "hulun_guard/queue.py",
            "hulun_guard/release_metadata.py",
            "hulun_guard/release_verification.py",
            "hulun_guard/schema_fixtures/batch_ingest_v1.json",
            "hulun_guard/schema_fixtures/collector_v1.json",
            "hulun_guard/schema_fixtures/legacy_state_v0.json",
            "hulun_guard/security_docs/THREAT_MODEL.md",
            f"hulun_guard-{version}.dist-info/METADATA",
            f"hulun_guard-{version}.dist-info/entry_points.txt",
        },
        archive_type="wheel",
    )
    require_archive_members(
        sdist,
        {
            f"hulun_guard-{version}/pyproject.toml",
            f"hulun_guard-{version}/README.md",
            f"hulun_guard-{version}/LICENSE",
            f"hulun_guard-{version}/src/hulun_guard/cli.py",
            f"hulun_guard-{version}/src/hulun_guard/collector.py",
            f"hulun_guard-{version}/src/hulun_guard/queue.py",
            f"hulun_guard-{version}/src/hulun_guard/release_metadata.py",
            f"hulun_guard-{version}/src/hulun_guard/release_verification.py",
            f"hulun_guard-{version}/src/hulun_guard/schema_fixtures/batch_ingest_v1.json",
            f"hulun_guard-{version}/src/hulun_guard/schema_fixtures/collector_v1.json",
            f"hulun_guard-{version}/tests/test_collector.py",
            f"hulun_guard-{version}/tests/test_hulun_guard.py",
        },
        archive_type="sdist",
    )

    with tempfile.TemporaryDirectory(prefix="hulun-artifact-smoke-") as tmp:
        tmp_root = Path(tmp).resolve()
        venv_dir = tmp_root / "venv"
        smoke_root = tmp_root / "smoke-root"
        smoke_root.mkdir()
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        python_path = python_executable(venv_dir)
        hulun_path = script_executable(venv_dir, "hulun")
        env = clean_env(tmp_root)

        run_command(
            [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)],
            cwd=smoke_root,
            env=env,
        )
        run_command([str(python_path), "-m", "pip", "check"], cwd=smoke_root, env=env)
        if not hulun_path.exists():
            raise ArtifactSmokeError(f"Missing console script after install: {hulun_path}")
        dist_link = tmp_root / "dist"
        dist_link.mkdir()
        for artifact in dist_dir.iterdir():
            if artifact.is_file():
                target = dist_link / artifact.name
                target.write_bytes(artifact.read_bytes())
        commands = verify_installed_commands(python_path, hulun_path, cwd=smoke_root, env=env, version=version, release_asset_dir=dist_link)

    return {
        "version": version,
        "dist": str(dist_dir),
        "wheel": {"path": str(wheel), "size": wheel.stat().st_size},
        "sdist": {"path": str(sdist), "size": sdist.stat().st_size},
        "metadata": {
            "sbom": {"path": str(sbom), "size": sbom.stat().st_size},
            "checksums": {"path": str(checksums), "size": checksums.stat().st_size},
        },
        "commands": commands,
        "gate": {"passed": True, "failure_count": 0, "failures": []},
        "root": str(root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify HulunGuard release artifacts and installed CLI behavior in a clean environment.")
    parser.add_argument("--dist", default="dist", help="Directory containing built wheel, sdist, SBOM, and SHA256SUMS artifacts.")
    parser.add_argument("--version", help="Expected package version. Defaults to project.version from pyproject.toml.")
    parser.add_argument("--json", action="store_true", help="Print the verification report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    version = args.version or project_version(root)
    dist_dir = Path(args.dist)
    dist_dir = dist_dir if dist_dir.is_absolute() else root / dist_dir

    try:
        report = verify_artifacts(root, dist_dir.resolve(), version)
    except ArtifactSmokeError as exc:
        if args.json:
            print(json.dumps({"version": version, "gate": {"passed": False, "failures": [str(exc)]}}, indent=2))
        else:
            print(f"HulunGuard release artifact smoke failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"HulunGuard release artifact smoke passed: {version}")
        print(f"Wheel: {report['wheel']['path']}")
        print(f"Sdist: {report['sdist']['path']}")
        print(f"Installed command checks: {len(report['commands'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
