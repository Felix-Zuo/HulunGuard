# HulunGuard Usage

## Start Fast

```powershell
python .\hulun.py onboard --agent langgraph
python .\hulun.py quickstart
python .\hulun.py doctor
```

`onboard` generates and verifies a supported agent path. `quickstart` prints a project-specific copy-paste path. `trace-doctor` diagnoses a trace before import. `doctor` checks version, state, evidence, checkpoint, and current HulunIndex.

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

## Diagnose A Trace Before Import

Use `trace-doctor` before importing a real agent trace. It checks file size, JSON parseability, detected format, adapter importability, field coverage, privacy mode, and the exact ingest command to run next. It does not write `.hulun/state.json`.

```powershell
python .\hulun.py trace-doctor --file .\trace.jsonl --json
python .\hulun.py trace-doctor --file .\otel-trace.json --format opentelemetry --json
python .\hulun.py trace-doctor --file .\trace.jsonl --strict --json
```

Use `--strict` when onboarding a connector and you want missing phases, action keys, refs, or generic-bridge usage to fail the gate instead of returning warnings.

## Import External Agent Traces

Use `ingest` to convert trace files into HulunGuard observations:

```powershell
python .\hulun.py ingest --file .\trace.jsonl --format generic --scan
python .\hulun.py ingest --file .\otel-trace.json --format opentelemetry --scan
python .\hulun.py ingest --file .\openinference-trace.json --format openinference --scan
python .\hulun.py ingest --file .\openhands-events.json --format openhands --scan
python .\hulun.py ingest --file .\run.traj --format swe-agent --scan
python .\hulun.py ingest --file .\langgraph-stream.json --format langgraph --scan
python .\hulun.py ingest --file .\langsmith-runs.json --format langsmith --scan
python .\hulun.py ingest --file .\langfuse-otel.json --format langfuse --scan
python .\hulun.py ingest --file .\phoenix-openinference.json --format phoenix --scan
python .\hulun.py ingest --file .\openai-agents-trace.json --format openai-agents --scan
```

For first-run onboarding in an empty project, allow ingest to create a minimal ledger:

```powershell
python .\hulun.py ingest --file .\trace.jsonl --format generic --scan --init-if-missing
```

Supported formats:

- `generic`: JSON or JSONL with fields like `type`, `summary`, `result`, `phase`, `claim`, `evidence`, `action_key`, `prompt_tokens`, `completion_tokens`, `cost`, and `latency_ms`.
- `opentelemetry`: OTLP-style JSON/JSONL spans with GenAI `gen_ai.*` attributes.
- `openinference`: OpenInference-style spans with `openinference.span.kind` and LLM/tool attributes.
- `openhands`: maps action/observation/error/condensation-like events into command, tool_result, agent_error, and summary observations.
- `swe-agent`: maps action/observation trajectory steps into command/tool_result observations with retry-loop fingerprints.
- `langgraph`: maps stream parts such as updates, values, messages, custom data, checkpoints, tasks, and debug records into runtime observations.
- `langsmith`: maps run exports into LLM calls, tool results, sources, commands, and agent errors.
- `langfuse`: maps Langfuse OTEL traces through the OpenTelemetry adapter while preserving `source_platform=langfuse`.
- `phoenix`: maps Phoenix/OpenInference spans through the OpenInference adapter while preserving `source_platform=phoenix`.
- `openai-agents`: maps OpenAI Agents SDK trace/span exports into LLM calls, tool results, handoffs, guardrails, commands, and agent errors.
- `auto`: guesses from the filename.

Adapter compatibility guarantees are documented in `docs/ADAPTER_CONFORMANCE.md`. Integration-tested adapter tiers are documented in `docs/ADAPTER_MATRIX.md`.
Mainstream agent compatibility paths are documented in `docs/AGENT_COMPATIBILITY.md`.

