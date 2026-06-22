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
- Python SDK and MCP server: agents can record runtime state directly without shell glue.
- Built-in validation suite: run synthetic healthy/slop-risk scenarios before release.
- Product operations: `onboard`, `quickstart`, `doctor`, `compatibility`, `integration-kit`, `adapter-matrix`, `schema-check`, `cleanup`, and `benchmark` commands for onboarding, diagnostics, agent compatibility, first-run integration packages, adapter integration, schema compatibility, retention cleanup, scan performance, and public-safe real-world workflow checks.
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
python .\hulun.py ingest --file .\trace.jsonl --format generic --scan
python .\hulun.py ingest --file .\otel-trace.json --format opentelemetry --scan
python .\hulun.py ingest --file .\openinference-trace.json --format openinference --scan
python .\hulun.py ingest --file .\openhands-events.json --format openhands --scan
python .\hulun.py ingest --file .\run.traj --format swe-agent --scan
python .\hulun.py ingest --file .\langgraph-stream.json --format langgraph --scan
python .\hulun.py ingest --file .\langsmith-runs.json --format langsmith --scan
python .\hulun.py ingest --file .\langfuse-otel.json --format langfuse --scan
python .\hulun.py ingest --file .\phoenix-openinference.json --format phoenix --scan
python .\hulun.py export-otel --output .\hulun-otel.json
```

For an empty project, add `--init-if-missing` to create the minimal local ledger before import.

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

The security boundary and threat assumptions are documented in `docs/THREAT_MODEL.md`.

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
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python -m pytest -q
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
- `tests/`: end-to-end tests.
- `integrations/openclaw/`: OpenClaw hook.
- `candidate_skill/`: Codex skill adapter.
- `docs/`: usage and integration docs.
- `research/`: source matrix and industrial design notes.
- `docs/ADAPTER_CONFORMANCE.md`: supported adapter contract and unsupported-field policy.
- `docs/ADAPTER_MATRIX.md`: adapter integration matrix and support tiers.
- `docs/AGENT_COMPATIBILITY.md`: mainstream agent compatibility paths and bridge boundaries.
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
python .\hulun.py --help
python .\hulun.py open --help
python .\hulun.py board --help
```
