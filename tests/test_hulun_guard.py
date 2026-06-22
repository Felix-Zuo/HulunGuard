from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard import calibration, retention, schemas
from hulun_guard.cli import main
from hulun_guard.mcp import HulunMCPServer
from hulun_guard.sdk import HulunGuardClient
from hulun_guard.storage import load_state, save_state


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

    def test_ingest_opentelemetry_genai_spans_without_payload_leakage(self) -> None:
        def attr(key: str, value: object) -> dict[str, object]:
            if isinstance(value, int):
                encoded = {"intValue": str(value)}
            else:
                encoded = {"stringValue": str(value)}
            return {"key": key, "value": encoded}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "otel-trace.json"
            secret_payload = "user prompt includes sk-testsecret012345678901234567890 and alice@example.com"
            trace.write_text(
                json.dumps(
                    {
                        "resourceSpans": [
                            {
                                "scopeSpans": [
                                    {
                                        "spans": [
                                            {
                                                "traceId": "abc123",
                                                "spanId": "span001",
                                                "name": "openai.chat",
                                                "startTimeUnixNano": "1000000000",
                                                "endTimeUnixNano": "1750000000",
                                                "attributes": [
                                                    attr("gen_ai.operation.name", "chat"),
                                                    attr("gen_ai.request.model", "gpt-4o"),
                                                    attr("gen_ai.usage.input_tokens", 1200),
                                                    attr("gen_ai.usage.output_tokens", 240),
                                                    attr("gen_ai.input.messages", secret_payload),
                                                    attr("gen_ai.output.messages", "assistant output includes alice@example.com"),
                                                ],
                                                "status": {"code": "STATUS_CODE_OK"},
                                            },
                                            {
                                                "traceId": "abc123",
                                                "spanId": "span002",
                                                "name": "tool:get_weather",
                                                "attributes": [
                                                    attr("gen_ai.tool.call.id", "call_123"),
                                                    attr("gen_ai.tool.name", "get_weather"),
                                                    attr("gen_ai.tool.call.arguments", "token=secret123"),
                                                ],
                                                "status": {"code": "STATUS_CODE_ERROR", "message": "tool failed"},
                                            },
                                        ]
                                    }
                                ]
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
                    "import otel safely",
                    "--criterion",
                    "otel spans map to observations",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "ingest", "--file", str(trace), "--format", "opentelemetry", "--include-events", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            events = payload["events"]
            joined = json.dumps(events, ensure_ascii=False)
            self.assertEqual(payload["imported"], 2)
            self.assertEqual(events[0]["type"], "llm_call")
            self.assertEqual(events[0]["source_platform"], "opentelemetry")
            self.assertEqual(events[0]["prompt_tokens"], 1200)
            self.assertEqual(events[0]["completion_tokens"], 240)
            self.assertEqual(events[0]["latency_ms"], 750)
            self.assertEqual(events[0]["refs"], ["otel:trace:abc123", "otel:span:span001"])
            self.assertEqual(events[1]["type"], "tool_result")
            self.assertEqual(events[1]["result"], "fail")
            self.assertEqual(events[1]["phase"], "recover")
            self.assertIn("OpenTelemetry GenAI span", events[0]["summary"])
            self.assertNotIn(secret_payload, joined)
            self.assertNotIn("sk-testsecret", joined)
            self.assertNotIn("alice@example.com", joined)
            self.assertNotIn("secret123", joined)

    def test_ingest_openinference_spans_without_payload_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "openinference-trace.json"
            trace.write_text(
                json.dumps(
                    [
                        {
                            "trace_id": "trace001",
                            "span_id": "spanllm",
                            "name": "chat completion",
                            "attributes": {
                                "openinference.span.kind": "LLM",
                                "llm.model_name": "gpt-4o-mini",
                                "llm.token_count.prompt": 300,
                                "llm.token_count.completion": 90,
                                "input.value": "input contains bob@example.com",
                                "output.value": "output contains sk-testsecret012345678901234567890",
                            },
                        },
                        {
                            "trace_id": "trace001",
                            "span_id": "spantool",
                            "name": "tool call",
                            "attributes": {
                                "openinference.span.kind": "TOOL",
                                "tool.name": "pytest",
                                "tool.parameters": "password=hunter2",
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "import openinference safely",
                    "--criterion",
                    "openinference spans map to observations",
                )[0],
                0,
            )

            code, out = self.run_cli("--root", tmp, "ingest", "--file", str(trace), "--format", "openinference", "--include-events", "--json")
            self.assertEqual(code, 0, out)
            events = json.loads(out)["events"]
            joined = json.dumps(events, ensure_ascii=False)
            self.assertEqual(events[0]["type"], "llm_call")
            self.assertEqual(events[0]["source_platform"], "openinference")
            self.assertEqual(events[0]["prompt_tokens"], 300)
            self.assertEqual(events[0]["completion_tokens"], 90)
            self.assertEqual(events[1]["type"], "tool_result")
            self.assertEqual(events[1]["phase"], "orchestrate")
            self.assertNotIn("bob@example.com", joined)
            self.assertNotIn("sk-testsecret", joined)
            self.assertNotIn("hunter2", joined)

    def test_export_opentelemetry_writes_redacted_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "hulun-otel.json"
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "init",
                    "--objective",
                    "export hulun events",
                    "--criterion",
                    "otel export exists",
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "observe",
                    "--type",
                    "llm_call",
                    "--phase",
                    "orchestrate",
                    "--summary",
                    "model call used sk-testsecret012345678901234567890 for alice@example.com",
                    "--prompt-tokens",
                    "55",
                    "--completion-tokens",
                    "13",
                    "--model",
                    "gpt-4o",
                )[0],
                0,
            )
            code, out = self.run_cli("--root", tmp, "export-otel", "--output", str(output), "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            exported = json.loads(output.read_text(encoding="utf-8"))
            joined = json.dumps(exported, ensure_ascii=False)
            self.assertEqual(payload["spans"], 2)
            self.assertIn("resourceSpans", exported)
            self.assertIn("hulun.event.summary", joined)
            self.assertIn("[redacted:openai-key]", joined)
            self.assertIn("[redacted:email]", joined)
            self.assertNotIn("sk-testsecret", joined)
            self.assertNotIn("alice@example.com", joined)

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

    def test_calibrate_reports_labeled_trajectory_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "calibrate", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["dataset"]["size"], 100)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["dataset"]["labels"]["healthy"], 10)
            self.assertEqual(payload["dataset"]["labels"]["unsupported-final"], 10)
            self.assertEqual(payload["dataset"]["labels"]["failure-masking"], 15)
            self.assertEqual(payload["dataset"]["labels"]["retry-loop"], 15)
            self.assertEqual(payload["dataset"]["labels"]["context-decay"], 10)
            self.assertEqual(payload["dataset"]["labels"]["polish-without-progress"], 10)
            self.assertEqual(payload["dataset"]["labels"]["cost-pressure"], 15)
            self.assertEqual(payload["dataset"]["labels"]["uncertainty"], 15)
            self.assertEqual(payload["dataset"]["source_classes"]["curated-public-safe"], 80)
            self.assertEqual(payload["dataset"]["source_classes"]["external-public-swe-agent-trajectory"], 5)
            self.assertEqual(payload["dataset"]["source_classes"]["external-public-openhands-event-log"], 5)
            self.assertEqual(payload["dataset"]["source_classes"]["external-public-opentelemetry-genai-trace"], 5)
            self.assertEqual(payload["dataset"]["source_classes"]["external-public-openinference-trace"], 5)
            self.assertEqual(payload["dataset"]["workflow_classes"]["calibration"], 80)
            self.assertEqual(payload["dataset"]["workflow_classes"]["coding"], 5)
            self.assertEqual(payload["dataset"]["workflow_classes"]["ops"], 5)
            self.assertEqual(payload["dataset"]["workflow_classes"]["artifact"], 5)
            self.assertEqual(payload["dataset"]["workflow_classes"]["research"], 5)
            self.assertEqual(payload["dataset"]["redaction_statuses"]["no-private-content"], 80)
            self.assertEqual(payload["dataset"]["redaction_statuses"]["public-schema-derived-no-private-content"], 20)
            self.assertIn("https://docs.openhands.dev/sdk/arch/events", payload["dataset"]["source_uris"])
            self.assertIn(
                "https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md",
                payload["dataset"]["source_uris"],
            )
            self.assertIn("https://opentelemetry.io/blog/2026/genai-observability/", payload["dataset"]["source_uris"])
            self.assertIn(
                "https://github.com/Arize-ai/openinference/blob/main/spec/traces.md",
                payload["dataset"]["source_uris"],
            )
            self.assertEqual(payload["gate"]["support_failures"], [])
            self.assertEqual(payload["component_support"]["cost_pressure"]["expected_positive"], 15)
            self.assertEqual(payload["component_support"]["uncertainty"]["expected_positive"], 15)
            self.assertEqual(payload["component_metrics"]["claim_overhang"]["false_negative_rate"], 0.0)
            self.assertEqual(payload["component_metrics"]["retry_loop"]["false_positive_rate"], 0.0)
            for trajectory in payload["trajectories"]:
                self.assertIn("source_class", trajectory)
                self.assertIn("workflow_class", trajectory)
                self.assertIn("label_source", trajectory)
                self.assertIn("redaction_status", trajectory)
                self.assertIn("source_uri", trajectory)
            self.assertTrue((Path(tmp) / ".hulun" / "calibration_report.md").exists())

    def test_calibrate_fails_zero_required_component_support_unless_waived(self) -> None:
        reduced_dataset = [
            item for item in calibration.build_trajectory_dataset() if "cost_pressure" not in item["expected_components"]
        ]
        with mock.patch.object(calibration, "build_trajectory_dataset", return_value=reduced_dataset):
            with mock.patch.object(calibration, "DATASET_SIZE", len(reduced_dataset)):
                result = calibration.run_trajectory_calibration()
        self.assertFalse(result["gate"]["passed"], result["gate"])
        self.assertEqual(result["gate"]["support_failures"], [
            {"component": "cost_pressure", "expected_positive": 0, "waiver": None}
        ])

        with mock.patch.object(calibration, "build_trajectory_dataset", return_value=reduced_dataset):
            with mock.patch.object(calibration, "DATASET_SIZE", len(reduced_dataset)):
                with mock.patch.object(
                    calibration,
                    "COMPONENT_SUPPORT_WAIVERS",
                    {"cost_pressure": "Covered by external calibration report."},
                ):
                    waived = calibration.run_trajectory_calibration()
        self.assertTrue(waived["gate"]["passed"], waived["gate"])
        self.assertEqual(waived["component_support"]["cost_pressure"]["waiver"], "Covered by external calibration report.")

    def test_calibration_drift_reports_baseline_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = calibration.build_calibration_baseline(
                calibration.run_trajectory_calibration(),
                baseline_id="test-baseline",
                source_version="test",
            )
            baseline_path = Path(tmp) / "baseline.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            code, out = self.run_cli("--root", tmp, "calibration-drift", "--baseline", str(baseline_path), "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["gate"]["status"], "pass")
            self.assertTrue(payload["gate"]["passed"])
            self.assertEqual(payload["gate"]["regression_count"], 0)
            self.assertEqual(payload["baseline"]["baseline_id"], "test-baseline")
            self.assertTrue((Path(tmp) / ".hulun" / "calibration_drift_report.json").exists())
            self.assertTrue((Path(tmp) / ".hulun" / "calibration_drift_report.md").exists())

    def test_calibration_drift_reports_missing_baseline_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "calibration-drift", "--baseline", "missing.json", "--json")
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertEqual(payload["error"], "baseline_not_found")
            self.assertIn("missing.json", payload["baseline"])

    def test_calibration_drift_fails_or_warns_on_regression_rationale(self) -> None:
        baseline = calibration.build_calibration_baseline(
            calibration.run_trajectory_calibration(),
            baseline_id="test-baseline",
            source_version="test",
        )
        current = calibration.run_trajectory_calibration()
        current["dataset"]["labels"]["healthy"] = 9
        current["dataset"]["source_classes"]["external-public-openhands-event-log"] = 4
        current["dataset"]["source_uris"].remove("https://docs.openhands.dev/sdk/arch/events")
        current["component_support"]["cost_pressure"]["expected_positive"] = 14
        current["component_metrics"]["cost_pressure"]["recall"] = 0.9

        failed = calibration.compare_calibration_drift(current, baseline)
        self.assertFalse(failed["gate"]["passed"])
        self.assertEqual(failed["gate"]["status"], "fail")
        self.assertGreaterEqual(failed["gate"]["regression_count"], 5)
        kinds = {regression["kind"] for regression in failed["regressions"]}
        self.assertIn("labels", kinds)
        self.assertIn("source_classes", kinds)
        self.assertIn("source_uris", kinds)
        self.assertIn("component_support.expected_positive", kinds)
        self.assertIn("component_metrics.recall", kinds)

        warned = calibration.compare_calibration_drift(current, baseline, rationale="Intentional fixture retirement.")
        self.assertTrue(warned["gate"]["passed"])
        self.assertEqual(warned["gate"]["status"], "warn")
        self.assertEqual(warned["gate"]["rationale"], "Intentional fixture retirement.")

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

            code, out = self.run_cli("--root", tmp, "doctor", "--run-validation", "--json")
            self.assertEqual(code, 0)
            doctor = json.loads(out)
            self.assertEqual(doctor["calibration"]["dataset"]["size"], 100)
            self.assertTrue(doctor["calibration"]["gate"]["passed"])
            self.assertNotIn("trajectories", doctor["calibration"])
            self.assertTrue(doctor["threat_model"]["gate"]["passed"])
            self.assertEqual(doctor["agent_compatibility"]["schema"], "hulun.agent_compatibility.v1")
            self.assertGreaterEqual(doctor["agent_compatibility"]["direct_or_standard_count"], 13)
            self.assertEqual(doctor["integration_kits"]["schema"], "hulun.integration_kit.v1")
            self.assertTrue(doctor["integration_kits"]["gate"]["passed"])
            self.assertGreaterEqual(doctor["integration_kits"]["kit_count"], 15)
            self.assertEqual(doctor["integration_kits"]["verified_count"], doctor["integration_kits"]["kit_count"])
            self.assertEqual(doctor["onboarding"]["schema"], "hulun.onboarding.v1")
            self.assertTrue(doctor["onboarding"]["gate"]["passed"])
            self.assertGreaterEqual(doctor["onboarding"]["agent_count"], 15)
            self.assertEqual(doctor["onboarding"]["verified_count"], doctor["onboarding"]["agent_count"])

            code, out = self.run_cli("--root", tmp, "benchmark", "--events", "200", "--json")
            self.assertEqual(code, 0)
            benchmark = json.loads(out)
            self.assertEqual(benchmark["events"], 200)
            self.assertGreater(benchmark["events_per_second"], 0)
            self.assertTrue((Path(tmp) / ".hulun" / "benchmark_report.json").exists())

    def test_real_world_benchmark_reports_public_safe_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "benchmark", "--suite", "real-world", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.real_world_benchmark.v1")
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["case_count"], 16)
            self.assertEqual(payload["workflow_classes"], {"artifact": 4, "coding": 4, "ops": 4, "research": 4})
            self.assertEqual(payload["redaction_statuses"], {"public-schema-derived-no-private-content": 16})
            self.assertEqual(payload["source_classes"]["public-schema-derived-langgraph-streaming"], 1)
            self.assertEqual(payload["source_classes"]["public-schema-derived-langsmith-runs"], 1)
            self.assertEqual(payload["source_classes"]["public-schema-derived-langfuse-otel"], 1)
            self.assertEqual(payload["source_classes"]["public-schema-derived-phoenix-openinference"], 1)
            self.assertEqual(payload["metrics"]["classification"]["false_positive_rate"], 0.0)
            self.assertEqual(payload["metrics"]["classification"]["false_negative_rate"], 0.0)
            self.assertEqual(payload["metrics"]["component_stability"]["rate"], 1.0)
            self.assertEqual(payload["metrics"]["component_stability"]["misses"], [])
            self.assertEqual(payload["metrics"]["component_stability"]["extras"], [])
            self.assertGreater(payload["metrics"]["scan_latency"]["max_ms"], 0)
            self.assertGreater(payload["metrics"]["fixture_size"]["total_bytes"], 0)
            self.assertTrue((Path(tmp) / ".hulun" / "real_world_benchmark_report.json").exists())
            self.assertTrue((Path(tmp) / ".hulun" / "real_world_benchmark_report.md").exists())

            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("sk-", serialized)
            self.assertNotIn("password=", serialized)
            self.assertNotIn("@example.com", serialized)

    def test_agent_compatibility_reports_mainstream_paths(self) -> None:
        code, out = self.run_cli("compatibility", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], "hulun.agent_compatibility.v1")
        self.assertGreaterEqual(payload["entry_count"], 15)
        self.assertGreaterEqual(payload["direct_or_standard_count"], 13)
        agents = {item["id"]: item for item in payload["agents"]}
        for required in [
            "openhands",
            "swe-agent",
            "langgraph",
            "langsmith",
            "langfuse",
            "phoenix",
            "opentelemetry-genai",
            "openinference",
            "autogen",
            "crewai",
            "llamaindex",
            "haystack",
            "semantic-kernel",
            "openai-agents-sdk",
            "custom-agent",
        ]:
            self.assertIn(required, agents)

        self.assertEqual(agents["openhands"]["ingest_format"], "openhands")
        self.assertEqual(agents["langgraph"]["ingest_format"], "langgraph")
        self.assertEqual(agents["autogen"]["ingest_format"], "opentelemetry")
        self.assertEqual(agents["openai-agents-sdk"]["ingest_format"], "generic")

    def test_integration_kit_generates_verified_agent_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "langgraph-kit"
            code, out = self.run_cli(
                "--root",
                tmp,
                "integration-kit",
                "--agent",
                "langgraph",
                "--output",
                str(output),
                "--verify",
                "--json",
            )
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.integration_kit.v1")
            self.assertEqual(payload["kit_count"], 1)
            self.assertEqual(payload["verified_count"], 1)
            self.assertTrue(payload["gate"]["passed"])
            kit = payload["kits"][0]
            self.assertEqual(kit["agent"]["id"], "langgraph")
            self.assertEqual(kit["agent"]["ingest_format"], "langgraph")
            self.assertTrue(kit["verification"]["passed"])
            self.assertGreaterEqual(kit["verification"]["observation_count"], 1)
            self.assertIn("tool_result", kit["verification"]["event_types"])
            for name in ["README.md", "hulun_integration.json", "run_ingest.ps1", "run_ingest.sh", "sample-langgraph.json"]:
                self.assertTrue((output / name).exists(), name)
            manifest = json.loads((output / "hulun_integration.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "hulun.integration_kit.v1")
            self.assertIn('"', manifest["ingest_command"])
            self.assertIn("--init-if-missing", manifest["ingest_command"])

            code, out = self.run_cli(
                "--root",
                tmp,
                "ingest",
                "--format",
                "langgraph",
                "--file",
                str(output / "sample-langgraph.json"),
                "--scan",
                "--init-if-missing",
                "--json",
            )
            self.assertEqual(code, 0, out)
            ingest = json.loads(out)
            self.assertEqual(ingest["imported"], kit["verification"]["observation_count"])
            self.assertIn("risk", ingest)
            state = load_state(Path(tmp))
            self.assertEqual(len(state["events"]), kit["verification"]["observation_count"])

            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("sk-", serialized)
            self.assertNotIn("password=", serialized)
            self.assertNotIn("@example.com", serialized)

    def test_integration_kit_verifies_all_supported_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "kits"
            code, out = self.run_cli(
                "--root",
                tmp,
                "integration-kit",
                "--agent",
                "all",
                "--output",
                str(output),
                "--verify",
                "--json",
            )
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.integration_kit.v1")
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertGreaterEqual(payload["kit_count"], 15)
            self.assertEqual(payload["verified_count"], payload["kit_count"])
            agent_ids = {kit["agent"]["id"] for kit in payload["kits"]}
            self.assertIn("openai-agents-sdk", agent_ids)
            self.assertIn("semantic-kernel", agent_ids)
            self.assertTrue((output / "openai-agents-sdk" / "sample-events.jsonl").exists())
            self.assertTrue((output / "semantic-kernel" / "sample-otlp.json").exists())

    def test_integration_kit_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "kit"
            code, out = self.run_cli("--root", tmp, "integration-kit", "--agent", "custom-agent", "--output", str(output), "--verify")
            self.assertEqual(code, 0, out)

            with self.assertRaises(SystemExit) as raised:
                self.run_cli("--root", tmp, "integration-kit", "--agent", "custom-agent", "--output", str(output), "--verify")
            self.assertIn("--force", str(raised.exception))

            code, out = self.run_cli("--root", tmp, "integration-kit", "--agent", "custom-agent", "--output", str(output), "--force", "--verify")
            self.assertEqual(code, 0, out)

    def test_integration_kit_rejects_file_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "not-a-directory"
            output.write_text("reserved", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                self.run_cli("--root", tmp, "integration-kit", "--agent", "custom-agent", "--output", str(output), "--verify")
            self.assertIn("not a directory", str(raised.exception))

    def test_onboard_generates_verified_agent_path_without_mutating_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "onboarding"
            code, out = self.run_cli("--root", tmp, "onboard", "--agent", "langgraph", "--output", str(output), "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.onboarding.v1")
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["agent_count"], 1)
            item = payload["agents"][0]
            self.assertEqual(item["agent"]["id"], "langgraph")
            self.assertTrue(item["verification"]["passed"])
            self.assertEqual(item["sandbox_import"]["imported"], item["verification"]["observation_count"])
            self.assertEqual(item["sandbox_import"]["risk"]["band"], "green")
            self.assertIn("--format langgraph", item["next_steps"]["real_trace_command"])
            self.assertIn("--init-if-missing", item["next_steps"]["real_trace_command"])
            self.assertTrue((output / "langgraph" / "hulun_integration.json").exists())
            self.assertFalse((root / ".hulun" / "state.json").exists())

    def test_onboard_verifies_all_supported_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "onboarding"
            code, out = self.run_cli("--root", tmp, "onboard", "--agent", "all", "--output", str(output), "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.onboarding.v1")
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertGreaterEqual(payload["agent_count"], 15)
            self.assertEqual(payload["verified_count"], payload["agent_count"])
            self.assertGreaterEqual(payload["sandbox_imported_count"], payload["agent_count"])
            agent_ids = {item["agent"]["id"] for item in payload["agents"]}
            self.assertIn("openai-agents-sdk", agent_ids)
            self.assertIn("semantic-kernel", agent_ids)

    def test_onboard_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "onboarding"
            code, out = self.run_cli("--root", tmp, "onboard", "--agent", "custom-agent", "--output", str(output), "--json")
            self.assertEqual(code, 0, out)

            with self.assertRaises(SystemExit) as raised:
                self.run_cli("--root", tmp, "onboard", "--agent", "custom-agent", "--output", str(output), "--json")
            self.assertIn("--force", str(raised.exception))

            code, out = self.run_cli("--root", tmp, "onboard", "--agent", "custom-agent", "--output", str(output), "--force", "--json")
            self.assertEqual(code, 0, out)

    def test_onboard_rejects_file_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "not-a-directory"
            output.write_text("reserved", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                self.run_cli("--root", tmp, "onboard", "--agent", "custom-agent", "--output", str(output), "--json")
            self.assertIn("not a directory", str(raised.exception))

    def test_real_world_benchmark_fails_when_fixture_size_limit_is_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "benchmark", "--suite", "real-world", "--max-case-bytes", "1", "--json")
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertFalse(payload["gate"]["passed"])
            self.assertTrue(any(failure["kind"] == "fixture_too_large" for failure in payload["gate"]["failures"]))

    def test_schema_check_migrates_legacy_fixtures(self) -> None:
        code, out = self.run_cli("schema-check", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], schemas.SCHEMA_COMPATIBILITY_SCHEMA)
        self.assertTrue(payload["gate"]["passed"])
        kinds = {item["kind"] for item in payload["fixtures"]}
        self.assertTrue({"state", "risk", "conversation", "calibration", "benchmark", "export_opentelemetry"}.issubset(kinds))

    def test_schema_check_fails_on_unsupported_future_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "future_state.json").write_text(json.dumps({"schema": "hulun.state.v99"}), encoding="utf-8")
            code, out = self.run_cli("schema-check", "--fixture-dir", str(fixture_dir), "--json")
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertFalse(payload["gate"]["passed"])
            self.assertEqual(payload["gate"]["failures"][0]["kind"], "fixture_failed")

    def test_schema_check_fails_on_empty_fixture_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("schema-check", "--fixture-dir", tmp, "--json")
            self.assertEqual(code, 2)
            payload = json.loads(out)
            self.assertFalse(payload["gate"]["passed"])
            self.assertEqual(payload["gate"]["failures"][0]["kind"], "fixture_dir_empty")

    def test_load_state_migrates_legacy_state_without_losing_privacy_or_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hulun = root / ".hulun"
            hulun.mkdir()
            legacy = schemas.DEFAULT_SCHEMA_FIXTURE_DIR / "legacy_state_v0.json"
            (hulun / "state.json").write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")

            state = load_state(root)
            self.assertEqual(state["schema"], schemas.STATE_SCHEMA)
            self.assertEqual(state["criteria"][0]["id"], "C9")
            self.assertEqual(state["evidence"][0]["id"], "E9")
            self.assertEqual(state["evidence"][0]["privacy"]["retention_days"], 14)
            self.assertEqual(state["events"][0]["privacy"]["retention_days"], 14)
            self.assertEqual(state["last_scan"]["schema"], schemas.RISK_SCHEMA)
            self.assertEqual(state["last_scan"]["score"], 12)
            self.assertTrue(state["schema_migrations"])

            save_state(root, state)
            written = json.loads((hulun / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(written["schema"], schemas.STATE_SCHEMA)
            self.assertEqual(written["evidence"][0]["privacy"]["retention_days"], 14)
            self.assertEqual(written["last_scan"]["schema"], schemas.RISK_SCHEMA)

    def test_current_commands_write_current_public_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_cli("--root", tmp, "init", "--objective", "schema current", "--criterion", "schemas are current")[0], 0)
            self.assertEqual(self.run_cli("--root", tmp, "scan")[0], 0)
            self.assertEqual(self.run_cli("--root", tmp, "validate")[0], 0)
            self.assertEqual(self.run_cli("--root", tmp, "benchmark", "--events", "10")[0], 0)
            self.assertEqual(self.run_cli("--root", tmp, "cleanup", "--json")[0], 0)
            self.assertEqual(json.loads((root / ".hulun" / "state.json").read_text(encoding="utf-8"))["schema"], schemas.STATE_SCHEMA)
            self.assertEqual(json.loads((root / ".hulun" / "risk.json").read_text(encoding="utf-8"))["schema"], schemas.RISK_SCHEMA)
            self.assertEqual(json.loads((root / ".hulun" / "validation_report.json").read_text(encoding="utf-8"))["schema"], schemas.VALIDATION_SCHEMA)
            self.assertEqual(json.loads((root / ".hulun" / "benchmark_report.json").read_text(encoding="utf-8"))["schema"], schemas.BENCHMARK_SCHEMA)

    def test_cleanup_dry_run_reports_expired_records_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_cli("--root", tmp, "init", "--objective", "cleanup dry run", "--criterion", "evidence retained")[0], 0)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "record-evidence",
                    "--kind",
                    "test",
                    "--summary",
                    "old test evidence",
                    "--retention-days",
                    "1",
                )[0],
                0,
            )
            state_path = root / ".hulun" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            old = "2000-01-01T00:00:00+00:00"
            state["events"][-1]["created_at"] = old
            state["evidence"][-1]["created_at"] = old
            state_path.write_text(json.dumps(state), encoding="utf-8")
            benchmark_report = root / ".hulun" / "benchmark_report.json"
            benchmark_report.write_text(json.dumps({"generated_at": old}), encoding="utf-8")

            code, out = self.run_cli("--root", tmp, "cleanup", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["expired_project_events"], 1)
            self.assertEqual(payload["summary"]["expired_project_evidence"], 1)
            self.assertTrue(any(item["name"] == "benchmark_report.json" and item["action"] == "would_delete" for item in payload["reports"]["items"]))
            self.assertTrue(benchmark_report.exists())
            after = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(after["events"]), len(state["events"]))
            self.assertEqual(len(after["evidence"]), len(state["evidence"]))

    def test_cleanup_apply_prunes_project_conversation_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HULUN_HOME")
            os.environ["HULUN_HOME"] = home
            try:
                root = Path(tmp)
                self.assertEqual(self.run_cli("--root", tmp, "init", "--objective", "cleanup apply", "--criterion", "fresh state remains")[0], 0)
                self.assertEqual(
                    self.run_cli(
                        "--root",
                        tmp,
                        "record-evidence",
                        "--kind",
                        "test",
                        "--summary",
                        "expired evidence",
                        "--retention-days",
                        "1",
                    )[0],
                    0,
                )
                state_path = root / ".hulun" / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                evidence_id = state["evidence"][-1]["id"]
                old = "2000-01-01T00:00:00+00:00"
                state["events"][-1]["created_at"] = old
                state["evidence"][-1]["created_at"] = old
                state["criteria"][0]["evidence"] = [evidence_id]
                state_path.write_text(json.dumps(state), encoding="utf-8")

                risk_report = root / ".hulun" / "risk_report.md"
                risk_report.write_text("old risk report", encoding="utf-8")
                benchmark_report = root / ".hulun" / "benchmark_report.json"
                benchmark_report.write_text(json.dumps({"generated_at": old}), encoding="utf-8")

                code, out = self.run_cli("--root", tmp, "conversation", "start", "--name", "cleanup-conversation", "--json")
                self.assertEqual(code, 0, out)
                conversation = json.loads(out)
                self.assertEqual(
                    self.run_cli(
                        "--root",
                        tmp,
                        "conversation",
                        "event",
                        "--id",
                        conversation["id"],
                        "--type",
                        "tool_result",
                        "--summary",
                        "expired conversation event",
                        "--retention-days",
                        "1",
                    )[0],
                    0,
                )
                conversation_path = Path(home) / "conversations" / f"{conversation['id']}.json"
                conversation_data = json.loads(conversation_path.read_text(encoding="utf-8"))
                conversation_data["events"][-1]["created_at"] = old
                conversation_path.write_text(json.dumps(conversation_data), encoding="utf-8")

                code, out = self.run_cli("--root", tmp, "cleanup", "--apply", "--json")
                self.assertEqual(code, 0, out)
                payload = json.loads(out)
                self.assertFalse(payload["dry_run"])
                self.assertEqual(payload["summary"]["expired_project_events"], 1)
                self.assertEqual(payload["summary"]["expired_project_evidence"], 1)
                self.assertEqual(payload["summary"]["expired_conversation_events"], 1)
                self.assertGreaterEqual(payload["summary"]["report_files_deleted"], 1)

                cleaned = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertNotIn(evidence_id, [item["id"] for item in cleaned["evidence"]])
                self.assertEqual(cleaned["criteria"][0]["evidence"], [])
                cleaned_conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
                self.assertFalse(any(event.get("summary") == "expired conversation event" for event in cleaned_conversation["events"]))
                self.assertFalse(benchmark_report.exists())
                self.assertTrue((root / ".hulun" / "retention_cleanup_report.json").exists())
                self.assertTrue((root / ".hulun" / "retention_cleanup_report.md").exists())
            finally:
                if old_home is None:
                    os.environ.pop("HULUN_HOME", None)
                else:
                    os.environ["HULUN_HOME"] = old_home

    def test_cleanup_tolerates_non_dict_ledger_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_cli("--root", tmp, "init", "--objective", "cleanup dirty ledger", "--criterion", "state survives")[0], 0)
            self.assertEqual(
                self.run_cli(
                    "--root",
                    tmp,
                    "record-evidence",
                    "--kind",
                    "test",
                    "--summary",
                    "expired evidence",
                    "--retention-days",
                    "1",
                )[0],
                0,
            )
            state_path = root / ".hulun" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            evidence_id = state["evidence"][-1]["id"]
            old = "2000-01-01T00:00:00+00:00"
            state["events"][-1]["created_at"] = old
            state["evidence"][-1]["created_at"] = old
            state["events"].append("legacy-event-junk")
            state["evidence"].append("legacy-evidence-junk")
            state_path.write_text(json.dumps(state), encoding="utf-8")

            code, out = self.run_cli("--root", tmp, "cleanup", "--apply", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["summary"]["expired_project_events"], 1)
            self.assertEqual(payload["summary"]["expired_project_evidence"], 1)
            cleaned = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn(evidence_id, [item["id"] for item in cleaned["evidence"] if isinstance(item, dict)])
            self.assertIn("legacy-event-junk", [item.get("summary") for item in cleaned["events"] if isinstance(item, dict)])
            self.assertIn("legacy-evidence-junk", [item.get("summary") for item in cleaned["evidence"] if isinstance(item, dict)])

    def test_cleanup_blocks_report_paths_outside_hulun_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"
            outside.write_text("do not delete", encoding="utf-8")
            with mock.patch.object(retention, "GENERATED_REPORT_FILES", ("../outside.txt",)):
                result = retention.run_retention_cleanup(root, dry_run=False, include_conversations=False)
            self.assertFalse(result["gate"]["passed"])
            self.assertEqual(result["summary"]["safety_violations"], 1)
            self.assertTrue(outside.exists())

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

    def test_conversation_event_writes_survive_concurrent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env["HULUN_HOME"] = home
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
            start = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hulun_guard",
                    "--root",
                    tmp,
                    "conversation",
                    "start",
                    "--name",
                    "concurrent-event-test",
                    "--group",
                    "tests",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            conversation = json.loads(start.stdout)

            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "hulun_guard",
                        "conversation",
                        "event",
                        "--id",
                        conversation["id"],
                        "--type",
                        "tool_result",
                        "--summary",
                        f"Concurrent event {index}",
                        "--action-key",
                        f"parallel-{index}",
                        "--json",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
                for index in range(8)
            ]
            outputs = [process.communicate(timeout=20) + (process.returncode,) for process in processes]
            for stdout, stderr, returncode in outputs:
                self.assertEqual(returncode, 0, stderr or stdout)

            conversation_path = Path(home) / "conversations" / f"{conversation['id']}.json"
            data = json.loads(conversation_path.read_text(encoding="utf-8"))
            events = data["events"]
            event_ids = [event["id"] for event in events]
            summaries = {event["summary"] for event in events}
            self.assertEqual(len(events), 9)
            self.assertEqual(len(event_ids), len(set(event_ids)))
            for index in range(8):
                self.assertIn(f"Concurrent event {index}", summaries)

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
