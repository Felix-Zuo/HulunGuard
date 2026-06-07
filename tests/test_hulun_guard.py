from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard.cli import main


class HulunGuardCliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(args))
        return code, buf.getvalue()

    def test_verify_fails_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _out = self.run_cli(
                "--root",
                tmp,
                "init",
                "--objective",
                "build a reliable long task guard",
                "--criterion",
                "guard has proof-backed verification",
                "--threshold",
                "50",
            )
            self.assertEqual(code, 0)

            code, out = self.run_cli("--root", tmp, "verify")
            self.assertEqual(code, 2)
            self.assertIn("FAIL", out)
            self.assertTrue((Path(tmp) / ".hulun" / "verification_report.md").exists())

    def test_complete_flow_passes_and_writes_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "build a reliable long task guard",
                    "--criterion",
                    "guard has proof-backed verification",
                )[0],
                0,
            )
            self.assertEqual(self.run_cli("--root", tmp, "add-step", "--text", "prove guard has verification")[0], 0)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "record-evidence",
                    "--kind",
                    "test",
                    "--summary",
                    "guard verification test evidence exists",
                    "--path",
                    ".hulun/state.json",
                )[0],
                0,
            )
            self.assertEqual(self.run_cli("--root", tmp, "set-step", "--id", "S1", "--status", "done", "--evidence", "E1")[0], 0)
            self.assertEqual(self.run_cli("--root", tmp, "set-criterion", "--id", "C1", "--status", "done", "--evidence", "E1")[0], 0)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "checkpoint",
                    "--summary",
                    "guard verification evidence is complete",
                    "--next-action",
                    "final verify",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "verify")
            self.assertEqual(code, 0, out)
            self.assertIn("PASS", out)

            code, out = self.run_cli("--root", tmp, "dashboard")
            self.assertEqual(code, 0)
            dashboard = root / ".hulun" / "dashboard.html"
            risk_file = root / ".hulun" / "risk.json"
            self.assertTrue(dashboard.exists())
            self.assertTrue(risk_file.exists())
            self.assertIn("HulunGauge", dashboard.read_text(encoding="utf-8"))
            risk = json.loads(risk_file.read_text(encoding="utf-8"))
            self.assertLess(risk["score"], 66)

    def test_monitor_board_groups_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                code, out = self.run_cli(
                    "--root",
                    tmp,
                    "open",
                    "--conversation",
                    "codex-demo",
                    "--group",
                    "factory-project",
                    "--score",
                    "42",
                    "--json",
                )
                self.assertEqual(code, 0)
                first = json.loads(out)
                self.assertEqual(first["score"], 42)
                self.assertEqual(first["band"], "yellow")

                code, out = self.run_cli(
                    "--root",
                    tmp,
                    "open",
                    "--conversation",
                    "claude-demo",
                    "--group",
                    "factory-project",
                    "--score",
                    "72",
                    "--json",
                )
                self.assertEqual(code, 0)
                second = json.loads(out)

                code, out = self.run_cli("update", "--id", first["id"], "--delta", "-20", "--summary", "Evidence added")
                self.assertEqual(code, 0)
                self.assertIn("green", out)

                code, out = self.run_cli("board", "--json")
                self.assertEqual(code, 0)
                board = json.loads(out)
                self.assertTrue(Path(board["board"]).exists())
                self.assertIn("factory-project", board["groups"])
                self.assertEqual(len(board["monitors"]), 2)
                self.assertGreaterEqual(board["groups"]["factory-project"]["score"], 40)
                self.assertLessEqual(board["groups"]["factory-project"]["score"], 80)

                code, _out = self.run_cli("close", "--id", second["id"])
                self.assertEqual(code, 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
