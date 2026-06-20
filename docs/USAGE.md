# HulunGuard Usage

## Start Fast

```powershell
python .\hulun.py quickstart
python .\hulun.py doctor
```

`quickstart` prints a project-specific copy-paste path. `doctor` checks version, state, evidence, checkpoint, and current HulunIndex.

## Open A Desktop HulunGauge

```powershell
python .\hulun.py open --conversation "Codex long task" --group "My Project" --widget
```

- Single-click and drag the bar to move it.
- Double-click the bar to close it.
- Green: continue.
- Yellow: checkpoint or calibrate.
- Red: do not claim completion.

## Update A Conversation

```powershell
python .\hulun.py update --id M1 --score 70 --summary "Tool failed and no evidence yet" --reason "Unresolved failure"
python .\hulun.py update --id M1 --delta -25 --summary "Tests passed and evidence was recorded"
python .\hulun.py update --id M1 --group "New Project Group"
```

## Record Realtime HulunIndex Signals

Use `observe` when an agent, hook, or adapter wants to record runtime behavior:

```powershell
python .\hulun.py observe --type tool_result --phase verify --result fail --summary "pytest failed" --action-key "pytest" --scan
python .\hulun.py observe --type final_attempt --phase final --summary "Task is complete" --claim "complete and verified" --scan
python .\hulun.py observe --type llm_call --phase summarize --summary "Large summary without new evidence" --prompt-tokens 9000 --completion-tokens 5000 --cost 6.5 --latency-ms 70000 --scan
```

Important fields:

- `--phase`: `explore`, `plan`, `implement`, `verify`, `recover`, `summarize`, `final`, or `orchestrate`.
- `--claim`: a completion or verification claim that must be backed by evidence.
- `--evidence`: evidence ids that support the observation.
- `--action-key`: stable fingerprint used to detect retry loops.
- `--source-platform`: adapter source such as `manual`, `langgraph`, `swe-agent`, `openhands`, `langfuse`, or `phoenix`.
- `--prompt-tokens`, `--completion-tokens`, `--cost`, `--latency-ms`: model pressure signals.

With `--scan`, HulunGuard recalculates `slop_index` immediately and writes `.hulun/risk.json`.

Runtime writes are privacy-safe by default. Summaries, claims, references, action keys, model names, and evidence fields are sanitized before they are persisted. Known secret patterns, emails, private home paths, and URL query strings are removed or replaced with redaction markers.

## Monitor A Live Conversation

Project state monitoring uses `.hulun/state.json`. Conversation runtime monitoring uses separate per-conversation files under `HULUN_HOME/conversations`.

```powershell
python .\hulun.py conversation start --name "Codex live task" --group "HulunGuard" --monitor --widget
python .\hulun.py conversation event --id C1 --type user_message --summary "User asks for a feature"
python .\hulun.py conversation event --id C1 --type assistant_plan --phase plan --summary "Plan the implementation"
python .\hulun.py conversation event --id C1 --type tool_call --phase verify --summary "Run pytest" --action-key pytest
python .\hulun.py conversation event --id C1 --type tool_result --phase verify --summary "pytest passed" --action-key pytest
python .\hulun.py conversation event --id C1 --type user_challenge --summary "User says monitoring is not actually live"
python .\hulun.py conversation event --id C1 --type final_attempt --phase final --claim "done" --summary "Ready to final"
python .\hulun.py conversation scan --id C1
```

Conversation risk components:

- `claim_overhang`: final or completion claims without nearby evidence.
- `unresolved_failures`: failed commands/tools not resolved.
- `pending_tools`: tool calls without matching tool results.
- `stagnation`: summaries/plans without execution evidence.
- `user_challenge`: user correction or objection requiring calibration.
- `context_decay`: long conversation without checkpoint.
- `cost_pressure`: high token/cost without nearby execution evidence.

This is the layer to use when you want HulunGuard to judge the agent's live state inside a chat.

## Import External Agent Traces

Use `ingest` to convert trace files into HulunGuard observations:

```powershell
python .\hulun.py ingest --file .\trace.jsonl --format generic --scan
python .\hulun.py ingest --file .\otel-trace.json --format opentelemetry --scan
python .\hulun.py ingest --file .\openinference-trace.json --format openinference --scan
python .\hulun.py ingest --file .\openhands-events.json --format openhands --scan
python .\hulun.py ingest --file .\run.traj --format swe-agent --scan
```

Supported formats:

- `generic`: JSON or JSONL with fields like `type`, `summary`, `result`, `phase`, `claim`, `evidence`, `action_key`, `prompt_tokens`, `completion_tokens`, `cost`, and `latency_ms`.
- `opentelemetry`: OTLP-style JSON/JSONL spans with GenAI `gen_ai.*` attributes.
- `openinference`: OpenInference-style spans with `openinference.span.kind` and LLM/tool attributes.
- `openhands`: maps action/observation/error/condensation-like events into command, tool_result, agent_error, and summary observations.
- `swe-agent`: maps action/observation trajectory steps into command/tool_result observations with retry-loop fingerprints.
- `auto`: guesses from the filename.

