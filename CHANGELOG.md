# Changelog

## 0.6.2 - 2026-06-19

- Applied Dependabot workflow updates for checkout and Scorecard actions.

## 0.6.1 - 2026-06-19

- Fixed OpenSSF Scorecard workflow permissions so publishing results does not use global write permissions.
- Updated GitHub Actions workflows to Node 24-compatible action majors.

## 0.6.0 - 2026-06-19

- Added professional maturity, security, and release governance assets.
- Added GitHub CI, CodeQL/Bandit security scanning, Scorecard, Dependabot, and issue templates.
- Strengthened conversation final-gate scoring for unsupported final claims, pending tools, and unresolved failures.
- Changed validation to require exact expected risk bands instead of counting yellow scenarios as passed when red.
- Changed OpenClaw hook guidance to use portable installed commands instead of machine-specific absolute paths.
- Expanded package metadata, project URLs, dev dependencies, and Ruff configuration.

## 0.5.1 - 2026-06-13

- Verified the unittest suite after moving the local repository under the showcase project directory.
- Kept the public README focused on proof-first agent reliability rather than private workflow details.

## 0.5.0 - 2026-06-08

- Added a polished GitHub Pages showcase at `docs/index.html`.
- Added a Chinese showcase page at `docs/zh.html`.
- Added a product runtime visual asset for the showcase hero.

## 0.4.0 - 2026-06-08

- Added `hulun conversation start/event/scan/status/close` for live conversation runtime monitoring.
- Added per-conversation state under `HULUN_HOME/conversations`.
- Added conversation-specific risk components: user challenge, pending tools, unresolved failures, unsupported claims, stagnation, context decay, and cost pressure.
- Added monitor sync for conversation runtime monitors so desktop widgets track conversation risk instead of project ledger risk.
- Added tests for user challenge, pending tool calls, and resolved tool results.

## 0.3.0 - 2026-06-08

- Added `quickstart` for copy-paste onboarding.
- Added `doctor` for local project diagnostics.
- Added `benchmark` for scan performance checks.
- Changed bulk event ID allocation to use state counters instead of repeated full-list scans.
- Changed JSONL/NDJSON ingestion to stream records instead of loading the whole file first.
- Changed `ingest --json` to omit imported event bodies by default; use `--include-events` when needed.
- Added tests for usability commands, streamed ingestion, and benchmark reports.

## 0.2.0 - 2026-06-08

- Added `observe` for realtime HulunIndex observations.
- Added `ingest` for generic, OpenHands-like, and SWE-agent-like trace files.
- Added `validate` with built-in healthy and slop-risk scenarios.
- Added HulunIndex research notes and product validation notes.

## 0.1.0 - 2026-06-08

- Initial local-first CLI, HulunGauge dashboard, desktop monitor, project board, OpenClaw hook, and candidate skill adapter.
