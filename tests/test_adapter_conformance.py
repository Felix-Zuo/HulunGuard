from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable
from unittest import mock

from hulun_guard.cli import main
from hulun_guard.mcp import HulunMCPServer
from hulun_guard.sdk import HulunGuardClient, HulunGuardError


def private_openai_key() -> str:
    return "".join(["sk", "-", "testsecret", "012345678901234567890"])


def private_email() -> str:
    return "alice" + "@" + "example.com"


def private_password() -> str:
    return "password=" + "hunter2"


def private_summary() -> str:
    return "pytest failed with [redacted:openai-key] for [redacted:email] and password=[redacted:secret]"


def private_tool_args() -> str:
    return "tool arguments withheld"


def private_ref() -> str:
    return "https://trace.example/run"


def write_synthetic_trace_fixture(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


REDACTED_SUMMARY = "pytest failed with [redacted:openai-key] for [redacted:email] and password=[redacted:secret]"
PUBLIC_SUMMARY = "pytest failed after contract mismatch"
REF_WITH_QUERY = "https://trace.example/run?id=abc&debug=true#debug"
REDACTED_REF = "https://trace.example/run"
ACTION_KEY = "pytest-contract"
EVIDENCE_ID = "E-contract"


def run_cli(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


def run_cli_with_stdin(stdin_text: str, *args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), mock.patch("sys.stdin", io.StringIO(stdin_text)):
        code = main(list(args))
    return code, buf.getvalue()


def init_cli_project(root: str) -> None:
    code, out = run_cli(
        "--root",
        root,
        "init",
        "--objective",
        "adapter contract conformance",
        "--criterion",
        "adapter emits durable runtime semantics",
    )
    if code != 0:
        raise AssertionError(out)


def load_last_event(root: str | Path) -> dict[str, object]:
    state = json.loads((Path(root) / ".hulun" / "state.json").read_text(encoding="utf-8"))
    return state["events"][-1]


def assert_contract_event(
    test: unittest.TestCase,
    root: str | Path,
    event: dict[str, object],
    payload: dict[str, object],
    *,
    require_secret_redaction: bool,
) -> None:
    test.assertEqual(event["type"], "tool_result")
    test.assertEqual(event["phase"], "verify")
    test.assertEqual(event["result"], "fail")
    test.assertEqual(event["evidence"], [EVIDENCE_ID])
    test.assertEqual(event["action_key"], ACTION_KEY)
    test.assertEqual(event["prompt_tokens"], 123)
    test.assertEqual(event["completion_tokens"], 45)
    test.assertEqual(event["cost"], 0.67)
    test.assertEqual(event["latency_ms"], 890)
    test.assertEqual(event["model"], "gpt-contract")
    test.assertIn(REDACTED_REF, event["refs"])
    if require_secret_redaction:
        test.assertIn("[redacted:openai-key]", event["summary"])
        test.assertIn("[redacted:email]", event["summary"])
        test.assertIn("password=[redacted:secret]", event["summary"])
    else:
        test.assertIn(PUBLIC_SUMMARY, event["summary"])
    test.assertEqual(event["privacy"]["mode"], "redacted-default")
    test.assertEqual(event["privacy"]["retention_days"], 30)

    joined = json.dumps(event, ensure_ascii=False)
    test.assertNotIn(private_openai_key(), joined)
    test.assertNotIn(private_email(), joined)
    test.assertNotIn("hunter2", joined)
    test.assertNotIn("token=secret", joined)

    test.assertIn("risk", payload)
    test.assertTrue((Path(root) / ".hulun" / "risk.json").exists())


def otlp_attr(key: str, value: object) -> dict[str, object]:
    if isinstance(value, bool):
        encoded: dict[str, object] = {"boolValue": value}
    elif isinstance(value, int):
        encoded = {"intValue": str(value)}
    elif isinstance(value, float):
        encoded = {"doubleValue": value}
    elif isinstance(value, list):
        encoded = {"arrayValue": {"values": [otlp_attr("", item)["value"] for item in value]}}
    else:
        encoded = {"stringValue": str(value)}
    return {"key": key, "value": encoded}


def write_generic_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        {
            "events": [
                {
                    "type": "tool_result",
                    "summary": REDACTED_SUMMARY,
                    "result": "fail",
                    "phase": "verify",
                    "evidence": [EVIDENCE_ID],
                    "refs": [private_ref()],
                    "action_key": ACTION_KEY,
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "cost": 0.67,
                    "latency_ms": 890,
                    "model": "gpt-contract",
                }
            ]
        },
    )


def write_opentelemetry_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "trace-contract",
                                    "spanId": "span-contract",
                                    "name": "contract span",
                                    "attributes": [
                                        otlp_attr("hulun.event.type", "tool_result"),
                                        otlp_attr("hulun.event.summary", private_summary()),
                                        otlp_attr("hulun.event.result", "fail"),
                                        otlp_attr("hulun.event.phase", "verify"),
                                        otlp_attr("hulun.evidence.ids", [EVIDENCE_ID]),
                                        otlp_attr("hulun.refs", [private_ref()]),
                                        otlp_attr("hulun.action_key", ACTION_KEY),
                                        otlp_attr("gen_ai.usage.input_tokens", 123),
                                        otlp_attr("gen_ai.usage.output_tokens", 45),
                                        otlp_attr("hulun.cost", 0.67),
                                        otlp_attr("hulun.latency_ms", 890),
                                        otlp_attr("gen_ai.request.model", "gpt-contract"),
                                        otlp_attr("gen_ai.tool.call.arguments", private_tool_args()),
                                    ],
                                    "status": {"code": "STATUS_CODE_OK"},
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    )


