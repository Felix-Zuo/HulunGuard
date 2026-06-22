from __future__ import annotations

import argparse
import json
import shutil

# gh is invoked with shell=False and an argv list only.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import Any

from .release_metadata import ReleaseMetadataError, parse_checksums, project_version, sbom_path, sha256_hex, validate_sbom
from .schemas import GITHUB_RELEASE_VERIFICATION_SCHEMA
from .util import utc_now

DEFAULT_REPO = "Felix-Zuo/HulunGuard"


class ReleaseVerificationError(RuntimeError):
    """Raised when a GitHub release asset verification step fails."""


def version_from_tag(tag: str) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    if not version:
        raise ReleaseVerificationError("Release tag is empty.")
    return version


def tag_from_version(version: str) -> str:
    if not version or version == "unknown":
        raise ReleaseVerificationError("Cannot infer a release tag from an unknown package version.")
    return version if version.startswith("v") else f"v{version}"


def tag_from_project(root: Path) -> str:
    return tag_from_version(project_version(root))


def default_tag(root: Path, fallback_version: str | None = None) -> str:
    if fallback_version:
        return tag_from_version(fallback_version)
    try:
        return tag_from_project(root)
    except (OSError, ReleaseMetadataError):
        try:
            from . import __version__
        except ImportError as exc:  # pragma: no cover - defensive only
            raise ReleaseVerificationError("Cannot infer release tag from project metadata or installed package version.") from exc
        return tag_from_version(__version__)


def expected_asset_names(version: str) -> list[str]:
    return [
        f"hulun_guard-{version}-py3-none-any.whl",
        f"hulun_guard-{version}.tar.gz",
        f"hulun_guard-{version}-sbom.cdx.json",
        "SHA256SUMS",
    ]


def expected_artifact_paths(asset_dir: Path, version: str) -> list[Path]:
    return [
        asset_dir / f"hulun_guard-{version}-py3-none-any.whl",
        asset_dir / f"hulun_guard-{version}.tar.gz",
        asset_dir / f"hulun_guard-{version}-sbom.cdx.json",
    ]


def require_assets(asset_dir: Path, version: str) -> dict[str, Path]:
    missing: list[str] = []
    assets: dict[str, Path] = {}
    for name in expected_asset_names(version):
        path = asset_dir / name
        if not path.exists() or not path.is_file():
            missing.append(name)
        else:
            assets[name] = path
    if missing:
        raise ReleaseVerificationError(f"Missing expected release assets: {', '.join(missing)}")
    return assets


def run_command(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, shell=False)  # nosec B603
    if result.returncode != 0:
        raise ReleaseVerificationError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def require_gh(gh_path: str) -> str:
    resolved = shutil.which(gh_path) if not Path(gh_path).exists() else gh_path
    if not resolved:
        raise ReleaseVerificationError(f"GitHub CLI not found: {gh_path}")
    return resolved


def download_release_assets(*, repo: str, tag: str, asset_dir: Path, gh_path: str) -> None:
    gh = require_gh(gh_path)
    version = version_from_tag(tag)
    command = [
        gh,
        "release",
        "download",
        tag,
        "--repo",
        repo,
        "--dir",
        str(asset_dir),
        "--clobber",
    ]
    for name in expected_asset_names(version):
        command.extend(["--pattern", name])
    run_command(command)


def verify_checksums(asset_dir: Path, version: str) -> dict[str, Any]:
    checksum_file = asset_dir / "SHA256SUMS"
    checksums = parse_checksums(checksum_file)
    required = expected_artifact_paths(asset_dir, version)
    for path in required:
        expected = checksums.get(path.name)
        actual = sha256_hex(path)
        if expected != actual:
            raise ReleaseVerificationError(f"Checksum mismatch for {path.name}: {expected or 'missing'} != {actual}")
    return {"file": str(checksum_file), "count": len(checksums), "verified": [path.name for path in required]}


def verify_sbom(asset_dir: Path, version: str) -> dict[str, Any]:
    sbom_file = sbom_path(asset_dir, version)
    sbom = validate_sbom(sbom_file, version, expected_artifact_paths(asset_dir, version)[:2])
    return {"file": str(sbom_file), "format": sbom["bomFormat"], "spec_version": sbom["specVersion"], "component_count": len(sbom.get("components", []))}


def verify_attestations(asset_dir: Path, version: str, *, repo: str, gh_path: str) -> list[dict[str, str]]:
    gh = require_gh(gh_path)
    results: list[dict[str, str]] = []
    for name in expected_asset_names(version):
        path = asset_dir / name
        run_command([gh, "attestation", "verify", str(path), "--repo", repo])
        results.append({"asset": name, "status": "ok"})
    return results


