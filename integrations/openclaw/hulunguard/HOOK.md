---
name: hulunguard
description: "Inject HulunGuard monitoring reminders for long-running, evidence-sensitive agent work."
metadata: {"openclaw":{"emoji":"HG","events":["agent:bootstrap","session:compact:before","session:compact:after"]}}
---

# HulunGuard Hook

When a task is long-running, artifact-producing, research-heavy, or likely to be compressed:

1. Open a monitor:
   `python D:\0A OpenClaw\projects\展示项目\skill开发\HulunGuard\hulun.py open --conversation "<short name>" --group "<project>" --widget`
2. Track work with evidence:
   `python D:\0A OpenClaw\projects\展示项目\skill开发\HulunGuard\hulun.py record-evidence --root "<project-root>" --kind test --summary "<proof>" --command "<command>"`
3. Before final answers:
   `python D:\0A OpenClaw\projects\展示项目\skill开发\HulunGuard\hulun.py scan --root "<project-root>"`
   `python D:\0A OpenClaw\projects\展示项目\skill开发\HulunGuard\hulun.py verify --root "<project-root>"`
4. If HulunGauge is red or verify fails, do not claim completion. Recover state, add evidence, or tell the user what is missing.
