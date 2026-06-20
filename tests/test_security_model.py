from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hulun_guard.adapters import MAX_TRACE_BYTES
from hulun_guard.cli import main
from hulun_guard.security import run_threat_model_check


def run_cli(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


class SecurityModelTest(unittest.TestCase):
    def test_threat_model_check_passes_and_covers_trace_cap(self) -> None:
        code, out = run_cli("threat-model-check", "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], "hulun.threat_model_check.v1")
        self.assertTrue(payload["gate"]["passed"])
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertEqual(checks["trace_size_cap"]["status"], "ok")
        self.assertIn(str(MAX_TRACE_BYTES), checks["trace_size_cap"]["detail"])

    def test_threat_model_links_are_enforced(self) -> None:
        result = run_threat_model_check(Path.cwd())
        self.assertTrue(result["gate"]["passed"], result)
        link_checks = [item for item in result["checks"] if item["name"].startswith("link:")]
        self.assertGreaterEqual(len(link_checks), 5)
        self.assertTrue(all(item["status"] == "ok" for item in link_checks))

    def test_oversized_trace_is_rejected_before_persisting_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out = run_cli("--root", tmp, "init", "--objective", "reject large trace", "--criterion", "state survives")
            self.assertEqual(code, 0, out)
            trace = root / "oversized.json"
            trace.write_text(json.dumps({"events": [{"summary": "x" * 256}]}), encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                main(["--root", tmp, "ingest", "--file", str(trace), "--max-trace-bytes", "64"])
            self.assertIn("Trace file is too large", str(raised.exception))

            state = json.loads((root / ".hulun" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual([event["type"] for event in state["events"]], ["init"])
