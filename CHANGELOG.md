# Changelog

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
