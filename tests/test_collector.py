from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hulun_guard import collector as collector_module
from hulun_guard.cli import main
from hulun_guard.collector import (
    CollectorConfig,
    CollectorError,
    CollectorRuntimeState,
    build_collector_server,
    collector_flush_once,
    collector_operations_status,
    collector_status_path,
)
from hulun_guard.queue import dead_letter_path, enqueue_observations, queue_status
from hulun_guard.storage import risk_path, write_json


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


def request_text(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return int(response.status), body, str(response.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return int(exc.code), body, str(exc.headers.get("Content-Type") or "")


def diagnostic_group(payload: dict[str, Any], group_id: str) -> dict[str, Any]:
    groups = payload["diagnostics"]["groups"]
    for group in groups:
        if group["id"] == group_id:
            return group
    raise AssertionError(f"Missing diagnostic group: {group_id}")


def write_green_risk(root: str) -> None:
    write_json(
        risk_path(Path(root)),
        {
            "schema": "hulun.risk.v1",
            "generated_at": "2026-06-25T00:00:00Z",
            "score": 8,
            "slop_index": 8,
            "band": "green",
            "threshold": 66,
            "blocked": False,
            "required_action": "continue",
        },
    )


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

    def test_managed_collector_smoke_flushes_and_scans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--managed", "--scan", "--init-if-missing", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertTrue(payload["gate"]["passed"])
            self.assertTrue(payload["managed"])
            self.assertEqual(payload["response"]["queued"], 1)
            self.assertEqual(payload["managed_flush"]["imported"], 1)
            self.assertTrue(payload["managed_flush"]["scanned"])
            self.assertIn("risk", payload["managed_flush"])
            self.assertEqual(queue_status(tmp)["queue"]["pending"], 0)
            self.assertTrue((Path(tmp) / ".hulun" / "state.json").exists())
            self.assertTrue((Path(tmp) / ".hulun" / "risk.json").exists())
            self.assertTrue(collector_status_path(tmp).exists())

    def test_managed_collector_smoke_flushes_existing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--json")
            self.assertEqual(code, 0, out)
            self.assertEqual(queue_status(tmp)["queue"]["pending"], 1)

            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--managed", "--scan", "--init-if-missing", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertTrue(payload["gate"]["passed"])
            self.assertEqual(payload["managed_flush"]["pending_before"], 2)
            self.assertEqual(payload["managed_flush"]["imported"], 2)
            self.assertEqual(queue_status(tmp)["queue"]["pending"], 0)

    def test_collector_status_reports_offline_operations_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--managed", "--scan", "--init-if-missing", "--json")
            self.assertEqual(code, 0, out)

            code, out = self.run_cli("--root", tmp, "collector", "status", "--require-status-file", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "operations_status")
            self.assertTrue(payload["gate"]["passed"])
            self.assertTrue(payload["status_file"]["exists"])
            self.assertEqual(payload["queue"]["pending"], 0)
            self.assertEqual(payload["dead_letter"]["records"], 0)
            self.assertTrue(payload["risk"]["exists"])
            self.assertEqual(payload["risk"]["band"], "yellow")
            self.assertIn("diagnostics", payload)
            self.assertIn(diagnostic_group(payload, "risk")["status"], {"warning", "critical"})

    def test_collector_metrics_reports_prometheus_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "smoke", "--managed", "--scan", "--init-if-missing", "--json")
            self.assertEqual(code, 0, out)

            code, out = self.run_cli("--root", tmp, "collector", "metrics", "--require-status-file", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "metrics")
            self.assertEqual(payload["format"], "prometheus")
            metric_names = {metric["name"] for metric in payload["metrics"]}
            self.assertIn("hulun_collector_up", metric_names)
            self.assertIn("hulun_collector_queue_pending", metric_names)
            self.assertIn("hulun_collector_risk_score", metric_names)
            self.assertIn("hulun_collector_risk_band", metric_names)
            self.assertIn("hulun_collector_runtime_state", metric_names)
            self.assertIn("hulun_collector_runtime_uptime_seconds", metric_names)
            status = payload["status"]
            diagnostics = status["diagnostics"]
            self.assertIn(diagnostics["summary"]["status"], {"ok", "warning", "critical"})
            diagnostic_groups = {group["id"] for group in diagnostics["groups"]}
            self.assertEqual(
                diagnostic_groups,
                {"queue", "status_freshness", "runtime_lifecycle", "dead_letter", "managed_flush", "risk"},
            )
            self.assertNotIn(str(Path(tmp)), json.dumps(diagnostics, ensure_ascii=False))
            self.assertIn("hulun_collector_queue_pending 0", payload["text"])
            self.assertIn('hulun_collector_risk_band{band="yellow"} 1', payload["text"])
            self.assertIn('hulun_collector_runtime_state{state="running"} 1', payload["text"])
            self.assertNotIn(str(Path(tmp)), payload["text"])

            code, out = self.run_cli("--root", tmp, "collector", "metrics", "--require-status-file")
            self.assertEqual(code, 0, out)
            self.assertIn("# HELP hulun_collector_up", out)
            self.assertIn("hulun_collector_up 1", out)

    def test_collector_status_reports_green_grouped_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            runtime_state = CollectorRuntimeState()
            collector_module.write_collector_status(config, runtime_state)
            write_green_risk(tmp)

            payload = collector_operations_status(tmp, require_status_file=True)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            summary = payload["diagnostics"]["summary"]
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["critical_count"], 0)
            self.assertEqual(summary["warning_count"], 0)
            groups = {group["id"]: group["status"] for group in payload["diagnostics"]["groups"]}
            self.assertEqual(
                groups,
                {
                    "queue": "ok",
                    "status_freshness": "ok",
                    "runtime_lifecycle": "ok",
                    "dead_letter": "ok",
                    "managed_flush": "ok",
                    "risk": "ok",
                },
            )
            diagnostics_text = json.dumps(payload["diagnostics"], ensure_ascii=False)
            self.assertNotIn(str(Path(tmp)), diagnostics_text)
            self.assertNotIn("collector_status.json", diagnostics_text)

    def test_collector_status_diagnoses_stale_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            collector_module.write_collector_status(config, CollectorRuntimeState())
            write_green_risk(tmp)
            stale_time = time.time() - 120
            os.utime(collector_status_path(tmp), (stale_time, stale_time))

            payload = collector_operations_status(tmp, require_status_file=True, stale_after_seconds=1)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["diagnostics"]["summary"]["status"], "warning")
            status_group = diagnostic_group(payload, "status_freshness")
            self.assertEqual(status_group["status"], "warning")
            self.assertTrue(status_group["signals"]["stale"])

            failing = collector_operations_status(tmp, require_status_file=True, stale_after_seconds=1, fail_on_stale=True)
            self.assertFalse(failing["gate"]["passed"])
            self.assertEqual(diagnostic_group(failing, "status_freshness")["status"], "critical")

    def test_collector_status_diagnoses_runtime_error_without_leaking_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            runtime_state = CollectorRuntimeState()
            runtime_state.last_error = {
                "code": "managed_loop_failed",
                "message": f"secret token at {Path(tmp)}",
                "generated_at": "2026-06-25T00:00:00Z",
            }
            collector_module.write_collector_status(config, runtime_state)
            write_green_risk(tmp)

            payload = collector_operations_status(tmp, require_status_file=True)
            self.assertFalse(payload["gate"]["passed"])
            self.assertIn("managed_loop_failed", payload["gate"]["failures"][0])
            self.assertNotIn("secret token", payload["gate"]["failures"][0])
            self.assertEqual(diagnostic_group(payload, "runtime_lifecycle")["status"], "critical")
            self.assertEqual(diagnostic_group(payload, "runtime_lifecycle")["signals"]["last_error_code"], "managed_loop_failed")
            diagnostics_text = json.dumps(payload["diagnostics"], ensure_ascii=False)
            self.assertIn("managed_loop_failed", diagnostics_text)
            self.assertNotIn("secret token", diagnostics_text)
            self.assertNotIn(str(Path(tmp)), diagnostics_text)

    def test_collector_status_diagnoses_stopped_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            runtime_state = CollectorRuntimeState()
            collector_module._mark_runtime_stopped(runtime_state, reason="unit_test")  # noqa: SLF001
            collector_module.write_collector_status(config, runtime_state)
            write_green_risk(tmp)

            payload = collector_operations_status(tmp, require_status_file=True)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["diagnostics"]["summary"]["status"], "warning")
            runtime_group = diagnostic_group(payload, "runtime_lifecycle")
            self.assertEqual(runtime_group["status"], "warning")
            self.assertEqual(runtime_group["signals"]["lifecycle_state"], "stopped")
            self.assertEqual(runtime_group["signals"]["stop_reason"], "unit_test")

    def test_collector_status_diagnoses_queue_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            collector_module.write_collector_status(config, CollectorRuntimeState())
            write_green_risk(tmp)
            enqueue_observations(
                tmp,
                [
                    {"type": "tool_result", "phase": "verify", "summary": "queued one", "result": "pass"},
                    {"type": "tool_result", "phase": "verify", "summary": "queued two", "result": "pass"},
                ],
            )

            payload = collector_operations_status(tmp, require_status_file=True, queue_pending_threshold=1)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["diagnostics"]["summary"]["status"], "warning")
            queue_group = diagnostic_group(payload, "queue")
            self.assertEqual(queue_group["status"], "warning")
            self.assertEqual(queue_group["signals"]["pending"], 2)
            self.assertEqual(queue_group["signals"]["pending_threshold"], 1)

    def test_collector_status_diagnoses_dead_letters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            collector_module.write_collector_status(config, CollectorRuntimeState())
            write_green_risk(tmp)
            path = dead_letter_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"schema":"hulun.ingest_dead_letter.v1","reason":"unit-test"}\n', encoding="utf-8")

            payload = collector_operations_status(tmp, require_status_file=True)
            self.assertFalse(payload["gate"]["passed"])
            self.assertEqual(payload["diagnostics"]["summary"]["status"], "critical")
            dead_group = diagnostic_group(payload, "dead_letter")
            self.assertEqual(dead_group["status"], "critical")
            self.assertEqual(dead_group["signals"]["records"], 1)

    def test_collector_status_warns_on_unknown_risk_band(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=5)
            collector_module.write_collector_status(config, CollectorRuntimeState())
            write_json(
                risk_path(Path(tmp)),
                {
                    "schema": "hulun.risk.v1",
                    "generated_at": "2026-06-25T00:00:00Z",
                    "score": 8,
                    "slop_index": 8,
                    "blocked": False,
                    "required_action": "continue",
                },
            )

            payload = collector_operations_status(tmp, require_status_file=True)
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["diagnostics"]["summary"]["status"], "warning")
            risk_group = diagnostic_group(payload, "risk")
            self.assertEqual(risk_group["status"], "warning")
            self.assertIsNone(risk_group["signals"]["band"])

    def test_collector_alert_rules_generates_prometheus_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "alert-rules"
            code, out = self.run_cli(
                "--root",
                tmp,
                "collector",
                "alert-rules",
                "--output",
                str(output_dir),
                "--queue-pending-threshold",
                "42",
                "--status-stale-seconds",
                "90",
                "--risk-red-threshold",
                "70",
                "--force",
                "--json",
            )
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "alert_rules")
            self.assertEqual(payload["format"], "prometheus-rule-yaml")
            self.assertEqual(payload["thresholds"]["queue_pending"], 42)
            self.assertEqual(payload["thresholds"]["status_stale_seconds"], 90)
            self.assertEqual(payload["thresholds"]["risk_red"], 70)
            self.assertTrue(payload["gate"]["passed"])
            rule_file = output_dir / "hulunguard-collector.rules.yml"
            readme_file = output_dir / "README.md"
            self.assertTrue(rule_file.exists())
            self.assertTrue(readme_file.exists())
            rule_text = rule_file.read_text(encoding="utf-8")
            self.assertIn("groups:", rule_text)
            self.assertIn('name: "hulunguard-collector"', rule_text)
            self.assertIn('alert: "HulunCollectorGateFailing"', rule_text)
            self.assertIn('alert: "HulunCollectorQueueBacklog"', rule_text)
            self.assertIn('expr: "hulun_collector_queue_pending > 42"', rule_text)
            self.assertIn('expr: "hulun_collector_status_file_stale == 1 or hulun_collector_status_file_age_seconds > 90"', rule_text)
            self.assertIn('expr: "hulun_collector_risk_score >= 70"', rule_text)
            self.assertNotIn(str(Path(tmp)), rule_text)
            self.assertIn("promtool check rules", readme_file.read_text(encoding="utf-8"))

    def test_collector_alert_rules_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "alert-rules", "--json")
            self.assertEqual(code, 0, out)

            code, out = self.run_cli("--root", tmp, "collector", "alert-rules", "--json")
            self.assertEqual(code, 2, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "alert_rules")
            self.assertFalse(payload["gate"]["passed"])
            self.assertIn("Refusing to overwrite", payload["gate"]["failures"][0])

    def test_collector_service_template_generates_cross_platform_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "service-templates"
            code, out = self.run_cli("--root", tmp, "collector", "service-template", "--output", str(output_dir), "--force", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "service_template")
            self.assertTrue(payload["gate"]["passed"])
            targets = {item["target"] for item in payload["files"]}
            self.assertEqual(targets, {"systemd", "launchd", "windows-task", "readme"})
            for item in payload["files"]:
                self.assertTrue(Path(item["path"]).exists(), item)
            self.assertIn("collector serve", (output_dir / "README.md").read_text(encoding="utf-8"))
            self.assertIn("--scan-on-flush", " ".join(payload["command"]))

    def test_collector_service_template_rejects_remote_host_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "service-template", "--host", "0.0.0.0", "--json")
            self.assertNotEqual(code, 0, out)
            self.assertIn("loopback-bound", out)

    def test_collector_service_lifecycle_generates_cross_platform_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "service-lifecycle"
            code, out = self.run_cli("--root", tmp, "collector", "service-lifecycle", "--output", str(output_dir), "--force", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "service_lifecycle")
            self.assertTrue(payload["gate"]["passed"])
            self.assertEqual(payload["actions"], ["install", "start", "stop", "restart", "status", "uninstall"])
            targets = {item["target"] for item in payload["files"]}
            self.assertEqual(targets, {"systemd", "launchd", "windows-task", "readme"})
            roles = {item["role"] for item in payload["files"]}
            self.assertEqual(roles, {"service", "lifecycle", "readme"})
            for item in payload["files"]:
                self.assertTrue(Path(item["path"]).exists(), item)
            systemd_script = (output_dir / "systemd" / "hulun-collector-systemd.sh").read_text(encoding="utf-8")
            launchd_script = (output_dir / "launchd" / "hulun-collector-launchd.sh").read_text(encoding="utf-8")
            windows_script = (output_dir / "windows-task" / "Register-HulunCollectorLifecycle.ps1").read_text(encoding="utf-8")
            for action in ("install", "start", "stop", "restart", "status", "uninstall"):
                self.assertIn(action, systemd_script)
                self.assertIn(action, launchd_script)
                self.assertIn(action, windows_script)
            self.assertIn("systemctl --user", systemd_script)
            self.assertIn("launchctl", launchd_script)
            self.assertIn("ScheduledTask", windows_script)
            combined = "\n".join([systemd_script, launchd_script, windows_script, (output_dir / "README.md").read_text(encoding="utf-8")])
            self.assertIn("127.0.0.1", " ".join(payload["command"]))
            self.assertNotIn("--token", combined)
            self.assertNotIn("0.0.0.0", combined)

    def test_collector_service_lifecycle_rejects_remote_host_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "service-lifecycle", "--host", "0.0.0.0", "--json")
            self.assertEqual(code, 2, out)
            self.assertIn("loopback-bound", out)

            code, out = self.run_cli("--root", tmp, "collector", "service-lifecycle", "--json")
            self.assertEqual(code, 0, out)
            code, out = self.run_cli("--root", tmp, "collector", "service-lifecycle", "--json")
            self.assertEqual(code, 2, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "service_lifecycle")
            self.assertIn("Refusing to overwrite", payload["gate"]["failures"][0])

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

    def test_collector_shutdown_check_records_stopped_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("--root", tmp, "collector", "shutdown-check", "--json")
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["operation"], "shutdown_check")
            self.assertTrue(payload["gate"]["passed"], payload["gate"])
            self.assertEqual(payload["response_status"], 202)
            self.assertEqual(payload["managed_flush"]["imported"], 1)
            shutdown = payload["shutdown"]
            self.assertEqual(shutdown["operation"], "shutdown")
            self.assertTrue(shutdown["gate"]["passed"])
            self.assertTrue(shutdown["server"]["shutdown_requested"])
            self.assertTrue(shutdown["server"]["shutdown_completed"])
            self.assertTrue(shutdown["manager"]["stopped"])
            self.assertTrue(shutdown["serve_thread"]["stopped"])
            runtime = shutdown["runtime"]
            self.assertEqual(runtime["lifecycle_state"], "stopped")
            self.assertEqual(runtime["stop_reason"], "shutdown_check")
            self.assertIsNotNone(runtime["stopping_at"])
            self.assertIsNotNone(runtime["stopped_at"])
            self.assertGreaterEqual(runtime["uptime_seconds"], 0)
            final_runtime = payload["final_status"]["managed"]["runtime"]
            self.assertEqual(final_runtime["lifecycle_state"], "stopped")
            self.assertEqual(final_runtime["stop_reason"], "shutdown_check")

    def test_status_reports_managed_runtime_after_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=1, scan_on_flush=True, init_if_missing=True)
            runtime_state = CollectorRuntimeState()
            server = build_collector_server(config, runtime_state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]
            base_url = f"http://{host}:{port}"
            try:
                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload())
                self.assertEqual(code, 202)
                flush = collector_flush_once(config, runtime_state)
                self.assertTrue(flush["gate"]["passed"])
                self.assertEqual(flush["imported"], 1)

                code, body = request_json(f"{base_url}/status")
                self.assertEqual(code, 200)
                managed = body["managed"]
                self.assertTrue(managed["enabled"])
                self.assertEqual(managed["runtime"]["flush_count"], 1)
                self.assertEqual(managed["runtime"]["imported_total"], 1)
                self.assertEqual(body["queue"]["pending"], 0)

                code, text, content_type = request_text(f"{base_url}/metrics")
                self.assertEqual(code, 200)
                self.assertIn("text/plain", content_type)
                self.assertIn("hulun_collector_managed_flush_total 1", text)
                self.assertIn("hulun_collector_managed_imported_total 1", text)
                self.assertIn("hulun_collector_queue_pending 0", text)
                self.assertIn('hulun_collector_runtime_state{state="running"} 1', text)
            finally:
                self.stop_server(server, thread)

    def test_managed_loop_records_unexpected_flush_error(self) -> None:
        class OneShotStopEvent:
            def __init__(self) -> None:
                self.calls = 0

            def wait(self, _timeout: float) -> bool:
                self.calls += 1
                return self.calls > 1

        with tempfile.TemporaryDirectory() as tmp:
            config = CollectorConfig(root=tmp, port=0, flush_interval_seconds=1)
            runtime_state = CollectorRuntimeState()
            with mock.patch.object(collector_module, "collector_flush_once", side_effect=RuntimeError("transient flush failure")):
                collector_module._flush_loop(config, runtime_state, OneShotStopEvent())  # noqa: SLF001
            self.assertEqual(runtime_state.last_error["code"], "managed_loop_failed")
            self.assertIn("transient flush failure", runtime_state.last_error["message"])

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

                code, text, _content_type = request_text(f"{base_url}/metrics")
                self.assertEqual(code, 401)
                self.assertIn("unauthorized", text)

                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload())
                self.assertEqual(code, 401)
                self.assertEqual(body["error"]["code"], "unauthorized")

                code, body = request_json(f"{base_url}/v1/traces", method="POST", payload=otlp_payload(), headers={"X-Hulun-Token": "secret-token"})
                self.assertEqual(code, 202)
                self.assertEqual(body["queued"], 1)

                code, text, _content_type = request_text(f"{base_url}/metrics", headers={"X-Hulun-Token": "secret-token"})
                self.assertEqual(code, 200)
                self.assertIn("hulun_collector_queue_pending 1", text)
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
        with self.assertRaises(CollectorError):
            build_collector_server(CollectorConfig(port=0, flush_interval_seconds=-1))


if __name__ == "__main__":
    unittest.main()
