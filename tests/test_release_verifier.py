from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard.release_metadata import generate_metadata
from hulun_guard.release_verification import ReleaseVerificationError, verify_release


def cli_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) if not existing else f"{SRC}{os.pathsep}{existing}"
    return env


class GitHubReleaseVerifierTest(unittest.TestCase):
    def make_dist(self, root: Path, version: str) -> Path:
        dist = root / "dist"
        dist.mkdir()
        pyproject = root / "pyproject.toml"
        pyproject.write_text(f'[project]\nname = "hulun-guard"\nversion = "{version}"\n', encoding="utf-8")

        wheel = dist / f"hulun_guard-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("hulun_guard/__init__.py", f'__version__ = "{version}"\n')
            archive.writestr(
                f"hulun_guard-{version}.dist-info/METADATA",
                "\n".join(
                    [
                        "Metadata-Version: 2.4",
                        "Name: hulun-guard",
                        f"Version: {version}",
                        "Summary: Proof-first reliability guard",
                        "Requires-Python: >=3.10",
                        "License-Expression: MIT",
                        "",
                    ]
                ),
            )

        sdist = dist / f"hulun_guard-{version}.tar.gz"
        with tarfile.open(sdist, "w:gz") as archive:
            archive.add(pyproject, arcname=f"hulun_guard-{version}/pyproject.toml")

        generate_metadata(root, dist, version)
        return dist

    def test_verify_existing_asset_directory_without_attestations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)

            report = verify_release(
                tag=f"v{version}",
                repo="Felix-Zuo/HulunGuard",
                asset_dir=dist,
                download_dir=None,
                skip_attestation=True,
                gh_path="gh",
                root=root,
            )

            self.assertTrue(report["gate"]["passed"])
            self.assertFalse(report["downloaded"])
            self.assertEqual(report["checksums"]["count"], 3)
            self.assertEqual(report["sbom"]["spec_version"], "1.6")
            self.assertEqual(report["attestations"], [])

    def test_release_verify_cli_existing_asset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hulun_guard",
                    "release-verify",
                    f"v{version}",
                    "--root",
                    str(root),
                    "--asset-dir",
                    str(dist),
                    "--skip-attestation",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                env=cli_env(),
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "hulun.github_release_verification.v1")
            self.assertTrue(payload["gate"]["passed"])
            self.assertEqual(payload["checksums"]["count"], 3)

    def test_release_verify_cli_reports_schema_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)
            (dist / f"hulun_guard-{version}-sbom.cdx.json").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hulun_guard",
                    "release-verify",
                    f"v{version}",
                    "--root",
                    str(root),
                    "--asset-dir",
                    str(dist),
                    "--skip-attestation",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                env=cli_env(),
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "hulun.github_release_verification.v1")
            self.assertFalse(payload["gate"]["passed"])
            self.assertEqual(payload["gate"]["failure_count"], 1)

    def test_verify_fails_when_checksum_asset_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)
            (dist / f"hulun_guard-{version}.tar.gz").write_bytes(b"tampered")

            with self.assertRaises(ReleaseVerificationError):
                verify_release(
                    tag=f"v{version}",
                    repo="Felix-Zuo/HulunGuard",
                    asset_dir=dist,
                    download_dir=None,
                    skip_attestation=True,
                    gh_path="gh",
                    root=root,
                )

    def test_verify_fails_when_expected_asset_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)
            (dist / f"hulun_guard-{version}-sbom.cdx.json").unlink()

            with self.assertRaises(ReleaseVerificationError):
                verify_release(
                    tag=f"v{version}",
                    repo="Felix-Zuo/HulunGuard",
                    asset_dir=dist,
                    download_dir=None,
                    skip_attestation=True,
                    gh_path="gh",
                    root=root,
                )


if __name__ == "__main__":
    unittest.main()
