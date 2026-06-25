# 糊弄 / HulunGuard

HulunGuard is a proof-first reliability guard and desktop risk meter for long-running AI agent work.

它不是“AI 文风检测器”。它监控的是智能体是否正在失去可验证的任务执行能力：目标漂移、证据不足、上下文断裂、空转总结、工具失败后继续下结论。

Public examples are synthetic. Do not publish private conversation logs,
credentials, customer files, or production records into the repository when
using HulunGuard on real work.

## What Works Now

- Desktop HulunGauge: small always-on-top progress bar, click-drag to move, double-click to close.
- Per-conversation monitors: each conversation gets its own monitor ID.
- Group/project board: active conversations are grouped and averaged into project-level risk.
- Local state ledger: `.hulun/state.json`, `.hulun/resume.md`, `.hulun/risk.json`, `.hulun/verification_report.md`.
- Universal startup prompt: `#HULUN_ON` for any agent that can run shell commands.
- OpenClaw hook: injects HulunGuard guidance into OpenClaw agent bootstrap.
- Realtime HulunIndex observations: record phase, claims, failures, tokens, cost, latency, and retry fingerprints.
- Privacy-safe trace ingestion: import generic JSON/JSONL, OpenTelemetry GenAI, OpenInference, OpenHands-like events, SWE-agent-like trajectories, LangGraph stream parts, LangSmith run exports, Langfuse OTEL traces, and Phoenix/OpenInference spans without persisting raw sensitive payloads by default.
- Native service export: explicitly export bounded LangSmith run-query results into a redacted local file, then inspect with `trace-doctor` and import with `ingest --format langsmith`.
- Runtime payload bridge: SDK, MCP, and stdin ingestion can queue in-memory spans or stream events without writing trace files first.
- Local HTTP collector: accept live OTLP/HTTP JSON traces at `/v1/traces` and adapter payloads at `/ingest/<format>` into the durable queue, with offline operations status, Prometheus metrics, alert rules, service templates, and lifecycle controls for long-running managed mode.
- Python SDK and MCP server: agents can record runtime state directly without shell glue.
- Built-in validation suite: run synthetic healthy/slop-risk scenarios before release.
- Product operations: `onboard`, `quickstart`, `doctor`, `trace-doctor`, `compatibility`, `integration-kit`, `adapter-matrix`, `schema-check`, `release-verify`, `cleanup`, and `benchmark` commands for onboarding, trace diagnostics, agent compatibility, first-run integration packages, adapter integration, schema compatibility, release verification, retention cleanup, scan performance, and public-safe real-world workflow checks.
- Conversation runtime monitoring: per-conversation events, user challenges, pending tool calls, unresolved failures, unsupported final claims, and monitor sync.

## Quick Start

Prove a supported agent path with one command:

```powershell
python .\hulun.py onboard --agent langgraph
python .\hulun.py onboard --agent all --force
```

Print a copy-paste startup path:

```powershell
python .\hulun.py quickstart
```

Open a desktop bar:

```powershell
python .\hulun.py open --conversation "Codex task" --group "Demo Project" --widget
```

Update a monitor:

```powershell
python .\hulun.py update --id M1 --score 72 --summary "Tool failed and no evidence yet" --reason "unresolved failure"
python .\hulun.py update --id M1 --delta -30 --summary "Tests passed and evidence was recorded"
```

Record a realtime agent observation and immediately rescan the slop index:

```powershell
python .\hulun.py observe --type final_attempt --phase final --summary "Everything is completed and verified" --claim "completed and verified" --scan
python .\hulun.py observe --type tool_result --phase verify --result fail --summary "pytest failed" --action-key "pytest" --scan
python .\hulun.py observe --type llm_call --phase summarize --summary "Long summary without evidence" --prompt-tokens 9000 --completion-tokens 5000 --cost 6.5 --latency-ms 70000 --scan
```

Start a true conversation runtime monitor:

```powershell
python .\hulun.py conversation start --name "Codex live task" --group "HulunGuard" --monitor --widget
python .\hulun.py conversation event --id C1 --type user_challenge --summary "User challenged whether monitoring is actually live"
python .\hulun.py conversation event --id C1 --type tool_call --phase verify --summary "Run pytest" --action-key pytest
python .\hulun.py conversation event --id C1 --type tool_result --phase verify --summary "pytest passed" --action-key pytest
python .\hulun.py conversation scan --id C1
```

Conversation monitoring is not magic chat-log access. It becomes live when the agent or adapter records runtime events as they happen.

Import an external trace:

