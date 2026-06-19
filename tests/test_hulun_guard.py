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
from hulun_guard.mcp import HulunMCPServer
from hulun_guard.sdk import HulunGuardClient


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

    def test_observe_redacts_sensitive_text_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "monitor traces without leaking secrets",
                    "--criterion",
                    "runtime observations are privacy safe",
                )[0],
                0,
            )

            code, out = self.run_cli(
                "--root",
                tmp,
                "observe",
                "--type",
                "tool_result",
                "--summary",
                "called with sk-testsecret012345678901234567890 for alice@example.com password=hunter2",
                "--ref",
                "https://example.test/run?id=123&token=secret#debug",
                "--claim",
                "email alice@example.com is safe",
                "--json",
            )
            self.assertEqual(code, 0, out)
            event = json.loads(out)
            joined = json.dumps(event, ensure_ascii=False)
            self.assertIn("[redacted:openai-key]", event["summary"])
            self.assertIn("[redacted:email]", event["summary"])
            self.assertIn("password=[redacted:secret]", event["summary"])
            self.assertNotIn("sk-testsecret", joined)
            self.assertNotIn("alice@example.com", joined)
            self.assertNotIn("hunter2", joined)
            self.assertEqual(event["refs"], ["https://example.test/run"])
            self.assertEqual(event["privacy"]["mode"], "redacted-default")
            self.assertEqual(event["privacy"]["retention_days"], 30)

    def test_ingest_withholds_trace_payload_and_fingerprints_action_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace.json"
            raw_content = "model output includes sk-testsecret012345678901234567890 and alice@example.com"
            trace.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "type": "llm_call",
                                "phase": "implement",
                                "content": raw_content,
                                "ref": "https://trace.example/session?id=abc&token=secret",
                            }
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
                    "import traces safely",
                    "--criterion",
                    "sensitive payload is not persisted",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "ingest", "--file", str(trace), "--json", "--include-events")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            event = payload["events"][0]
            joined = json.dumps(event, ensure_ascii=False)
            self.assertIn("sensitive payload withheld", event["summary"])
            self.assertNotIn(raw_content, joined)
            self.assertNotIn("sk-testsecret", joined)
            self.assertNotIn("alice@example.com", joined)
            self.assertEqual(event["action_key"].split(":")[0], "generic")
            self.assertEqual(event["refs"], ["https://trace.example/session"])
            self.assertEqual(event["privacy"]["mode"], "redacted-default")

    def test_ingest_include_sensitive_preserves_trace_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace.json"
            raw_content = "local debug prompt includes sk-testsecret012345678901234567890"
            trace.write_text(json.dumps({"events": [{"type": "llm_call", "prompt": raw_content}]}), encoding="utf-8")
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "debug a local trace",
                    "--criterion",
                    "sensitive payload can be explicitly retained",
                )[0],
                0,
            )

            code, out = self.run_cli(
                "--root",
                tmp,
                "ingest",
                "--file",
                str(trace),
                "--include-sensitive",
                "--include-events",
                "--retention-days",
                "7",
                "--json",
            )
            self.assertEqual(code, 0, out)
            event = json.loads(out)["events"][0]
            self.assertEqual(event["summary"], raw_content)
            self.assertEqual(event["privacy"]["mode"], "sensitive-opt-in")
            self.assertEqual(event["privacy"]["retention_days"], 7)

    def test_sdk_records_project_and_conversation_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                client = HulunGuardClient(tmp)
                state = client.init(
                    objective="ship a stable adapter sdk",
                    criteria=["sdk can record verified runtime observations"],
                )
                self.assertEqual(state["objective"], "ship a stable adapter sdk")

                observed = client.observe(
                    event_type="tool_result",
                    phase="verify",
                    summary="pytest passed",
                    result="pass",
                    scan=True,
                    source_platform="sdk",
                    action_key="pytest",
                )
                self.assertEqual(observed["event"]["source_platform"], "sdk")
                self.assertIn("risk", observed)
                self.assertTrue((Path(tmp) / ".hulun" / "state.json").exists())

                conversation = client.start_conversation(name="sdk-live-test", group="tests")
                pending = client.conversation_event(
                    conversation_id=conversation["id"],
                    event_type="tool_call",
                    phase="verify",
                    summary="Run pytest.",
                    action_key="pytest",
                )
                self.assertGreater(pending["risk"]["components"]["pending_tools"], 0)
                resolved = client.conversation_event(
                    conversation_id=conversation["id"],
                    event_type="tool_result",
                    phase="verify",
                    summary="pytest passed.",
                    action_key="pytest",
                )
                self.assertEqual(resolved["risk"]["components"]["pending_tools"], 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

    def test_mcp_smoke_lists_tools_and_records_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                server = HulunMCPServer(root=tmp)
                initialized = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
                self.assertEqual(initialized["result"]["serverInfo"]["name"], "hulunguard")

                listed = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                tool_names = {tool["name"] for tool in listed["result"]["tools"]}
                self.assertIn("hulun_project_init", tool_names)
                self.assertIn("hulun_conversation_event", tool_names)

                init_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "hulun_project_init",
                            "arguments": {
                                "objective": "mcp records runtime state",
                                "criteria": ["mcp observation is persisted"],
                            },
                        },
                    }
                )
                self.assertEqual(init_result["result"]["structuredContent"]["objective"], "mcp records runtime state")

                observed = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "hulun_observe",
                            "arguments": {
                                "type": "tool_result",
                                "summary": "pytest passed",
                                "phase": "verify",
                                "action_key": "pytest",
                                "scan": True,
                            },
                        },
                    }
                )
                structured = observed["result"]["structuredContent"]
                self.assertEqual(structured["event"]["source_platform"], "mcp")
                self.assertIn("risk", structured)

                started = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {
                            "name": "hulun_conversation_start",
                            "arguments": {"name": "mcp-live-test", "group": "tests"},
                        },
                    }
                )
                conversation_id = started["result"]["structuredContent"]["id"]
                event = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {
                            "name": "hulun_conversation_event",
                            "arguments": {
                                "conversation_id": conversation_id,
                                "type": "tool_call",
                                "summary": "Run pytest.",
                                "phase": "verify",
                                "action_key": "pytest",
                            },
                        },
                    }
                )
                self.assertGreater(event["result"]["structuredContent"]["risk"]["components"]["pending_tools"], 0)
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

    def test_conversation_event_redacts_sensitive_text_by_default(self) -> None:
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
                    "privacy-runtime-test",
                    "--group",
                    "tests",
                    "--json",
                )
                self.assertEqual(code, 0)
                conversation = json.loads(out)

                code, out = self.run_cli(
                    "conversation",
                    "event",
                    "--id",
                    conversation["id"],
                    "--type",
                    "tool_result",
                    "--summary",
                    "trace included token=secret123 and bob@example.com",
                    "--ref",
                    "https://example.test/run?token=secret123",
                    "--json",
                )
                self.assertEqual(code, 0, out)
                event = json.loads(out)["event"]
                joined = json.dumps(event, ensure_ascii=False)
                self.assertIn("token=[redacted:secret]", event["summary"])
                self.assertIn("[redacted:email]", event["summary"])
                self.assertNotIn("secret123", joined)
                self.assertNotIn("bob@example.com", joined)
                self.assertEqual(event["refs"], ["https://example.test/run"])
                self.assertEqual(event["privacy"]["mode"], "redacted-default")
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

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
