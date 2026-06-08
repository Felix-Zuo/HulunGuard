# Changelog

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