```powershell
python .\hulun.py trace-doctor --file .\trace.jsonl --json
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
python .\hulun.py export-otel --output .\hulun-otel.json
```

For an empty project, add `--init-if-missing` to create the minimal local ledger before import.

Export a bounded LangSmith run slice:

```powershell
$env:LANGSMITH_API_KEY = "<key>"
python .\hulun.py service-export langsmith --project-id "<project-id>" --api-key-env LANGSMITH_API_KEY --output .\langsmith-runs.json --json
python .\hulun.py trace-doctor --format langsmith --file .\langsmith-runs.json --json
python .\hulun.py ingest --format langsmith --file .\langsmith-runs.json --scan --init-if-missing
```

Service exports require explicit credentials and are documented in `docs/SERVICE_EXPORTS.md`.

Queue high-frequency runtime events and flush them in batches:

```powershell
python .\hulun.py batch enqueue --type tool_result --phase verify --summary "pytest passed" --result pass
python .\hulun.py batch ingest-file --file .\trace.jsonl --format generic
'{"events":[{"type":"tasks","event_type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest"}]}' | python .\hulun.py batch ingest-stdin --format langgraph
python .\hulun.py batch status
python .\hulun.py batch flush --limit 500 --scan
```

`batch` writes a durable local JSONL queue first. `ingest-stdin` accepts JSON or JSONL from an agent process, shell pipe, or host runtime. `flush` moves queued observations into `.hulun/state.json`; `flush --scan` then recomputes the HulunIndex from those events.

Run a live local HTTP collector for OTLP/HTTP JSON or adapter payloads:

```powershell
python .\hulun.py collector serve
python .\hulun.py collector serve --flush-interval-seconds 5 --scan-on-flush --init-if-missing
python .\hulun.py collector smoke --json
python .\hulun.py collector smoke --managed --scan --init-if-missing --json
python .\hulun.py collector shutdown-check --json
python .\hulun.py collector status --require-status-file --queue-pending-threshold 100 --json
python .\hulun.py collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python .\hulun.py collector alert-rules --output .\.hulun\collector-alerts --force --json
python .\hulun.py collector service-template --output .\.hulun\collector-service --force --json
python .\hulun.py collector service-lifecycle --output .\.hulun\collector-service-lifecycle --force --json
python .\hulun.py batch flush --scan --init-if-missing
```

The collector listens on `127.0.0.1:4318` by default. `POST /v1/traces` accepts OTLP/HTTP JSON, while `POST /ingest/<format>` accepts adapter payloads such as `generic`, `langgraph`, `langsmith`, `langfuse`, `phoenix`, and `openai-agents`. Queue-only mode is the default. Managed mode periodically flushes queued observations and can update `.hulun/risk.json` automatically. `collector shutdown-check` verifies that a temporary collector can stop gracefully and write a final stopped runtime status. `collector status` reads queue, status, and risk files without opening a server and includes grouped diagnostics with operator actions for queue, status freshness, runtime lifecycle, dead letters, managed flush, and risk. `collector metrics` and `GET /metrics` export Prometheus health metrics without local paths as labels. `collector alert-rules` writes Prometheus alerting rule files for those metrics without installing them or changing Alertmanager routing. `collector service-template` generates systemd, launchd, and Windows Scheduled Task templates without installing them or embedding tokens. `collector service-lifecycle` generates reviewed install/start/stop/restart/status/uninstall controls for those service targets without running them. Non-loopback binds require `--allow-remote --token`.

By default, runtime observations and imported traces redact known secrets, emails, URL query strings, private home paths, and raw payload fields such as prompts, completions, outputs, and tool arguments. Use `--include-sensitive --retention-days 7` only for trusted local debugging.

Check mainstream agent compatibility:

```powershell
python .\hulun.py compatibility
python .\hulun.py compatibility --json
```

Generate a verified onboarding kit for an agent:

```powershell
python .\hulun.py onboard --agent langgraph
python .\hulun.py integration-kit --agent langgraph --verify
python .\hulun.py integration-kit --agent all --output .\.hulun\integration-kits --force --verify
```

The observability surface is documented in `docs/OBSERVABILITY.md`. The security boundary and threat assumptions are documented in `docs/THREAT_MODEL.md`.

Run the release validation suite:

```powershell
python .\hulun.py doctor --run-validation
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
@'
{"type":"tool_result","phase":"verify","summary":"stdin payload passed","result":"pass","action_key":"stdin-smoke"}
'@ | python .\hulun.py batch ingest-stdin --format generic --json
'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest","refs":["command:pytest"]}' | Set-Content -Encoding UTF8 trace-doctor-sample.jsonl
python .\hulun.py trace-doctor --file trace-doctor-sample.jsonl --format generic --json
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python -m pytest -q
python -m build
python scripts/generate_release_metadata.py --verify --json
python scripts/verify_release_artifacts.py
python .\hulun.py release-verify --asset-dir .\dist --skip-attestation --json
```

