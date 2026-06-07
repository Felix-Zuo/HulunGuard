# 糊弄 / HulunGuard

HulunGuard is a proof-first reliability guard and desktop risk meter for long-running AI agent work.

它不是“AI 文风检测器”。它监控的是智能体是否正在失去可验证的任务执行能力：目标漂移、证据不足、上下文断裂、空转总结、工具失败后继续下结论。

## What Works Now

- Desktop HulunGauge: small always-on-top progress bar, click-drag to move, double-click to close.
- Per-conversation monitors: each conversation gets its own monitor ID.
- Group/project board: active conversations are grouped and averaged into project-level risk.
- Local state ledger: `.hulun/state.json`, `.hulun/resume.md`, `.hulun/risk.json`, `.hulun/verification_report.md`.
- Universal startup prompt: `#HULUN_ON` for any agent that can run shell commands.
- OpenClaw hook: injects HulunGuard guidance into OpenClaw agent bootstrap.

## Quick Start

Open a desktop bar:

```powershell
python .\hulun.py open --conversation "Codex task" --group "Demo Project" --widget
```

Update a monitor:

```powershell
python .\hulun.py update --id M1 --score 72 --summary "Tool failed and no evidence yet" --reason "unresolved failure"
python .\hulun.py update --id M1 --delta -30 --summary "Tests passed and evidence was recorded"
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
- Unfinished criteria.
- Stagnation.
- Unhandled failures.
- Context decay.
- Intent drift.
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

## Validation

```powershell
python -m unittest discover -s tests
python .\hulun.py --help
python .\hulun.py open --help
python .\hulun.py board --help
```
