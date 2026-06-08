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

## Import External Agent Traces

Use `ingest` to convert trace files into HulunGuard observations:

```powershell
python .\hulun.py ingest --file .\trace.jsonl --format generic --scan
python .\hulun.py ingest --file .\openhands-events.json --format openhands --scan
python .\hulun.py ingest --file .\run.traj --format swe-agent --scan
```

Supported formats:

- `generic`: JSON or JSONL with fields like `type`, `summary`, `result`, `phase`, `claim`, `evidence`, `action_key`, `prompt_tokens`, `completion_tokens`, `cost`, and `latency_ms`.
- `openhands`: maps action/observation/error/condensation-like events into command, tool_result, agent_error, and summary observations.
- `swe-agent`: maps action/observation trajectory steps into command/tool_result observations with retry-loop fingerprints.
- `auto`: guesses from the filename.

## Run Release Validation

Before publishing a new version:

```powershell
python .\hulun.py validate
python -m pytest -q
```

`validate` writes `.hulun/validation_report.md` and `.hulun/validation_report.json`.

## Benchmark Scan Performance

Use `benchmark` before releases or after scoring changes:

```powershell
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --events 50000 --max-ms 1000
```

`benchmark` writes `.hulun/benchmark_report.json` and returns exit code `2` if `--max-ms` is exceeded.

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
