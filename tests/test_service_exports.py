from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hulun_guard.adapters import iter_observations
from hulun_guard.cli import main
from hulun_guard.service_exports import (
    JsonPostResponse,
    LangfuseServiceConfig,
    LangSmithServiceConfig,
    ServiceExportError,
    export_langfuse_observations,
    export_langsmith_runs,
)
from hulun_guard.trace_diagnostics import diagnose_trace_file

PRIVATE_KEY_MARKER = "sk-" + "service" + "secret" + "012345678901234567890"
EMAIL_MARKER = "service@example.com"
AUTH_MARKER = "password=" + "hunter" + "2"


def run_cli(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


class ServiceExportTest(unittest.TestCase):
    def test_langsmith_export_writes_redacted_importable_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "langsmith-runs.json"
            requests: list[dict[str, object]] = []

            def transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: float) -> JsonPostResponse:
                requests.append({"url": url, "headers": dict(headers), "payload": dict(payload), "timeout_seconds": timeout_seconds})
                return JsonPostResponse(
                    status=200,
                    body={
                        "items": [
                            {
                                "id": "run-success",
                                "trace_id": "trace-service",
                                "run_type": "llm",
                                "name": "fixture llm call",
                                "status": "success",
                                "prompt_tokens": 123,
                                "completion_tokens": 45,
                                "total_cost": 0.67,
                                "latency_ms": 890,
                                "inputs": {"prompt": PRIVATE_KEY_MARKER},
                            },
                            {
                                "id": "run-error",
                                "trace_id": "trace-service",
                                "run_type": "tool",
                                "name": "fixture tool call",
                                "status": "error",
                                "error": f"tool failed with {PRIVATE_KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                            },
                        ],
                        "next_cursor": None,
                    },
                )

            report = export_langsmith_runs(
                LangSmithServiceConfig(
                    endpoint="http://127.0.0.1:1",
                    api_key="fixture-api-key",
                    project_id="project-public",
                    output=output,
                    page_size=50,
                    max_runs=10,
                ),
                transport=transport,
            )

            self.assertEqual(report["schema"], "hulun.service_export.v1")
            self.assertTrue(report["gate"]["passed"])
            self.assertEqual(report["exported"]["run_count"], 2)
            self.assertIn("trace-doctor --format langsmith", report["exported"]["trace_doctor_command"])
            self.assertEqual(requests[0]["headers"]["X-Api-Key"], "fixture-api-key")
            self.assertNotIn("INPUTS", requests[0]["payload"]["selects"])

            text = output.read_text(encoding="utf-8")
            self.assertNotIn("fixture-api-key", text)
            self.assertNotIn(PRIVATE_KEY_MARKER, text)
            self.assertNotIn(EMAIL_MARKER, text)
            self.assertNotIn("hunter2", text)
            self.assertNotIn("inputs", text)

            observations = list(iter_observations(output, "langsmith"))
            self.assertEqual(len(observations), 2)
            self.assertEqual({item["source_platform"] for item in observations}, {"langsmith"})
            self.assertTrue(any(item["type"] == "llm_call" for item in observations))
            self.assertTrue(any(item["result"] == "fail" for item in observations))

            doctor = diagnose_trace_file(output, source_format="auto")
            self.assertTrue(doctor["gate"]["passed"], doctor["gate"]["failures"])
            self.assertEqual(doctor["detected_format"], "langsmith")
            self.assertIn("ingest --format langsmith", doctor["next_command"])

    def test_langsmith_export_auth_failure_hides_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def transport(_url: str, _headers: dict[str, str], _payload: dict[str, object], _timeout_seconds: float) -> JsonPostResponse:
                return JsonPostResponse(status=401, body={"detail": "bad key"})

            with self.assertRaises(ServiceExportError) as context:
                export_langsmith_runs(
                    LangSmithServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        api_key="fixture-api-key",
                        project_id="project-public",
                        output=Path(tmp) / "out.json",
                    ),
                    transport=transport,
                )
            self.assertIn("authentication failed", str(context.exception))
            self.assertNotIn("fixture-api-key", str(context.exception))

    def test_langsmith_export_pagination_partial_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[dict[str, object]] = []

            def transport(_url: str, _headers: dict[str, str], payload: dict[str, object], _timeout_seconds: float) -> JsonPostResponse:
                calls.append(dict(payload))
                return JsonPostResponse(
                    status=200,
                    body={
                        "items": [
                            {"id": "run-a", "trace_id": "trace-a", "run_type": "chain", "name": "a", "status": "success"},
                            {"id": "run-b", "trace_id": "trace-b", "run_type": "chain", "name": "b", "status": "success"},
                        ],
                        "next_cursor": "cursor-b",
                    },
                )

            report = export_langsmith_runs(
                LangSmithServiceConfig(
                    endpoint="http://127.0.0.1:1",
                    api_key="fixture-api-key",
                    project_id="project-public",
                    output=Path(tmp) / "out.json",
                    page_size=10,
                    max_runs=1,
                ),
                transport=transport,
            )

            self.assertEqual(report["exported"]["run_count"], 1)
            self.assertTrue(report["pagination"]["truncated"])
            self.assertTrue(report["pagination"]["next_cursor_present"])
            self.assertEqual(report["pagination"]["pages_fetched"], 1)
            self.assertEqual(calls[0]["page_size"], 1)

    def test_langsmith_export_malformed_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def transport(_url: str, _headers: dict[str, str], _payload: dict[str, object], _timeout_seconds: float) -> JsonPostResponse:
                return JsonPostResponse(status=200, body={"unexpected": []})

            with self.assertRaises(ServiceExportError) as context:
                export_langsmith_runs(
                    LangSmithServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        api_key="fixture-api-key",
                        project_id="project-public",
                        output=Path(tmp) / "out.json",
                    ),
                    transport=transport,
                )
            self.assertIn("runs/items", str(context.exception))

    def test_langsmith_service_export_cli_requires_explicit_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as context:
                run_cli(
                    "service-export",
                    "langsmith",
                    "--project-id",
                    "project-public",
                    "--output",
                    str(Path(tmp) / "out.json"),
                    "--json",
                )
            self.assertIn("explicit credentials", str(context.exception))

    def test_langfuse_export_writes_redacted_importable_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "langfuse-observations.json"
            requests: list[dict[str, object]] = []

            def transport(url: str, headers: dict[str, str], timeout_seconds: float) -> JsonPostResponse:
                requests.append({"url": url, "headers": dict(headers), "timeout_seconds": timeout_seconds})
                return JsonPostResponse(
                    status=200,
                    body={
                        "data": [
                            {
                                "id": "obs-generation",
                                "traceId": "trace-service",
                                "type": "GENERATION",
                                "name": "fixture generation",
                                "level": "DEFAULT",
                                "startTime": "2026-06-25T00:00:00Z",
                                "endTime": "2026-06-25T00:00:02Z",
                                "inputUsage": 123,
                                "outputUsage": 45,
                                "totalCost": 0.67,
                                "providedModelName": "gpt-service",
                                "input": {"prompt": PRIVATE_KEY_MARKER},
                            },
                            {
                                "id": "obs-error",
                                "traceId": "trace-service",
                                "type": "SPAN",
                                "name": "fixture tool call",
                                "level": "ERROR",
                                "statusMessage": f"tool failed with {PRIVATE_KEY_MARKER} for {EMAIL_MARKER} and {AUTH_MARKER}",
                            },
                        ],
                        "meta": {"cursor": None},
                    },
                )

            report = export_langfuse_observations(
                LangfuseServiceConfig(
                    endpoint="http://127.0.0.1:1",
                    public_key="pk-fixture-public",
                    secret_key="sk-fixture-secret",
                    output=output,
                    from_start_time="2026-06-25T00:00:00Z",
                    to_start_time="2026-06-25T01:00:00Z",
                    limit=50,
                    max_observations=10,
                ),
                transport=transport,
            )

            self.assertEqual(report["schema"], "hulun.service_export.v1")
            self.assertTrue(report["gate"]["passed"])
            self.assertEqual(report["exported"]["observation_count"], 2)
            self.assertEqual(report["exported"]["format"], "generic")
            self.assertIn("trace-doctor --format generic", report["exported"]["trace_doctor_command"])
            self.assertNotIn("pk-fixture-public", json.dumps(report, ensure_ascii=False))
            self.assertNotIn("sk-fixture-secret", json.dumps(report, ensure_ascii=False))
            self.assertEqual(requests[0]["headers"]["Authorization"], "Basic cGstZml4dHVyZS1wdWJsaWM6c2stZml4dHVyZS1zZWNyZXQ=")
            query = parse_qs(urlsplit(str(requests[0]["url"])).query)
            self.assertEqual(query["fields"], ["core,basic,usage,trace_context"])
            self.assertEqual(query["fromStartTime"], ["2026-06-25T00:00:00Z"])
            self.assertEqual(query["toStartTime"], ["2026-06-25T01:00:00Z"])
            self.assertNotIn("io", query["fields"][0])

            text = output.read_text(encoding="utf-8")
            self.assertNotIn("pk-fixture-public", text)
            self.assertNotIn("sk-fixture-secret", text)
            self.assertNotIn(PRIVATE_KEY_MARKER, text)
            self.assertNotIn(EMAIL_MARKER, text)
            self.assertNotIn("hunter2", text)
            self.assertNotIn("input", text)

            observations = list(iter_observations(output, "generic"))
            self.assertEqual(len(observations), 2)
            self.assertEqual({item["source_platform"] for item in observations}, {"langfuse"})
            self.assertTrue(any(item["type"] == "llm_call" for item in observations))
            self.assertTrue(any(item["result"] == "fail" for item in observations))

            doctor = diagnose_trace_file(output, source_format="auto")
            self.assertTrue(doctor["gate"]["passed"], doctor["gate"]["failures"])
            self.assertEqual(doctor["detected_format"], "generic")
            self.assertIn("ingest --format generic", doctor["next_command"])

    def test_langfuse_export_auth_failure_hides_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def transport(_url: str, _headers: dict[str, str], _timeout_seconds: float) -> JsonPostResponse:
                return JsonPostResponse(status=401, body={"message": "bad key"})

            with self.assertRaises(ServiceExportError) as context:
                export_langfuse_observations(
                    LangfuseServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        public_key="pk-fixture-public",
                        secret_key="sk-fixture-secret",
                        output=Path(tmp) / "out.json",
                        from_start_time="2026-06-25T00:00:00Z",
                        to_start_time="2026-06-25T01:00:00Z",
                    ),
                    transport=transport,
                )
            self.assertIn("authentication failed", str(context.exception))
            self.assertNotIn("pk-fixture-public", str(context.exception))
            self.assertNotIn("sk-fixture-secret", str(context.exception))

    def test_langfuse_export_pagination_partial_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[str] = []

            def transport(url: str, _headers: dict[str, str], _timeout_seconds: float) -> JsonPostResponse:
                calls.append(url)
                return JsonPostResponse(
                    status=200,
                    body={
                        "data": [
                            {"id": "obs-a", "traceId": "trace-a", "type": "EVENT", "name": "a", "level": "DEFAULT"},
                            {"id": "obs-b", "traceId": "trace-b", "type": "EVENT", "name": "b", "level": "DEFAULT"},
                        ],
                        "meta": {"cursor": "cursor-b"},
                    },
                )

            report = export_langfuse_observations(
                LangfuseServiceConfig(
                    endpoint="http://127.0.0.1:1",
                    public_key="pk-fixture-public",
                    secret_key="sk-fixture-secret",
                    output=Path(tmp) / "out.json",
                    from_start_time="2026-06-25T00:00:00Z",
                    to_start_time="2026-06-25T01:00:00Z",
                    limit=10,
                    max_observations=1,
                ),
                transport=transport,
            )

            self.assertEqual(report["exported"]["observation_count"], 1)
            self.assertTrue(report["pagination"]["truncated"])
            self.assertTrue(report["pagination"]["next_cursor_present"])
            self.assertEqual(report["pagination"]["pages_fetched"], 1)
            query = parse_qs(urlsplit(calls[0]).query)
            self.assertEqual(query["limit"], ["1"])

    def test_langfuse_export_malformed_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def transport(_url: str, _headers: dict[str, str], _timeout_seconds: float) -> JsonPostResponse:
                return JsonPostResponse(status=200, body={"unexpected": []})

            with self.assertRaises(ServiceExportError) as context:
                export_langfuse_observations(
                    LangfuseServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        public_key="pk-fixture-public",
                        secret_key="sk-fixture-secret",
                        output=Path(tmp) / "out.json",
                        from_start_time="2026-06-25T00:00:00Z",
                        to_start_time="2026-06-25T01:00:00Z",
                    ),
                    transport=transport,
                )
            self.assertIn("data/observations/items", str(context.exception))

    def test_langfuse_export_requires_bounded_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ServiceExportError) as context:
                export_langfuse_observations(
                    LangfuseServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        public_key="pk-fixture-public",
                        secret_key="sk-fixture-secret",
                        output=Path(tmp) / "out.json",
                        from_start_time="2026-06-25T01:00:00Z",
                        to_start_time="2026-06-25T00:00:00Z",
                    ),
                    transport=lambda _url, _headers, _timeout: JsonPostResponse(status=200, body={"data": []}),
                )
            self.assertIn("earlier than to-start-time", str(context.exception))

    def test_langfuse_export_rejects_raw_field_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ServiceExportError) as context:
                export_langfuse_observations(
                    LangfuseServiceConfig(
                        endpoint="http://127.0.0.1:1",
                        public_key="pk-fixture-public",
                        secret_key="sk-fixture-secret",
                        output=Path(tmp) / "out.json",
                        from_start_time="2026-06-25T00:00:00Z",
                        to_start_time="2026-06-25T01:00:00Z",
                        fields="core,basic,io",
                    ),
                    transport=lambda _url, _headers, _timeout: JsonPostResponse(status=200, body={"data": []}),
                )
            self.assertIn("must not include raw field groups", str(context.exception))

    def test_langfuse_service_export_cli_requires_explicit_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as context:
                run_cli(
                    "service-export",
                    "langfuse",
                    "--output",
                    str(Path(tmp) / "out.json"),
                    "--from-start-time",
                    "2026-06-25T00:00:00Z",
                    "--to-start-time",
                    "2026-06-25T01:00:00Z",
                    "--json",
                )
            self.assertIn("explicit public key", str(context.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
