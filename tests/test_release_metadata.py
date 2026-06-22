from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_release_metadata import ReleaseMetadataError, generate_metadata, verify_metadata


class ReleaseMetadataTest(unittest.TestCase):
    def make_dist(self, root: Path, version: str) -> Path:
        dist = root / "dist"
        dist.mkdir()
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
                        "Requires-Dist: pytest; extra == \"dev\"",
                        "License-Expression: MIT",
                        "",
                    ]
                ),
            )
            archive.writestr(f"hulun_guard-{version}.dist-info/WHEEL", "Wheel-Version: 1.0\n")

        sdist = dist / f"hulun_guard-{version}.tar.gz"
        pyproject = root / "pyproject.toml"
        pyproject.write_text(f'[project]\nname = "hulun-guard"\nversion = "{version}"\n', encoding="utf-8")
        with tarfile.open(sdist, "w:gz") as archive:
            archive.add(pyproject, arcname=f"hulun_guard-{version}/pyproject.toml")
        return dist

    def test_generate_and_verify_release_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)

            generated = generate_metadata(root, dist, version)
            verified = verify_metadata(dist, version)

            self.assertEqual(generated["version"], version)
            self.assertTrue((dist / "SHA256SUMS").exists())
            sbom_path = dist / f"hulun_guard-{version}-sbom.cdx.json"
            self.assertTrue(sbom_path.exists())
            self.assertEqual(verified["gate"]["passed"], True)
            self.assertEqual(verified["checksum_count"], 3)
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            self.assertEqual(sbom["bomFormat"], "CycloneDX")
            self.assertEqual(sbom["specVersion"], "1.6")
            self.assertIn(f"pkg:pypi/hulun-guard@{version}", json.dumps(sbom))
            self.assertNotIn("pytest", json.dumps(sbom))
            self.assertNotIn(str(root), json.dumps(sbom))

    def test_verify_fails_when_artifact_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = "9.9.9"
            dist = self.make_dist(root, version)
            generate_metadata(root, dist, version)

            wheel = dist / f"hulun_guard-{version}-py3-none-any.whl"
            with wheel.open("ab") as handle:
                handle.write(b"tampered")

            with self.assertRaises(ReleaseMetadataError):
                verify_metadata(dist, version)


if __name__ == "__main__":
    unittest.main()