def verify_release(
    *,
    tag: str,
    repo: str,
    asset_dir: Path | None,
    download_dir: Path | None,
    skip_attestation: bool,
    gh_path: str,
    root: Path,
) -> dict[str, Any]:
    version = version_from_tag(tag)
    temp_context: tempfile.TemporaryDirectory[str] | None = None
    downloaded = False
    try:
        if asset_dir is None:
            if download_dir is None:
                temp_context = tempfile.TemporaryDirectory(prefix="hulun-release-verify-")
                resolved_asset_dir = Path(temp_context.name).resolve()
            else:
                resolved_asset_dir = download_dir.resolve()
                resolved_asset_dir.mkdir(parents=True, exist_ok=True)
            download_release_assets(repo=repo, tag=tag, asset_dir=resolved_asset_dir, gh_path=gh_path)
            downloaded = True
        else:
            resolved_asset_dir = asset_dir.resolve()

        require_assets(resolved_asset_dir, version)
        checksum_result = verify_checksums(resolved_asset_dir, version)
        sbom_result = verify_sbom(resolved_asset_dir, version)
        attestation_result = [] if skip_attestation else verify_attestations(resolved_asset_dir, version, repo=repo, gh_path=gh_path)
        return {
            "schema": GITHUB_RELEASE_VERIFICATION_SCHEMA,
            "generated_at": utc_now(),
            "repo": repo,
            "tag": tag,
            "version": version,
            "asset_dir": str(resolved_asset_dir),
            "downloaded": downloaded,
            "checksums": checksum_result,
            "sbom": sbom_result,
            "attestations": attestation_result,
            "gate": {"passed": True, "failure_count": 0, "failures": []},
            "root": str(root),
        }
    except (ReleaseMetadataError, OSError) as exc:
        raise ReleaseVerificationError(str(exc)) from exc
    finally:
        if temp_context is not None:
            temp_context.cleanup()


def failure_report(*, repo: str, tag: str, root: Path, error: str, asset_dir: Path | None = None) -> dict[str, Any]:
    try:
        version = version_from_tag(tag)
    except ReleaseVerificationError:
        version = ""
    return {
        "schema": GITHUB_RELEASE_VERIFICATION_SCHEMA,
        "generated_at": utc_now(),
        "repo": repo,
        "tag": tag,
        "version": version,
        "asset_dir": str(asset_dir.resolve()) if asset_dir else None,
        "downloaded": False,
        "checksums": {"file": None, "count": 0, "verified": []},
        "sbom": {"file": None, "format": None, "spec_version": None, "component_count": 0},
        "attestations": [],
        "gate": {"passed": False, "failure_count": 1, "failures": [error]},
        "root": str(root),
    }


def release_verification_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify HulunGuard GitHub release assets, checksums, SBOM, and attestations.")
    parser.add_argument("tag", nargs="?", help="Release tag to verify. Defaults to v<project.version> or the installed package version.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repository. Defaults to {DEFAULT_REPO}.")
    asset_mode = parser.add_mutually_exclusive_group()
    asset_mode.add_argument("--asset-dir", help="Verify release assets already present in this directory.")
    asset_mode.add_argument("--download-dir", help="Download release assets into this directory instead of a temporary directory.")
    parser.add_argument("--skip-attestation", action="store_true", help="Skip gh attestation verification.")
    parser.add_argument("--gh", default="gh", help="GitHub CLI executable path or name.")
    parser.add_argument("--json", action="store_true", help="Print verification report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    tag = args.tag or default_tag(root)
    asset_dir = Path(args.asset_dir) if args.asset_dir else None
    download_dir = Path(args.download_dir) if args.download_dir else None
    try:
        report = verify_release(
            tag=tag,
            repo=args.repo,
            asset_dir=asset_dir,
            download_dir=download_dir,
            skip_attestation=args.skip_attestation,
            gh_path=args.gh,
            root=root,
        )
    except ReleaseVerificationError as exc:
        report = failure_report(repo=args.repo, tag=tag, root=root, error=str(exc), asset_dir=asset_dir or download_dir)
        if args.json:
            print(release_verification_json(report), end="")
        else:
            print(f"HulunGuard release verification failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(release_verification_json(report), end="")
    else:
        print(f"HulunGuard release verification passed: {report['tag']}")
        print(f"Assets: {report['asset_dir']}")
        print(f"Checksums: {report['checksums']['count']}")
        print(f"SBOM components: {report['sbom']['component_count']}")
        print(f"Attestations: {len(report['attestations'])}")
    return 0