Trace imports reject files larger than the configured `--max-trace-bytes` limit before parsing. The default is 5 MiB. The full security boundary is documented in `docs/THREAT_MODEL.md`.

## Export From Hosted Observability Services

Use `service-export` when traces already live in a hosted observability service and you want a bounded local file for `trace-doctor` and `ingest`.

LangSmith exports are explicit and bounded:

```powershell
$env:LANGSMITH_API_KEY = "<key>"
python .\hulun.py service-export langsmith --project-id "<project-id>" --api-key-env LANGSMITH_API_KEY --output .\langsmith-runs.json --max-runs 100 --json
python .\hulun.py trace-doctor --format langsmith --file .\langsmith-runs.json --json
python .\hulun.py ingest --format langsmith --file .\langsmith-runs.json --scan --init-if-missing
```

Langfuse exports use the Observations API v2 and require a bounded time window:

```powershell
$env:LANGFUSE_PUBLIC_KEY = "<public-key>"
$env:LANGFUSE_SECRET_KEY = "<secret-key>"
python .\hulun.py service-export langfuse --public-key-env LANGFUSE_PUBLIC_KEY --secret-key-env LANGFUSE_SECRET_KEY --from-start-time "2026-06-25T00:00:00Z" --to-start-time "2026-06-25T01:00:00Z" --output .\langfuse-observations.json --max-observations 100 --json
python .\hulun.py trace-doctor --format generic --file .\langfuse-observations.json --json
python .\hulun.py ingest --format generic --file .\langfuse-observations.json --scan --init-if-missing
```

No service export runs unless the endpoint, credential source, output path, and required service-specific bounds are supplied. Credentials are used only for request headers and are not written to reports or exported files. The default selected fields exclude raw inputs, outputs, prompts, completions, attachments, and tool arguments.

The service export boundary is documented in `docs/SERVICE_EXPORTS.md`.

Export HulunGuard events as OTLP-style JSON spans:

```powershell
python .\hulun.py export-otel --output .\hulun-otel.json
```

## Batched Runtime Ingestion

Use `batch` when an agent emits events continuously and the adapter should avoid opening and rewriting `.hulun/state.json` for every event:

```powershell
python .\hulun.py batch enqueue --type tool_result --phase verify --summary "pytest passed" --result pass
python .\hulun.py batch ingest-file --file .\trace.jsonl --format generic
'{"events":[{"type":"tasks","event_type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest"}]}' | python .\hulun.py batch ingest-stdin --format langgraph
python .\hulun.py batch status
python .\hulun.py batch flush --limit 500 --scan
```

Behavior:

- `batch enqueue` writes one normalized observation to `.hulun/ingest_queue.jsonl`.
- `batch ingest-file` parses a supported trace format and appends the normalized observations to the same queue.
- `batch ingest-stdin` parses JSON or JSONL from stdin and queues normalized observations without requiring a trace file on disk.
- `batch status` reports pending queue size, queue bytes, parse errors, and dead-letter count.
- `batch flush` moves queued observations into `.hulun/state.json` in bounded batches. Use `--scan` to recompute risk after flushing.
- Malformed queued records are moved to `.hulun/ingest_dead_letter.jsonl` and do not block valid queued observations.
- `--init-if-missing` on `batch flush` creates a minimal project ledger before the first flush.

The JSON output for `batch` commands uses `hulun.batch_ingest.v1`.

Use stdin ingestion when the host runtime already has stream events or spans in memory. Examples include LangGraph stream chunks, LangSmith run dictionaries, OpenAI Agents SDK span export dictionaries, OTLP JSON, OpenInference spans, and generic JSONL events emitted by a custom agent wrapper.

## Run A Local HTTP Collector

Use `collector serve` when an agent runtime can emit OTLP/HTTP JSON or POST adapter payloads during execution:

```powershell
python .\hulun.py collector serve
python .\hulun.py collector serve --flush-interval-seconds 5 --scan-on-flush --init-if-missing
```

Default endpoint:

```text
http://127.0.0.1:4318/v1/traces
```

Machine-check the collector path without leaving a server running:

```powershell
python .\hulun.py collector smoke --json
python .\hulun.py collector smoke --managed --scan --init-if-missing --json
python .\hulun.py collector shutdown-check --json
python .\hulun.py collector status --require-status-file --queue-pending-threshold 100 --json
python .\hulun.py collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python .\hulun.py collector alert-rules --output .\.hulun\collector-alerts --force --json
python .\hulun.py collector service-template --output .\.hulun\collector-service --force --json
python .\hulun.py collector service-lifecycle --output .\.hulun\collector-service-lifecycle --force --json
python .\hulun.py batch status --json
python .\hulun.py batch flush --scan --init-if-missing --json
```

Supported POST routes:

- `/v1/traces`: OTLP/HTTP JSON traces.
- `/ingest`: auto-detected JSON or JSONL runtime payload.
- `/ingest/<format>`: explicit adapter payload, such as `generic`, `langgraph`, `langsmith`, `langfuse`, `phoenix`, or `openai-agents`.

The collector writes to the same durable queue as `batch`. Queue-only mode does not update `.hulun/state.json` on every request; run `batch flush --scan` to import queued observations and recompute risk. Managed mode enables a periodic flush loop, writes `.hulun/collector_status.json`, and can update `.hulun/risk.json` automatically after successful flushes. Use `collector shutdown-check` to verify graceful stop handling, `collector status` for offline service checks and grouped operator diagnostics, `collector metrics` or `GET /metrics` for Prometheus monitoring, `collector alert-rules` for reviewed Prometheus alerting rules, `collector service-template` to generate service files, and `collector service-lifecycle` to generate reviewed install/start/stop/restart/status/uninstall controls for managed mode.

Security defaults:

- loopback bind only unless `--allow-remote` is set
- non-loopback bind requires `--token`
- protobuf payloads are rejected; use OTLP/HTTP JSON
- `--max-payload-bytes` defaults to the same 5 MiB runtime payload cap
- `/healthz` is public; `/status` and POST requests require a token when configured

See `docs/COLLECTOR.md` for endpoint and adapter examples.

## Check Agent Compatibility

Use `compatibility` to see whether an agent framework has a direct adapter, a standards path, or the generic bridge:

```powershell
python .\hulun.py compatibility
python .\hulun.py compatibility --json
```

The matrix covers OpenHands, SWE-agent, LangGraph, LangSmith, Langfuse, Phoenix, OpenTelemetry GenAI emitters, OpenInference emitters, AutoGen, CrewAI, LlamaIndex, Haystack, Semantic Kernel, OpenAI Agents SDK, and custom agents that can write JSON/JSONL records.

## Generate Integration Kits

Use `onboard` when a user wants HulunGuard to generate a kit, verify the sample trace, import the sample in an isolated sandbox, and return the real next command:

```powershell
python .\hulun.py onboard --agent langgraph
python .\hulun.py onboard --agent all --output .\.hulun\onboarding --force --json
```

Use `integration-kit` when a user needs a runnable first-run package for a specific agent or trace format:

```powershell
python .\hulun.py integration-kit --agent langgraph --verify
python .\hulun.py integration-kit --agent openai-agents-sdk --verify
python .\hulun.py integration-kit --agent all --output .\.hulun\integration-kits --force --verify
```

Each kit includes a synthetic sample trace, `README.md`, PowerShell and POSIX shell runners, and `hulun_integration.json`. The generated runners use `ingest --init-if-missing` so a fresh project can import the sample without a separate initialization step. The `--verify` flag parses the generated sample trace through the selected adapter without persisting it to the project ledger. `onboard` wraps this with an isolated sandbox import and a `hulun.onboarding.v1` report.