def write_openinference_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        [
            {
                "trace_id": "trace-contract",
                "span_id": "span-contract",
                "name": "contract tool span",
                "attributes": {
                    "openinference.span.kind": "TOOL",
                    "hulun.event.type": "tool_result",
                    "hulun.event.summary": private_summary(),
                    "hulun.event.result": "fail",
                    "hulun.event.phase": "verify",
                    "hulun.evidence.ids": [EVIDENCE_ID],
                    "hulun.refs": [private_ref()],
                    "hulun.action_key": ACTION_KEY,
                    "llm.token_count.prompt": 123,
                    "llm.token_count.completion": 45,
                    "hulun.cost": 0.67,
                    "hulun.latency_ms": 890,
                    "llm.model_name": "gpt-contract",
                    "tool.parameters": private_tool_args(),
                },
            }
        ],
    )


def write_openhands_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        {
            "events": [
                {
                    "type": "observation",
                    "summary": private_summary(),
                    "message": private_summary(),
                    "result": "fail",
                    "phase": "verify",
                    "evidence": [EVIDENCE_ID],
                    "refs": [private_ref()],
                    "action_key": ACTION_KEY,
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "cost": 0.67,
                    "latency_ms": 890,
                    "model": "gpt-contract",
                }
            ]
        },
    )


def write_swe_agent_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        {
            "trajectory": [
                {
                    "action": "python -m pytest tests/test_contract.py",
                    "observation": private_summary(),
                    "summary": private_summary(),
                    "result": "fail",
                    "phase": "verify",
                    "evidence": [EVIDENCE_ID],
                    "refs": [private_ref()],
                    "action_key": ACTION_KEY,
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "cost": 0.67,
                    "latency_ms": 890,
                    "model": "gpt-contract",
                }
            ]
        },
    )


def write_langgraph_trace(path: Path) -> None:
    write_synthetic_trace_fixture(path, langgraph_contract_payload())


def langgraph_contract_payload() -> dict[str, object]:
    return {
        "events": [
            {
                "type": "tasks",
                "event_type": "tool_result",
                "summary": PUBLIC_SUMMARY,
                "result": "fail",
                "phase": "verify",
                "evidence": [EVIDENCE_ID],
                "refs": [REF_WITH_QUERY],
                "action_key": ACTION_KEY,
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "cost": 0.67,
                "latency_ms": 890,
                "model": "gpt-contract",
                "data": {"node": "pytest", "status": "redacted failure"},
            }
        ]
    }


def write_langsmith_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        [
            {
                "id": "run-contract",
                "trace_id": "trace-contract",
                "run_type": "tool",
                "name": "pytest contract run",
                "summary": PUBLIC_SUMMARY,
                "error": PUBLIC_SUMMARY,
                "result": "fail",
                "phase": "verify",
                "evidence": [EVIDENCE_ID],
                "refs": [REF_WITH_QUERY],
                "action_key": ACTION_KEY,
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "cost": 0.67,
                "latency_ms": 890,
                "invocation_params": {"model": "gpt-contract"},
            }
        ],
    )


