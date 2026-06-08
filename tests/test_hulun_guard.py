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

    def test_observe_surfaces_slop_index_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "ship a proof-backed agent monitor",
                    "--criterion",
                    "final answer is blocked when evidence is missing",
                )[0],
                0,
            )

            code, out = self.run_cli(
                "--root",
                tmp,
                "observe",
                "--type",
                "final_attempt",
                "--summary",
                "Everything is completed and verified.",
                "--phase",
                "final",
                "--claim",
                "completed and verified",
                "--prompt-tokens",
                "9000",
                "--completion-tokens",
                "5000",
                "--cost",
                "6.5",
                "--latency-ms",
                "70000",
                "--source-platform",
                "manual",
                "--scan",
                "--json",
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            risk = payload["risk"]
            components = risk["components"]
            self.assertEqual(risk["slop_index"], risk["score"])
            self.assertGreater(components["claim_overhang"], 0)
            self.assertGreater(components["phase_disorder"], 0)
            self.assertGreater(components["cost_pressure"], 0)
            self.assertIn("Completion or verification claims outpace evidence coverage", "\n".join(risk["reasons"]))

    def test_observe_accepts_evidence_backed_final_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "ship a proof-backed monitor",
                    "--criterion",
                    "final claim has evidence",
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "record-evidence",
                    "--kind",
                    "test",
                    "--summary",
                    "pytest passed",
                    "--command",
                    "python -m pytest -q",
                )[0],
                0,
            )
            self.assertEqual(self.run_cli("--root", tmp, "set-criterion", "--id", "C1", "--status", "done", "--evidence", "E1")[0], 0)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "observe",
                    "--type",
                    "final_attempt",
                    "--phase",
                    "final",
                    "--summary",
                    "Completed and verified with evidence E1",
                    "--claim",
                    "completed and verified",
                    "--evidence",
                    "E1",
                    "--scan",
                    "--json",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "scan", "--json")
            self.assertEqual(code, 0)
            risk = json.loads(out)
            self.assertEqual(risk["components"]["claim_overhang"], 0)
            self.assertLess(risk["score"], 36)

    def test_ingest_imports_generic_trace_and_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace.json"
            trace.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "type": "tool_result",
                                "phase": "verify",
                                "summary": "pytest failed",
                                "result": "fail",
                                "action_key": "pytest",
                            },
                            {
                                "type": "final_attempt",
                                "phase": "final",
                                "summary": "Everything is complete and verified",
                                "claim": "complete and verified",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "fix tests before final",
                    "--criterion",
                    "pytest passes",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "ingest", "--file", str(trace), "--scan", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["imported"], 2)
            self.assertGreater(payload["risk"]["components"]["claim_overhang"], 0)
            self.assertGreater(payload["risk"]["components"]["unhandled_failures"], 0)

    def test_validate_runs_builtin_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "validate", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["passes"], payload["total"])
            self.assertEqual(payload["total"], 4)
            self.assertTrue((Path(tmp) / ".hulun" / "validation_report.md").exists())


if __name__ == "__main__":
    unittest.main()