Existing generated files are not overwritten unless `--force` is used.

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
python .\hulun.py threat-model-check --json
python .\hulun.py compatibility --json
python .\hulun.py integration-kit --agent all --output .\.hulun\integration-kits --force --verify --json
python .\hulun.py onboard --agent all --output .\.hulun\onboarding --force --json
python .\hulun.py adapter-matrix --json
python .\hulun.py collector smoke --json
python .\hulun.py collector smoke --managed --scan --init-if-missing --json
python .\hulun.py collector shutdown-check --json
python .\hulun.py collector status --require-status-file --queue-pending-threshold 100 --json
python .\hulun.py collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python .\hulun.py collector alert-rules --output .\.hulun\collector-alerts --force --json
python .\hulun.py collector service-template --output .\.hulun\collector-service --force --json
python .\hulun.py collector service-lifecycle --output .\.hulun\collector-service-lifecycle --force --json
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python -m pytest -q
```

`validate` writes `.hulun/validation_report.md` and `.hulun/validation_report.json`.
`calibrate` writes `.hulun/calibration_report.md` and `.hulun/calibration_report.json` with component support, precision, recall, false-positive rate, false-negative rate, source coverage, workflow coverage, and redaction coverage over 100 labeled trajectories.
`calibration-drift` writes `.hulun/calibration_drift_report.md` and `.hulun/calibration_drift_report.json` by comparing current calibration against `docs/calibration_baseline.json`. Regressions fail unless `--rationale` is provided for an intentional review.
`threat-model-check` verifies that the public threat model exists, is linked from release/security docs, and that trace import keeps a bounded default file-size limit.
`compatibility` reports direct, standards-based, and bridge-based paths for mainstream agent frameworks.
`integration-kit` generates first-run onboarding packages and verifies their sample traces through the matching ingest adapters.
`onboard` verifies generated kits with an isolated sandbox import and returns next-step commands for real traces.
`adapter-matrix` verifies OpenTelemetry/OpenInference/Langfuse/Phoenix round-trips plus OpenHands-like, SWE-agent-like, LangGraph, and LangSmith stream coverage without committing private traces.
`collector smoke` starts a temporary local HTTP collector, POSTs one OTLP/HTTP JSON span, and verifies that the queue grows by one record.
`collector smoke --managed --scan --init-if-missing` verifies that a live POST can be flushed into a fresh project ledger and rescanned without a separate operator command.
`collector shutdown-check` verifies that a temporary collector records `stopping` and final `stopped` runtime state during graceful shutdown.
`collector status` verifies queue, dead-letter, managed status, last risk state, and grouped `diagnostics` without starting the HTTP server.
`collector metrics` verifies the Prometheus health export path used by external service monitors.
`collector alert-rules` verifies that Prometheus alerting rules can be generated for collector health and HulunIndex risk signals.
`collector service-template` verifies that reviewed managed-mode templates can be generated for systemd, launchd, and Windows Scheduled Task.
`collector service-lifecycle` verifies that reviewed install/start/stop/restart/status/uninstall controls can be generated for managed collector services.
`batch ingest-stdin` verifies the runtime pipe path used by agents that emit JSON/JSONL events directly instead of writing trace files.
`schema-check` loads legacy JSON fixtures, normalizes them through the migration layer, and fails if current public schemas are not written. See `docs/SCHEMAS.md`.

## Release Asset Verification

Use `release-verify` after release metadata has been generated:

```powershell
python .\hulun.py release-verify v0.29.0 --json
python .\hulun.py release-verify v0.29.0 --asset-dir .\dist --skip-attestation --json
```

The command checks expected release files, `SHA256SUMS`, CycloneDX SBOM artifact hashes, and GitHub attestations unless `--skip-attestation` is set. It returns `hulun.github_release_verification.v1`.

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

The suite covers 16 public-safe coding, research, ops, and artifact workflows. It measures scan latency, fixture size, component stability, false-positive rate, and false-negative rate, then writes `.hulun/real_world_benchmark_report.json` and `.hulun/real_world_benchmark_report.md`.

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
