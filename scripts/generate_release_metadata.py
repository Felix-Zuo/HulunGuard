from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import uuid
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

CHECKSUM_FILE = "SHA256SUMS"
SBOM_SUFFIX = "sbom.cdx.json"
CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.6.schema.json"


class ReleaseMetadataError(RuntimeError):
    """Raised when release metadata cannot be generated or verified."""


def project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ReleaseMetadataError(f"Cannot find project.version in {pyproject}")
    return match.group(1)


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_artifacts(dist_dir: Path, version: str) -> list[Path]:
    artifacts = [
        dist_dir / f"hulun_guard-{version}-py3-none-any.whl",
        dist_dir / f"hulun_guard-{version}.tar.gz",
    ]
    missing = [str(path) for path in artifacts if not path.exists() or not path.is_file()]
    if missing:
        raise ReleaseMetadataError(f"Missing release artifacts: {', '.join(missing)}")
    return artifacts


def sbom_path(dist_dir: Path, version: str) -> Path:
    return dist_dir / f"hulun_guard-{version}-{SBOM_SUFFIX}"


def parse_wheel_metadata(wheel_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_name = next((name for name in archive.namelist() if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise ReleaseMetadataError(f"Wheel metadata not found: {wheel_path}")
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
    return {
        "name": metadata.get("Name") or "hulun-guard",
        "version": metadata.get("Version") or "",
        "summary": metadata.get("Summary") or "",
        "requires_python": metadata.get("Requires-Python") or "",
        "requires_dist": metadata.get_all("Requires-Dist") or [],
        "license": metadata.get("License-Expression") or metadata.get("License") or "MIT",
    }


def pypi_purl(name: str, version: str) -> str:
    return f"pkg:pypi/{name.replace('_', '-').lower()}@{version}"


def artifact_component(path: Path) -> dict[str, Any]:
    return {
        "type": "file",
        "bom-ref": f"release-artifact:{path.name}",
        "name": path.name,
        "hashes": [{"alg": "SHA-256", "content": sha256_hex(path)}],
        "properties": [
            {"name": "hulunguard:release-asset", "value": "true"},
            {"name": "hulunguard:size-bytes", "value": str(path.stat().st_size)},
        ],
    }


def dependency_components(requirements: list[str]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for requirement in sorted(requirements):
        if "extra ==" in requirement.lower():
            continue
        name = re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0].strip()
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "bom-ref": f"dependency:{name.lower()}",
                "name": name,
                "purl": f"pkg:pypi/{name.lower()}",
                "properties": [{"name": "hulunguard:declared-requirement", "value": requirement}],
            }
        )
    return components


def build_sbom(*, version: str, wheel_metadata: dict[str, Any], artifacts: list[Path]) -> dict[str, Any]:
    package_name = str(wheel_metadata["name"])
    package_ref = pypi_purl(package_name, version)
    artifact_hashes = "|".join(f"{path.name}:{sha256_hex(path)}" for path in artifacts)
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/Felix-Zuo/HulunGuard/releases/tag/v{version}|{artifact_hashes}")
    dependencies = dependency_components(list(wheel_metadata.get("requires_dist") or []))
    package_component = {
        "type": "application",
        "bom-ref": package_ref,
        "name": package_name,
        "version": version,
        "description": wheel_metadata.get("summary") or "Proof-first reliability guard for long-running AI agents.",
        "licenses": [{"license": {"id": str(wheel_metadata.get("license") or "MIT")}}],
        "purl": package_ref,
        "externalReferences": [
            {"type": "website", "url": "https://felix-zuo.github.io/HulunGuard/"},
            {"type": "vcs", "url": "https://github.com/Felix-Zuo/HulunGuard"},
            {"type": "distribution", "url": f"https://github.com/Felix-Zuo/HulunGuard/releases/tag/v{version}"},
        ],
        "properties": [
            {"name": "hulunguard:requires-python", "value": str(wheel_metadata.get("requires_python") or "")},
            {"name": "hulunguard:dependency-count", "value": str(len(dependencies))},
        ],
    }
    components = [package_component, *[artifact_component(path) for path in artifacts], *dependencies]
    return {
        "$schema": CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": package_component,
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "hulun-guard-release-metadata",
                        "version": version,
                    }
                ]
            },
        },
        "components": components,
        "dependencies": [{"ref": package_ref, "dependsOn": [component["bom-ref"] for component in dependencies]}],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_checksums(path: Path, artifacts: list[Path]) -> None:
    lines = [f"{sha256_hex(artifact)}  {artifact.name}" for artifact in sorted(artifacts, key=lambda item: item.name)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_metadata(root: Path, dist_dir: Path, version: str) -> dict[str, Any]:
    artifacts = release_artifacts(dist_dir, version)
    wheel_metadata = parse_wheel_metadata(artifacts[0])
    if str(wheel_metadata.get("version")) != version:
        raise ReleaseMetadataError(f"Wheel version mismatch: {wheel_metadata.get('version')} != {version}")

    sbom_file = sbom_path(dist_dir, version)
    write_json(sbom_file, build_sbom(version=version, wheel_metadata=wheel_metadata, artifacts=artifacts))
    checksum_file = dist_dir / CHECKSUM_FILE
    write_checksums(checksum_file, [*artifacts, sbom_file])
    return {
        "version": version,
        "dist": str(dist_dir),
        "generated": [str(sbom_file), str(checksum_file)],
        "artifacts": [str(path) for path in artifacts],
        "root": str(root),
    }


def parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ReleaseMetadataError(f"Invalid checksum line {line_number}: {line}")
        digest, name = parts
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReleaseMetadataError(f"Invalid SHA-256 digest on line {line_number}: {digest}")
        checksums[name] = digest
    return checksums


def validate_sbom(sbom_file: Path, version: str, artifacts: list[Path]) -> dict[str, Any]:
    try:
        sbom = json.loads(sbom_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseMetadataError(f"Invalid SBOM JSON: {exc}") from exc
    if not isinstance(sbom, dict):
        raise ReleaseMetadataError("SBOM must be a JSON object")
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise ReleaseMetadataError("SBOM must declare CycloneDX specVersion 1.6")
    if sbom.get("$schema") != CYCLONEDX_SCHEMA:
        raise ReleaseMetadataError("SBOM schema URI is not CycloneDX 1.6")
    components = sbom.get("components")
    if not isinstance(components, list):
        raise ReleaseMetadataError("SBOM components must be a list")
    artifact_components = {component.get("name"): component for component in components if isinstance(component, dict) and component.get("type") == "file"}
    for artifact in artifacts:
        component = artifact_components.get(artifact.name)
        if not isinstance(component, dict):
            raise ReleaseMetadataError(f"SBOM missing file component for {artifact.name}")
        hashes = component.get("hashes")
        expected = sha256_hex(artifact)
        if not isinstance(hashes, list) or {"alg": "SHA-256", "content": expected} not in hashes:
            raise ReleaseMetadataError(f"SBOM hash mismatch for {artifact.name}")
    if f"@{version}" not in json.dumps(sbom, ensure_ascii=False):
        raise ReleaseMetadataError(f"SBOM does not reference package version {version}")
    return sbom


def verify_metadata(dist_dir: Path, version: str) -> dict[str, Any]:
    artifacts = release_artifacts(dist_dir, version)
    sbom_file = sbom_path(dist_dir, version)
    checksum_file = dist_dir / CHECKSUM_FILE
    if not sbom_file.exists():
        raise ReleaseMetadataError(f"Missing SBOM: {sbom_file}")
    if not checksum_file.exists():
        raise ReleaseMetadataError(f"Missing checksum file: {checksum_file}")

    checksums = parse_checksums(checksum_file)
    required = [*artifacts, sbom_file]
    for path in required:
        actual = sha256_hex(path)
        expected = checksums.get(path.name)
        if expected != actual:
            raise ReleaseMetadataError(f"Checksum mismatch for {path.name}: {expected or 'missing'} != {actual}")
    sbom = validate_sbom(sbom_file, version, artifacts)
    return {
        "version": version,
        "dist": str(dist_dir),
        "checksum_file": str(checksum_file),
        "sbom": str(sbom_file),
        "checksum_count": len(checksums),
        "component_count": len(sbom.get("components", [])),
        "gate": {"passed": True, "failure_count": 0, "failures": []},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and verify HulunGuard release checksum and SBOM metadata.")
    parser.add_argument("--dist", default="dist", help="Directory containing built release artifacts.")
    parser.add_argument("--version", help="Expected package version. Defaults to project.version from pyproject.toml.")
    parser.add_argument("--verify", action="store_true", help="Verify metadata after generation.")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing metadata without regenerating it.")
    parser.add_argument("--json", action="store_true", help="Print the metadata report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    version = args.version or project_version(root)
    dist_dir = Path(args.dist)
    dist_dir = dist_dir if dist_dir.is_absolute() else root / dist_dir
    dist_dir = dist_dir.resolve()

    try:
        generated = None if args.verify_only else generate_metadata(root, dist_dir, version)
        verified = verify_metadata(dist_dir, version) if args.verify or args.verify_only else None
    except ReleaseMetadataError as exc:
        if args.json:
            print(json.dumps({"version": version, "gate": {"passed": False, "failures": [str(exc)]}}, indent=2))
        else:
            print(f"HulunGuard release metadata failed: {exc}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "version": version,
        "dist": str(dist_dir),
        "generated": generated,
        "verified": verified,
        "gate": {"passed": True, "failure_count": 0, "failures": []},
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        action = "verified" if args.verify_only else "generated"
        if args.verify:
            action += " and verified"
        print(f"HulunGuard release metadata {action}: {version}")
        if generated:
            for path in generated["generated"]:
                print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
