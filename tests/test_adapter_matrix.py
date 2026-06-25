from __future__ import annotations

import contextlib
import io
import json
import unittest

from hulun_guard.adapter_matrix import FORBIDDEN_VALUES, run_adapter_matrix
from hulun_guard.cli import main
from hulun_guard.schemas import ADAPTER_MATRIX_SCHEMA


def run_cli(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


class AdapterMatrixTest(unittest.TestCase):
    def test_adapter_matrix_gate_covers_roundtrip_and_stream_surfaces(self) -> None:
        result = run_adapter_matrix()

        self.assertEqual(result["schema"], ADAPTER_MATRIX_SCHEMA)
        self.assertEqual(result["fixture_policy"], "synthetic-public-safe-no-private-traces")
        self.assertTrue(result["gate"]["passed"], result["gate"]["failures"])
        self.assertEqual(result["gate"]["case_count"], 11)

        cases = {case["name"]: case for case in result["cases"]}
        self.assertEqual(
            set(cases),
            {
                "opentelemetry_roundtrip",
                "openinference_roundtrip",
                "langfuse_otel_roundtrip",
                "phoenix_openinference_roundtrip",
                "openhands_stream",
                "swe_agent_stream",
                "langgraph_stream",
                "langsmith_run_export",
                "langsmith_service_export",
                "langfuse_service_export",
                "openai_agents_trace_export",
            },
        )
        self.assertEqual(cases["opentelemetry_roundtrip"]["tier"], "roundtrip-tested")
        self.assertEqual(cases["openinference_roundtrip"]["tier"], "roundtrip-tested")
        self.assertEqual(cases["langfuse_otel_roundtrip"]["tier"], "roundtrip-tested")
        self.assertEqual(cases["phoenix_openinference_roundtrip"]["tier"], "roundtrip-tested")
        self.assertEqual(cases["langgraph_stream"]["tier"], "hosted-fixture-tested")
        self.assertEqual(cases["langsmith_run_export"]["tier"], "hosted-fixture-tested")
        self.assertEqual(cases["langsmith_service_export"]["tier"], "native-export-tested")
        self.assertEqual(cases["langfuse_service_export"]["tier"], "native-export-tested")
        self.assertEqual(cases["openai_agents_trace_export"]["tier"], "integration-tested")
        self.assertEqual(cases["openhands_stream"]["input_events"], 6)
        self.assertEqual(cases["swe_agent_stream"]["output_events"], 6)
        self.assertEqual(cases["langgraph_stream"]["output_events"], 6)
        self.assertEqual(cases["langsmith_run_export"]["input_events"], 6)
        self.assertEqual(cases["langsmith_service_export"]["output_events"], 2)
        self.assertEqual(cases["langfuse_service_export"]["output_events"], 2)
        self.assertEqual(cases["openai_agents_trace_export"]["output_events"], 6)

        for case in result["cases"]:
            with self.subTest(case=case["name"]):
                self.assertTrue(case["passed"], case["checks"])
                self.assertEqual(case["failure_count"], 0)
                self.assertTrue(all(check["passed"] for check in case["checks"]))

        tiers = {tier["tier"]: tier["surfaces"] for tier in result["support_tiers"]}
        self.assertIn("opentelemetry", tiers["integration-tested"])
        self.assertIn("openai-agents", tiers["integration-tested"])
        self.assertIn("openinference", tiers["roundtrip-tested"])
        self.assertIn("langgraph", tiers["hosted-fixture-tested"])
        self.assertIn("langsmith-file-export", tiers["hosted-fixture-tested"])
        self.assertIn("langsmith-service-export", tiers["native-export-tested"])
        self.assertIn("langfuse-service-export", tiers["native-export-tested"])
        self.assertIn("langfuse", tiers["hosted-fixture-tested"])
        self.assertIn("phoenix", tiers["hosted-fixture-tested"])
        self.assertIn("sdk", tiers["conformance"])
        self.assertIn("custom-json", tiers["best-effort"])

        serialized = json.dumps(result, ensure_ascii=False)
        for forbidden in FORBIDDEN_VALUES:
            self.assertNotIn(forbidden, serialized)

    def test_adapter_matrix_cli_json(self) -> None:
        code, out = run_cli("adapter-matrix", "--json")

        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], ADAPTER_MATRIX_SCHEMA)
        self.assertTrue(payload["gate"]["passed"], payload["gate"]["failures"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