Adapter compatibility guarantees are documented in `docs/ADAPTER_CONFORMANCE.md`.

Export HulunGuard events as OTLP-style JSON spans:

```powershell
python .\hulun.py export-otel --output .\hulun-otel.json
```

## Privacy And Retention

HulunGuard is designed to ingest real agent traces without turning the local ledger into a secret dump.

Defaults:

- Raw payload fields such as `content`, `text`, `prompt`, `response`, `output`, `completion`, tool arguments, and tool results are not persisted as summaries unless the trace already provides a safe summary.
- Imported events keep enough structure for scoring: type, phase, result, cost/latency/token pressure, evidence IDs, sanitized refs, and a privacy-preserving action fingerprint.
- Each stored event and evidence record includes `privacy.mode` and `privacy.retention_days`.
- The default retention hint is 30 days.

Use explicit opt-in only for trusted local debugging:

```powershell
python .\hulun.py observe --type llm_call --summary "raw local debug text" --include-sensitive --retention-days 7
python .\hulun.py ingest --file .\trace.jsonl --include-sensitive --retention-days 7
python .\hulun.py conversation event --id C1 --type tool_result --summary "raw local debug text" --include-sensitive --retention-days 7
```

Preview expired local records:

```powershell
python .\hulun.py cleanup --json
```

Apply cleanup only in a trusted local working copy:

```powershell
python .\hulun.py cleanup --apply --write-report
```

`cleanup` prunes expired project events, evidence records, conversation events, stale scans, and generated `.hulun/` reports. It refuses to delete anything outside the project `.hulun` directory or `HULUN_HOME/conversations`. See `docs/RETENTION.md`.

## Run Release Validation

Before publishing a new version:

```powershell
python .\hulun.py validate
python .\hulun.py calibrate
python .\hulun.py calibration-drift
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python -m pytest -q
```

`validate` writes `.hulun/validation_report.md` and `.hulun/validation_report.json`.
`calibrate` writes `.hulun/calibration_report.md` and `.hulun/calibration_report.json` with component support, precision, recall, false-positive rate, false-negative rate, source coverage, workflow coverage, and redaction coverage over 100 labeled trajectories.
`calibration-drift` writes `.hulun/calibration_drift_report.md` and `.hulun/calibration_drift_report.json` by comparing current calibration against `docs/calibration_baseline.json`. Regressions fail unless `--rationale` is provided for an intentional review.

## Benchmark Scan Performance

Use `benchmark` before releases or after scoring changes:

```powershell
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --events 50000 --max-ms 1000
```

`benchmark` writes `.hulun/benchmark_report.json` and returns exit code `2` if `--max-ms` is exceeded.

## Real-World Benchmark Suite

Use `benchmark --suite real-world` to run the public-safe workflow suite separately from calibration:

```powershell
python .\hulun.py benchmark --suite real-world
python .\hulun.py benchmark --suite real-world --json
```

The suite covers coding, research, ops, and artifact workflows. It measures scan latency, fixture size, component stability, false-positive rate, and false-negative rate, then writes `.hulun/real_world_benchmark_report.json` and `.hulun/real_world_benchmark_report.md`.

Maintainer rules for adding cases are documented in `docs/REAL_WORLD_BENCHMARKS.md`.

## Open The Project Board

```powershell
python .\hulun.py board --serve --open
```

This opens:

```text
http://127.0.0.1:8766/board.html
```

The board shows all active monitors and group-level risk averages.

## Universal Agent Prompt

Generate a pasteable startup code for any agent:

```powershell
python .\hulun.py prompt --conversation "Claude task" --group "Research"
```

Paste the output into the target agent. It starts with:

```text
#HULUN_ON
```

Any agent that can run shell commands can then open its own widget and update the same board.

## Use The Python SDK

```python
from hulun_guard import HulunGuardClient

client = HulunGuardClient(".")
client.init(
    objective="Ship an evidence-backed agent workflow",
    criteria=["final claims have verification evidence"],
)
client.observe(
    event_type="tool_result",
    phase="verify",
    summary="pytest passed",
    result="pass",
    source_platform="my-agent",
    action_key="pytest",
    scan=True,
)
```

For live conversation monitoring:

```python
conversation = client.start_conversation(name="agent-live-task", group="HulunGuard")
client.conversation_event(
    conversation_id=conversation["id"],
    event_type="tool_call",
    phase="verify",
    summary="Run pytest",
    action_key="pytest",
)
```

## Run The MCP Server

```powershell
hulun-mcp --root .
python -m hulun_guard.mcp --root .
python .\hulun.py --root . mcp
```

The MCP server exposes project init, observe, scan, conversation start, conversation event, and conversation scan tools. See `docs/SDK_AND_MCP.md`.
