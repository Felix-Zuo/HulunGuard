---
name: anti-slop-longrun
description: Use HulunGuard to prevent long-running agent tasks from drifting after context compaction by maintaining a durable objective, success criteria, task ledger, evidence log, HulunGauge risk scan, checkpoints, resume packet, and final verification gate. Use for multi-turn, high-stakes, research-heavy, coding, debugging, packaging, deployment, or artifact-producing work where losing context could cause false completion, vague claims, duplicated work, or unverifiable results.
---

# Anti Slop Longrun

## Core Rule

Never let chat history be the only source of truth for a long task. Maintain a `.hulun/` run ledger in the active project and verify it before claiming completion.

## Start A Run

From the HulunGuard project root, run:

```bash
python hulun.py init --root <project-root> --objective "<goal>" --criterion "<observable success condition>"
```

Add one criterion for each user-visible definition of done. Prefer criteria that can be proven by a file path, command output, screenshot, URL, test result, or source link.

## During Work

Record progress as externally auditable state:

```bash
python hulun.py add-step --root <project-root> --text "<work item>"
python hulun.py record-evidence --root <project-root> --kind test --summary "<what was proven>" --command "<command run>"
python hulun.py set-step --root <project-root> --id S1 --status done --evidence E1
python hulun.py set-criterion --root <project-root> --id C1 --status done --evidence E1
```

Use evidence for commands, tests, source links, files, screenshots, packages, user approvals, blockers, and rejected assumptions.

## HulunGauge

Scan the current drift/slop risk before major claims:

```bash
python hulun.py scan --root <project-root>
python hulun.py dashboard --root <project-root>
```

Risk bands:

- `0-35`: continue.
- `36-65`: checkpoint or calibrate.
- `66-100`: block final; recover state before continuing.

## Before Compaction Or Resuming

Write and read a checkpoint:

```bash
python hulun.py checkpoint --root <project-root> --summary "<state>" --next-action "<next action>"
python hulun.py resume --root <project-root>
```

On resume, read `.hulun/resume.md` and the referenced evidence before continuing.

## Final Gate

Before final response, run:

```bash
python hulun.py verify --root <project-root>
```

Do not claim the task is complete if verification fails or HulunGauge blocks the final attempt. Report the failed criteria, missing evidence, risk reasons, or pending steps and continue working if possible.

## References

- Read `references/architecture.md` when designing a robust long-running agent system or explaining tradeoffs.
- Read `references/state_schema.md` before changing the ledger format or integrating the skill into another runtime.
