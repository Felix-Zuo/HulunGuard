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
            for scenario in payload["scenarios"]:
                self.assertEqual(scenario["expected"], scenario["band"], scenario["scenario"])
            self.assertTrue((Path(tmp) / ".hulun" / "validation_report.md").exists())

    def test_usability_commands_doctor_quickstart_and_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "quickstart", "--json")
            self.assertEqual(code, 0)
            quickstart = json.loads(out)
            self.assertIn("commands", quickstart)
            self.assertTrue(any(" init " in command for command in quickstart["commands"]))

            code, out = self.run_cli("--root", tmp, "doctor", "--json")
            self.assertEqual(code, 0)
            doctor = json.loads(out)
            self.assertEqual(doctor["result"], "warn")

            code, out = self.run_cli("--root", tmp, "benchmark", "--events", "200", "--json")
            self.assertEqual(code, 0)
            benchmark = json.loads(out)
            self.assertEqual(benchmark["events"], 200)
            self.assertGreater(benchmark["events_per_second"], 0)
            self.assertTrue((Path(tmp) / ".hulun" / "benchmark_report.json").exists())

    def test_ingest_streams_jsonl_without_echoing_all_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace.jsonl"
            trace.write_text(
                "\n".join(
                    json.dumps({"type": "summary", "phase": "summarize", "summary": f"summary {idx}"})
                    for idx in range(25)
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "import a long trace",
                    "--criterion",
                    "trace imports",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "ingest", "--file", str(trace), "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["imported"], 25)
            self.assertNotIn("events", payload)
            code, out = self.run_cli("--root", tmp, "status", "--json")
            self.assertEqual(code, 0)
            status = json.loads(out)
            self.assertEqual(status["events"], 26)

    def test_conversation_runtime_tracks_user_challenge_and_pending_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                code, out = self.run_cli(
                    "--root",
                    tmp,
                    "conversation",
                    "start",
                    "--name",
                    "codex-live-test",
                    "--group",
                    "tests",
                    "--monitor",
                    "--json",
                )
                self.assertEqual(code, 0)
                conversation = json.loads(out)
                self.assertTrue(conversation["id"].startswith("C"))
                self.assertTrue(conversation["monitor_id"].startswith("M"))

                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "user_challenge",
                    "--summary",
                    "User says the monitor is not actually watching the conversation.",
                    "--json",
                )
                self.assertEqual(code, 0)
                risk = json.loads(out)["risk"]
                self.assertGreater(risk["components"]["user_challenge"], 0)

                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "tool_call",
                    "--summary",
                    "Run pytest.",
                    "--phase",
                    "verify",
                    "--action-key",
                    "pytest",
                    "--json",
                )
                self.assertEqual(code, 0)
                risk = json.loads(out)["risk"]
                self.assertGreater(risk["components"]["pending_tools"], 0)

                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "tool_result",
                    "--summary",
                    "pytest passed.",
                    "--phase",
                    "verify",
                    "--action-key",
                    "pytest",
                    "--json",
                )
                self.assertEqual(code, 0)
                risk = json.loads(out)["risk"]
                self.assertEqual(risk["components"]["pending_tools"], 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

    def test_conversation_final_gate_calibrates_when_tools_are_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                code, out = self.run_cli(
                    "--root",
                    tmp,
                    "conversation",
                    "start",
                    "--name",
                    "pending-final-test",
                    "--group",
                    "tests",
                    "--json",
                )
                self.assertEqual(code, 0)
                conversation = json.loads(out)

                self.assertEqual(
                    self.run_cli(
                        "conversation",
                        "event",
                        "--id",
                        conversation["id"],
                        "--type",
                        "tool_call",
                        "--summary",
                        "Run pytest.",
                        "--phase",
                        "verify",
                        "--action-key",
                        "pytest",
                    )[0],
                    0,
                )
                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "final_attempt",
                    "--summary",
                    "Done and verified.",
                    "--phase",
                    "final",
                    "--claim",
                    "done and verified",
                    "--json",
                )
                self.assertEqual(code, 0)
                risk = json.loads(out)["risk"]
                self.assertEqual(risk["band"], "yellow")
                self.assertEqual(risk["required_action"], "calibrate")
                self.assertGreater(risk["components"]["final_gate"], 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

    def test_conversation_final_gate_blocks_after_unresolved_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                code, out = self.run_cli(
                    "--root",
                    tmp,
                    "conversation",
                    "start",
                    "--name",
                    "failure-final-test",
                    "--group",
                    "tests",
                    "--json",
                )
                self.assertEqual(code, 0)
                conversation = json.loads(out)
                for _idx in range(3):
                    self.assertEqual(
                        self.run_cli(
                            "conversation",
                            "event",
                            "--id",
                            conversation["id"],
                            "--type",
                            "tool_result",
                            "--summary",
                            "pytest failed.",
                            "--phase",
                            "verify",
                            "--result",
                            "fail",
                            "--action-key",
                            "pytest",
                        )[0],
                        0,
                    )

                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "final_attempt",
                    "--summary",
                    "Tests are fixed and verified.",
                    "--phase",
                    "final",
                    "--claim",
                    "fixed and verified",
                    "--json",
                )
                self.assertEqual(code, 0)
                risk = json.loads(out)["risk"]
                self.assertEqual(risk["band"], "red")
                self.assertEqual(risk["required_action"], "block_final")
                self.assertGreater(risk["components"]["unresolved_failures"], 0)
                self.assertGreater(risk["components"]["final_gate"], 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