def write_langfuse_trace(path: Path) -> None:
    write_opentelemetry_trace(path)


def write_phoenix_trace(path: Path) -> None:
    write_synthetic_trace_fixture(
        path,
        {
            "traceId": "trace-phoenix-contract",
            "spans": [
                {
                    "name": "pytest contract run",
                    "context": {"trace_id": "trace-phoenix-contract", "span_id": "span-phoenix-contract"},
                    "span_kind": "TOOL",
                    "parent_id": None,
                    "start_time": "2026-06-25T00:00:00.000Z",
                    "end_time": "2026-06-25T00:00:00.890Z",
                    "status_code": "ERROR",
                    "attributes": {
                        "hulun.event.type": "tool_result",
                        "hulun.event.summary": PUBLIC_SUMMARY,
                        "hulun.event.result": "fail",
                        "hulun.event.phase": "verify",
                        "hulun.evidence.ids": [EVIDENCE_ID],
                        "hulun.refs": [REF_WITH_QUERY],
                        "hulun.action_key": ACTION_KEY,
                        "llm.token_count.prompt": 123,
                        "llm.token_count.completion": 45,
                        "hulun.cost": 0.67,
                        "llm.model_name": "gpt-contract",
                    },
                }
            ],
        },
    )


class AdapterConformanceTest(unittest.TestCase):
    def test_cli_sdk_mcp_and_trace_adapters_emit_contract_fields(self) -> None:
        cases = [
            ("cli", self._record_cli, True),
            ("sdk", self._record_sdk, True),
            ("mcp", self._record_mcp, True),
            ("cli-batch", self._record_cli_batch, False),
            ("sdk-batch", self._record_sdk_batch, False),
            ("mcp-batch", self._record_mcp_batch, False),
            ("cli-stdin-batch", self._record_cli_stdin_batch, False),
            ("sdk-payload-batch", self._record_sdk_payload_batch, False),
            ("mcp-payload-batch", self._record_mcp_payload_batch, False),
            ("generic", self._record_generic_ingest, True),
            ("opentelemetry", self._record_opentelemetry_ingest, True),
            ("openinference", self._record_openinference_ingest, True),
            ("openhands", self._record_openhands_ingest, True),
            ("swe-agent", self._record_swe_agent_ingest, True),
            ("langgraph", self._record_langgraph_ingest, False),
            ("langsmith", self._record_langsmith_ingest, False),
            ("langfuse", self._record_langfuse_ingest, True),
            ("phoenix", self._record_phoenix_ingest, False),
        ]
        for name, recorder, require_secret_redaction in cases:
            with self.subTest(adapter=name):
                with tempfile.TemporaryDirectory() as tmp:
                    event, payload = recorder(tmp)
                    assert_contract_event(self, tmp, event, payload, require_secret_redaction=require_secret_redaction)

    def test_malformed_adapter_payloads_fail_without_persisting_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = HulunGuardClient(tmp)
            client.init(objective="reject malformed adapter payloads", criteria=["bad payload is rejected"])
            with self.assertRaises(HulunGuardError):
                client.observe(event_type="tool_result", summary="bad phase", phase="invalid-phase")

            server = HulunMCPServer(root=tmp)
            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "hulun_observe",
                        "arguments": {"type": "tool_result", "summary": "bad result", "result": "bad-result"},
                    },
                }
            )
            self.assertEqual(response["error"]["code"], -32602)
            with self.assertRaises(HulunGuardError):
                client.enqueue(event_type="tool_result", summary="bad phase", phase="invalid-phase")
            with self.assertRaises(HulunGuardError):
                client.enqueue_payload({"type": "tool_result", "summary": "too large"}, source_format="generic", max_payload_bytes=1)

            batch_response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "hulun_batch_enqueue",
                        "arguments": {"type": "tool_result", "summary": "bad result", "result": "bad-result"},
                    },
                }
            )
            self.assertEqual(batch_response["error"]["code"], -32602)
            state = json.loads((Path(tmp) / ".hulun" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["events"]), 1)

    def test_phoenix_cli_export_auto_detection_preserves_context_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace-export.json"
            write_phoenix_trace(trace)

            code, out = run_cli("trace-doctor", "--file", str(trace), "--json")
            self.assertEqual(code, 0, out)
            doctor = json.loads(out)
            self.assertEqual(doctor["detected_format"], "phoenix")
            self.assertEqual(doctor["selected_format"], "phoenix")
            self.assertEqual(doctor["observation_count"], 1)
            self.assertTrue(doctor["gate"]["passed"], doctor["gate"]["failures"])
            self.assertIn("--format phoenix", doctor["next_command"])
            self.assertFalse((root / ".hulun" / "state.json").exists())

            project = root / "project"
            init_cli_project(str(project))
            code, out = run_cli("--root", str(project), "ingest", "--file", str(trace), "--format", "auto", "--scan", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["imported"], 1)
            event = load_last_event(project)
            self.assertEqual(event["source_platform"], "phoenix")
            self.assertEqual(event["latency_ms"], 890)
            self.assertIn("phoenix:trace:trace-phoenix-contract", event["refs"])
            self.assertIn("phoenix:span:span-phoenix-contract", event["refs"])

    def _record_cli(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        init_cli_project(root)
        code, out = run_cli(
            "--root",
            root,
            "observe",
            "--type",
            "tool_result",
            "--summary",
            private_summary(),
            "--result",
            "fail",
            "--phase",
            "verify",
            "--evidence",
            EVIDENCE_ID,
            "--ref",
            private_ref(),
            "--action-key",
            ACTION_KEY,
            "--prompt-tokens",
            "123",
            "--completion-tokens",
            "45",
            "--cost",
            "0.67",
            "--latency-ms",
            "890",
            "--model",
            "gpt-contract",
            "--scan",
            "--json",
        )
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        return payload["event"], payload

    def _record_sdk(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        client = HulunGuardClient(root)
        client.init(objective="adapter contract conformance", criteria=["adapter emits durable runtime semantics"])
        payload = client.observe(
            event_type="tool_result",
            summary=private_summary(),
            result="fail",
            phase="verify",
            evidence=[EVIDENCE_ID],
            refs=[private_ref()],
            action_key=ACTION_KEY,
            prompt_tokens=123,
            completion_tokens=45,
            cost=0.67,
            latency_ms=890,
            model="gpt-contract",
            scan=True,
        )
        return payload["event"], payload

    def _record_mcp(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        server = HulunMCPServer(root=root)
        init_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hulun_project_init",
                    "arguments": {
                        "objective": "adapter contract conformance",
                        "criteria": ["adapter emits durable runtime semantics"],
                    },
                },
            }
        )
        self.assertNotIn("error", init_response)
        observe_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "hulun_observe",
                    "arguments": {
                        "type": "tool_result",
                        "summary": private_summary(),
                        "result": "fail",
                        "phase": "verify",
                        "evidence": [EVIDENCE_ID],
                        "refs": [private_ref()],
                        "action_key": ACTION_KEY,
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "cost": 0.67,
                        "latency_ms": 890,
                        "model": "gpt-contract",
                        "scan": True,
                    },
                },
            }
        )
        self.assertNotIn("error", observe_response)
        payload = observe_response["result"]["structuredContent"]
        return payload["event"], payload

    def _record_cli_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        init_cli_project(root)
        code, out = run_cli(
            "--root",
            root,
            "batch",
            "enqueue",
            "--type",
            "tool_result",
            "--summary",
            PUBLIC_SUMMARY,
            "--result",
            "fail",
            "--phase",
            "verify",
            "--evidence",
            EVIDENCE_ID,
            "--ref",
            REF_WITH_QUERY,
            "--action-key",
            ACTION_KEY,
            "--prompt-tokens",
            "123",
            "--completion-tokens",
            "45",
            "--cost",
            "0.67",
            "--latency-ms",
            "890",
            "--model",
            "gpt-contract",
            "--json",
        )
        self.assertEqual(code, 0, out)
        code, out = run_cli("--root", root, "batch", "flush", "--scan", "--include-events", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["imported"], 1)
        return payload["events"][0], payload

    def _record_sdk_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        client = HulunGuardClient(root)
        client.init(objective="adapter contract conformance", criteria=["adapter emits durable runtime semantics"])
        client.enqueue(
            event_type="tool_result",
            summary=PUBLIC_SUMMARY,
            result="fail",
            phase="verify",
            evidence=[EVIDENCE_ID],
            refs=[REF_WITH_QUERY],
            action_key=ACTION_KEY,
            prompt_tokens=123,
            completion_tokens=45,
            cost=0.67,
            latency_ms=890,
            model="gpt-contract",
        )
        payload = client.flush_queue(limit=1, scan=True)
        return load_last_event(root), payload

    def _record_mcp_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        server = HulunMCPServer(root=root)
        init_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hulun_project_init",
                    "arguments": {
                        "objective": "adapter contract conformance",
                        "criteria": ["adapter emits durable runtime semantics"],
                    },
                },
            }
        )
        self.assertNotIn("error", init_response)
        enqueue_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "hulun_batch_enqueue",
                    "arguments": {
                        "type": "tool_result",
                        "summary": PUBLIC_SUMMARY,
                        "result": "fail",
                        "phase": "verify",
                        "evidence": [EVIDENCE_ID],
                        "refs": [REF_WITH_QUERY],
                        "action_key": ACTION_KEY,
                        "prompt_tokens": 123,
                        "completion_tokens": 45,
                        "cost": 0.67,
                        "latency_ms": 890,
                        "model": "gpt-contract",
                    },
                },
            }
        )
        self.assertNotIn("error", enqueue_response)
        flush_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "hulun_batch_flush", "arguments": {"limit": 1, "scan": True}},
            }
        )
        self.assertNotIn("error", flush_response)
        payload = flush_response["result"]["structuredContent"]
        return load_last_event(root), payload

    def _record_cli_stdin_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        init_cli_project(root)
        code, out = run_cli_with_stdin(
            json.dumps(langgraph_contract_payload()),
            "--root",
            root,
            "batch",
            "ingest-stdin",
            "--format",
            "langgraph",
            "--json",
        )
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["queued"], 1)
        code, out = run_cli("--root", root, "batch", "flush", "--scan", "--include-events", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        return payload["events"][0], payload

    def _record_sdk_payload_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        client = HulunGuardClient(root)
        client.init(objective="adapter contract conformance", criteria=["adapter emits durable runtime semantics"])
        queued = client.enqueue_payload(langgraph_contract_payload(), source_format="langgraph", source_name="langgraph-stream")
        self.assertEqual(queued["queued"], 1)
        payload = client.flush_queue(limit=1, scan=True)
        return load_last_event(root), payload

    def _record_mcp_payload_batch(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        server = HulunMCPServer(root=root)
        init_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hulun_project_init",
                    "arguments": {
                        "objective": "adapter contract conformance",
                        "criteria": ["adapter emits durable runtime semantics"],
                    },
                },
            }
        )
        self.assertNotIn("error", init_response)
        enqueue_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "hulun_batch_ingest_payload",
                    "arguments": {
                        "format": "langgraph",
                        "source_name": "langgraph-stream",
                        "payload": langgraph_contract_payload(),
                    },
                },
            }
        )
        self.assertNotIn("error", enqueue_response)
        self.assertEqual(enqueue_response["result"]["structuredContent"]["queued"], 1)
        flush_response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "hulun_batch_flush", "arguments": {"limit": 1, "scan": True}},
            }
        )
        self.assertNotIn("error", flush_response)
        payload = flush_response["result"]["structuredContent"]
        return load_last_event(root), payload

    def _record_ingest(self, root: str, fmt: str, writer: Callable[[Path], None]) -> tuple[dict[str, object], dict[str, object]]:
        init_cli_project(root)
        trace = Path(root) / f"{fmt}-contract.json"
        writer(trace)
        code, out = run_cli(
            "--root",
            root,
            "ingest",
            "--file",
            str(trace),
            "--format",
            fmt,
            "--scan",
            "--include-events",
            "--json",
        )
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["imported"], 1)
        return payload["events"][0], payload

    def _record_generic_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "generic", write_generic_trace)

    def _record_opentelemetry_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "opentelemetry", write_opentelemetry_trace)

    def _record_openinference_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "openinference", write_openinference_trace)

    def _record_openhands_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "openhands", write_openhands_trace)

    def _record_swe_agent_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "swe-agent", write_swe_agent_trace)

    def _record_langgraph_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "langgraph", write_langgraph_trace)

    def _record_langsmith_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "langsmith", write_langsmith_trace)

    def _record_langfuse_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "langfuse", write_langfuse_trace)

    def _record_phoenix_ingest(self, root: str) -> tuple[dict[str, object], dict[str, object]]:
        return self._record_ingest(root, "phoenix", write_phoenix_trace)
