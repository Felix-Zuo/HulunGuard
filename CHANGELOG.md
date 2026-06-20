# Changelog

## 0.23.0 - 2026-06-20

- Expanded `benchmark --suite real-world` from 12 to 16 public-safe cases with LangGraph, LangSmith, Langfuse, and Phoenix/OpenInference workflow coverage.
- Added `compatibility` and `hulun.agent_compatibility.v1` to report mainstream agent support paths across direct adapters, OpenTelemetry/OpenInference standards, and generic JSON/JSONL bridges.
- Documented mainstream agent compatibility boundaries in `docs/AGENT_COMPATIBILITY.md`.

## 0.22.0 - 2026-06-20

- Added explicit hosted-platform trace formats for `langgraph`, `langsmith`, `langfuse`, and `phoenix`.
- Extended `adapter-matrix` with hosted fixture coverage and Langfuse/Phoenix round-trip checks.
- Updated adapter support tiers so hosted fixtures are no longer described as generic best-effort only.

## 0.21.0 - 2026-06-20

- Added `adapter-matrix` as a public release gate for OpenTelemetry/OpenInference round-trips and OpenHands/SWE-agent workflow streams.
- Added `hulun.adapter_matrix.v1` reports with support tiers, public-safe fixture policy, case outcomes, checks, and gate failures.
- Documented adapter support tiers and wired the matrix into doctor, CI, Release, PR, and release-checklist workflows.

## 0.20.0 - 2026-06-20

- Added `docs/THREAT_MODEL.md` with local storage, remote behavior, adapter input, redaction, retention, threat scenario, and release-rule boundaries.
- Added `threat-model-check` and wired it into doctor, CI, Release, PR, and release-checklist workflows.
- Added a default 5 MiB trace import file-size cap with `--max-trace-bytes` and regression coverage for oversized trace rejection before persistence.

## 0.19.0 - 2026-06-20

- Added a public schema registry, migration/normalization layer, and `schema-check` compatibility gate for legacy JSON fixtures.
- Normalized legacy project state and conversation ledgers on load while preserving evidence, privacy metadata, events, checkpoints, and last risk scans.
- Documented schema compatibility in `docs/SCHEMAS.md` and added the gate to CI, Release, PR, and release-checklist workflows.

## 0.18.0 - 2026-06-20

- Added `cleanup` for dry-run and explicit-apply retention cleanup of expired project events, evidence records, conversation events, stale scans, and generated `.hulun/` reports.
- Added path-boundary protection so cleanup refuses to delete outside the project `.hulun` directory or `HULUN_HOME/conversations`.
- Documented retention cleanup in `docs/RETENTION.md` and added cleanup dry-run to CI, Release, PR, and release-checklist gates.

## 0.17.0 - 2026-06-20

- Added `benchmark --suite real-world` with 12 public-safe workflow fixtures across coding, research, ops, and artifact tasks.
- Reported scan latency, fixture size, component stability, false-positive rate, and false-negative rate separately from calibration.
- Documented real-world benchmark fixture rules in `docs/REAL_WORLD_BENCHMARKS.md` and added the gate to CI, Release, PR, and release-checklist workflows.

## 0.16.0 - 2026-06-20

- Added shared adapter conformance tests for CLI, SDK, MCP, generic, OpenTelemetry, OpenInference, OpenHands-like, and SWE-agent-like inputs.
- Preserved explicit Hulun-compatible telemetry attributes for evidence, references, action keys, result, phase, cost, latency, and token fields.
- Documented the adapter compatibility contract and unsupported fields in `docs/ADAPTER_CONFORMANCE.md`.

## 0.15.0 - 2026-06-20

- Added `calibration-drift` to compare current HulunIndex calibration against a checked-in public-safe baseline.
- Added `docs/calibration_baseline.json` as the accepted v0.14.0 calibration summary for drift review.
- Added calibration and calibration-drift gates to CI and Release workflows.

## 0.14.0 - 2026-06-20

- Expanded calibration to 100 labeled trajectories with external public-source fixtures for SWE-agent, OpenHands, OpenTelemetry GenAI, and OpenInference.
- Added calibration source, workflow, label-source, redaction-status, and source-URI coverage reporting.
- Added `docs/CALIBRATION.md` as the public calibration evidence note for release review.

## 0.13.1 - 2026-06-20

- Updated Release workflow artifact upload to `actions/upload-artifact@v6` after confirming it uses the Node 24 runtime.
- Kept release provenance generation and GitHub Release asset upload behavior unchanged.

## 0.13.0 - 2026-06-20

- Added cross-process conversation write locking to prevent concurrent runtime event loss.
- Changed conversation saves to use atomic file replacement.
- Added regression coverage for concurrent conversation event recording.

## 0.12.0 - 2026-06-20

- Expanded calibration to 80 labeled trajectories with cost-pressure and uncertainty positive cases.
- Added component support counts for every HulunIndex component.
- Added zero-support calibration gate reporting with explicit waiver support.

## 0.11.0 - 2026-06-20

- Added `calibrate` to run a 60-trajectory labeled validation dataset across healthy, unsupported-final, failure-masking, retry-loop, context-decay, and polish-without-progress cases.
- Added component-level calibration reporting with precision, recall, false-positive rate, and false-negative rate.
- Added release-gate documentation and tests for calibration reports.

## 0.10.0 - 2026-06-20

- Added a tag-triggered Release workflow that builds wheel/sdist artifacts, uploads them, and generates build provenance attestations.
- Added supply-chain documentation for provenance, branch protection, release approval gates, and release asset policy.
- Updated release checklists and PR template to include provenance and branch protection controls.

## 0.9.0 - 2026-06-20

- Added OpenTelemetry GenAI trace ingestion through `ingest --format opentelemetry`.
- Added OpenInference trace ingestion through `ingest --format openinference`.
- Added `export-otel` to write HulunGuard events as OTLP-style JSON spans.
- Added integration tests for OTel/OpenInference span mapping and default private payload withholding.
- Updated usage and maturity docs for standard telemetry interoperability.

## 0.8.0 - 2026-06-19

- Added `HulunGuardClient` as the stable Python adapter SDK for project and conversation runtime monitoring.
- Added a stdio MCP server through `hulun-mcp`, `python -m hulun_guard.mcp`, and `hulun mcp`.
- Added MCP tools for project init, observe, scan, conversation start, conversation event, and conversation scan.
- Added SDK and MCP integration tests, including live conversation pending-tool behavior.
- Documented SDK and MCP usage in `docs/SDK_AND_MCP.md`.

## 0.7.0 - 2026-06-19

- Added default privacy-safe redaction for runtime observations, conversation events, evidence records, and imported traces.
- Added `--include-sensitive` and `--retention-days` controls for trusted local debugging and explicit retention metadata.
- Changed trace ingestion to withhold raw payload fields by default and use privacy-preserving action fingerprints for retry-loop detection.
- Added regression tests for secret, email, URL-query, conversation-event, and sensitive trace import handling.

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