Open the project board:

```powershell
python .\hulun.py board --serve --open
```

Generate a prompt for any agent:

```powershell
python .\hulun.py prompt --conversation "Claude research" --group "Market Research"
```

Paste the output beginning with `#HULUN_ON` into that agent conversation.

## SDK And MCP

Python agents can integrate directly:

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

MCP-capable hosts can run:

```powershell
hulun-mcp --root .
```

See `docs/SDK_AND_MCP.md` for tool names, schemas, and privacy behavior.

## Task Ledger Mode

For a concrete project root:

```powershell
python .\hulun.py init --objective "Complete a long-running task" --criterion "Final result is evidence-backed"
python .\hulun.py add-step --text "Build the artifact"
python .\hulun.py record-evidence --kind test --summary "Tests passed" --command "python -m unittest discover -s tests"
python .\hulun.py scan
python .\hulun.py verify
python .\hulun.py dashboard
```

If Chrome cannot open a local `.html` path:

```powershell
python .\hulun.py serve --open
```

## Risk Bands

- 0-35 green: continue.
- 36-65 yellow: checkpoint or calibrate.
- 66-100 red: block final, recover state, or ask the user for missing evidence.

Signals:

- Evidence gap.
- Claim overhang.
- Unfinished criteria.
- Stagnation.
- Unhandled failures.
- Context decay.
- Intent drift.
- Phase disorder.
- Retry loop.
- Polish without progress.
- Cost pressure.
- Uncertainty without verification.

## OpenClaw

Install the hook:

```powershell
.\scripts\Install-OpenClawHook.ps1
openclaw hooks list --json
```

The hook should show `hulunguard` as eligible, loadable, enabled, and attached to `agent:bootstrap`.

## Project Structure

- `src/hulun_guard/`: Python package.
- `hulun.py`: no-install CLI entry.
- `tools/`: Windows wrappers.
- `scripts/verify_release_artifacts.py`: clean-environment wheel and sdist smoke test.
- `scripts/generate_release_metadata.py`: repository wrapper for release checksum and CycloneDX SBOM generation.
- `scripts/verify_github_release.py`: repository wrapper for `hulun release-verify`.
- `tests/`: end-to-end tests.
- `CODE_OF_CONDUCT.md`: public participation and moderation boundary.
- `CONTRIBUTING.md`: development and pull request standards.
- `integrations/openclaw/`: OpenClaw hook.
- `candidate_skill/`: Codex skill adapter.
- `docs/`: usage and integration docs.
- `research/`: source matrix and industrial design notes.
- `docs/ADAPTER_CONFORMANCE.md`: supported adapter contract and unsupported-field policy.
- `docs/ADAPTER_MATRIX.md`: adapter integration matrix and support tiers.
- `docs/AGENT_COMPATIBILITY.md`: mainstream agent compatibility paths and bridge boundaries.
- `docs/SERVICE_EXPORTS.md`: hosted service export commands, privacy boundary, and failure modes.
- `docs/INTEGRATION_KITS.md`: first-run onboarding kits for supported agent runtimes and trace formats.
- `docs/ONBOARDING.md`: zero-knowledge onboarding command, output contract, and safety boundary.
- `docs/THREAT_MODEL.md`: local-first security model, privacy boundaries, and threat assumptions.
- `docs/SCHEMAS.md`: public JSON schema compatibility and migration policy.
- `docs/RETENTION.md`: local retention cleanup model and safety boundary.
- `docs/REAL_WORLD_BENCHMARKS.md`: public-safe real-world benchmark suite and fixture policy.

## Validation

```powershell
python -m unittest discover -s tests
python .\hulun.py validate
python .\hulun.py calibration-drift
python .\hulun.py threat-model-check --json
python .\hulun.py compatibility --json
python .\hulun.py integration-kit --agent all --output .\.hulun\integration-kits --force --verify --json
python .\hulun.py onboard --agent all --output .\.hulun\onboarding --force --json
python .\hulun.py adapter-matrix --json
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python -m build
python scripts/generate_release_metadata.py --verify --json
python scripts/verify_release_artifacts.py
python -m hulun_guard release-verify --asset-dir dist --skip-attestation --json
python .\hulun.py --help
python .\hulun.py open --help
python .\hulun.py board --help
```
