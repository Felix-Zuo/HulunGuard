from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard.cli import main
from hulun_guard.collector import CollectorConfig, CollectorError, build_collector_server
from hulun_guard.queue import queue_status


def otlp_payload(summary: str = "collector accepted otlp json") -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                "spanId": "bbbbbbbbbbbbbbbb",
                                "name": "test.collector",
                                "attributes": [
                                    {"key": "hulun.event.type", "value": {"stringValue": "tool_result"}},
                                    {"key": "hulun.event.phase", "value": {"stringValue": "verify"}},
                                    {"key": "hulun.event.summary", "value": {"stringValue": summary}},
                                    {"key": "hulun.action_key", "value": {"stringValue": "collector-test"}},
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }


def request_json(url: str, *, method: str = "GET", payload: Any | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"} if payload is not None else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return int(exc.code), body


class CollectorTest(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(args))
        return code, buf.getvalue()

    def start_server(self, config: CollectorConfig) -> tuple[Any, threading.Thread, str]:
        server = build_collector_server(config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        return server, thread, f"http://{host}:{port}"

    def stop_server(self, server: Any, thread: threading.Thread) -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    def test_collector_smoke_cli_queues_one_otlp_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema"], "hulun.collector.v1")
            self.assertTrue(payload["gate"]["passed"])
            self.assertEqual(payload["response"]["format"], "opentelemetry")
            self.assertEqual(queue_status(tmp)["queue"]["pending"], 1)

    def test_otlp_endpoint_queues_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, thread, base_url = self.start_server(CollectorConfig(root=tmp, port=0))
            try:
                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload())
                self.assertEqual(code, 202)
                self.assertEqual(body["schema"], "hulun.collector.v1")
                self.assertEqual(body["format"], "opentelemetry")
                self.assertEqual(body["queued"], 1)
                self.assertEqual(queue_status(tmp)["queue"]["pending"], 1)
            finally:
                self.stop_server(server, thread)

    def test_token_auth_protects_ingest_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, thread, base_url = self.start_server(CollectorConfig(root=tmp, port=0, token="secret-token"))
            try:
                code, body = request_json(f"{base_url}/healthz")
                self.assertEqual(code, 200)
                self.assertNotIn("gate", body)
                self.assertTrue(body["auth_required"])

                code, body = request_json(f"{base_url}/status")
                self.assertEqual(code, 401)
                self.assertEqual(body["error"]["code"], "unauthorized")

                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload())
                self.assertEqual(code, 401)
                self.assertEqual(body["error"]["code"], "unauthorized")

                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload(), headers={"X-Hulun-Token": "secret-token"})
                self.assertEqual(code, 202)
                self.assertEqual(body["queued"], 1)
            finally:
                self.stop_server(server, thread)

    def test_oversized_payload_is_rejected_before_queue_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server, thread, base_url = self.start_server(CollectorConfig(root=tmp, port=0, max_payload_bytes=20))
            try:
                code, body = request_json(f"{base_url}/ingest/generic", method="POST", payload={"summary": "x" * 200})
                self.assertEqual(code, 413)
                self.assertEqual(body["error"]["code"], "payload_too_large")
                self.assertEqual(queue_status(tmp)["queue"]["pending"], 0)
            finally:
                self.stop_server(server, thread)

    def test_remote_bind_requires_explicit_flag_and_token(self) -> None:
        with self.assertRaises(CollectorError):
            build_collector_server(CollectorConfig(host="0.0.0.0", port=0))
        with self.assertRaises(CollectorError):
            build_collector_server(CollectorConfig(host="0.0.0.0", port=0, allow_remote=True))


if __name__ == "__main__":
    unittest.main()
