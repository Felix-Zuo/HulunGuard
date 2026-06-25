# Changelog

## 0.46.0 - 2026-06-25

- Added locked `uv` dependency synchronization for CI, Security, and Release workflows, removing unpinned `pip install` workflow commands.
- Pinned all GitHub Actions by immutable commit SHA and moved write permissions from workflow scope to the narrow jobs that need them.
- Added open source governance documentation for Scorecard owner actions, branch protection, security policy visibility, and remaining non-code maturity signals.

## 0.45.0 - 2026-06-25

- Added defensive storage-boundary redaction before writing HulunGuard state, resume, risk, and JSON output artifacts.
- Reworked sensitive redaction fixtures to preserve API key, password, email, and query-token coverage without triggering CodeQL clear-text storage alerts.
- Added a regression test proving unmarked sensitive payloads are scrubbed before `.hulun/state.json` is written.

## 0.44.0 - 2026-06-25

- Added Phoenix CLI trace export hardening for `traceId`, `spans[]`, span `context`, `span_kind`, `status_code`, and `start_time` / `end_time` payloads.
- Added content-based `--format auto` detection for Phoenix CLI exports without relying on filename hints, plus adapter conformance and `adapter-matrix` coverage.
- Extended installed-wheel release smoke checks to verify Phoenix CLI export `trace-doctor` and `ingest --format auto` behavior without real credentials or private traces.

## 0.43.0 - 2026-06-25

- Added `service-export langfuse` for explicitly configured Langfuse Observations API v2 exports with Basic Auth, bounded time windows, selected field groups, pagination controls, redacted output, and next-step commands.
- Added Langfuse service export schema fixture coverage, auto trace-doctor detection for Langfuse service-export wrappers, agent compatibility metadata, and a native-export-tested adapter-matrix case.
- Extended installed-wheel release smoke checks to verify the Langfuse service export contract against a local mock HTTP server without real credentials.

## 0.42.0 - 2026-06-25

- Added `service-export langsmith` for explicitly configured LangSmith run-query exports with selected fields, pagination controls, redacted output, and next-step commands.
- Added `hulun.service_export.v1`, service export schema fixtures, trace-doctor/import support for `runs` and `items` wrappers, and a native-export-tested adapter-matrix case.
- Extended installed-wheel release smoke checks to verify the LangSmith service export contract against a local mock HTTP server without real credentials.

## 0.41.0 - 2026-06-25

- Added grouped collector health diagnostics to `collector status --json` and embedded metrics status output.
- Added operator action hints for queue backlog, stale status, runtime lifecycle, dead letters, managed flush, and latest HulunIndex risk without exposing local paths in diagnostics.
- Extended collector tests, release gates, installed-wheel smoke checks, docs, and schema fixture coverage for diagnostic status scenarios.

## 0.40.0 - 2026-06-25

- Added `collector shutdown-check` to verify graceful collector shutdown records a stopped runtime state and final status file.
- Added collector runtime lifecycle state, stop reason, stop timestamps, and uptime to status output and Prometheus metrics.
- Extended collector tests, CI, release gates, installed-wheel smoke checks, docs, and schema fixture coverage for graceful shutdown verification.

## 0.39.0 - 2026-06-25

- Added `collector service-lifecycle` to generate reviewed cross-platform lifecycle controls for managed collector operation.
- Added systemd, launchd, and Windows Scheduled Task install/start/stop/restart/status/uninstall scripts while preserving the default write-only safety boundary.
- Extended collector tests, CI, release gates, installed-wheel smoke checks, docs, and schema fixture coverage for service lifecycle generation.

## 0.38.0 - 2026-06-25

- Added `collector alert-rules` to generate reviewed Prometheus alerting rule files for collector health and HulunIndex risk signals.
- Added overwrite safety, configurable queue/staleness/risk thresholds, and generated deployment notes for alert-rule output.
- Extended collector tests, CI, release gates, installed-wheel smoke checks, docs, and schema fixture coverage for alert-rule generation.

## 0.37.0 - 2026-06-25

- Added Prometheus metrics export through `collector metrics` and `GET /metrics`.
- Reused collector operations status semantics for metrics so queue, dead-letter, stale status, runtime error, and risk signals share one health gate.
- Extended collector tests, CI, release gates, installed-wheel smoke checks, docs, and schema fixture coverage for external observability.

## 0.36.0 - 2026-06-25

- Added `collector status` for offline collector operations health across queue, status file, runtime error, and last-risk signals.
- Added `collector service-template` to generate systemd, launchd, and Windows Scheduled Task templates for long-running managed collector operation.
- Extended collector tests, CI, release gates, and installed-wheel smoke checks for collector operations paths.

## 0.35.0 - 2026-06-25

- Added managed collector flush mode so `collector serve` can periodically flush queued live observations and optionally recompute HulunIndex.
- Added `collector smoke --managed --scan --init-if-missing`, managed runtime status, and `.hulun/collector_status.json`.
- Extended collector tests, release gates, and documentation for long-running live-monitor operation.

## 0.34.0 - 2026-06-25

- Added `collector serve`, a loopback-first local HTTP collector for live OTLP/HTTP JSON traces and adapter runtime payloads.
- Added `collector smoke --json`, `hulun.collector.v1`, schema fixture coverage, CI/Release gates, and clean-environment artifact smoke coverage.
- Added collector safety controls for payload size caps, JSON-only ingestion, optional token auth, and non-loopback bind refusal unless explicitly enabled with a token.

## 0.33.0 - 2026-06-25

- Added in-memory runtime payload ingestion through adapter APIs, SDK `enqueue_payload`, and MCP `hulun_batch_ingest_payload`.
- Added `batch ingest-stdin` so agents and host processes can pipe JSON/JSONL trace events directly into the durable queue.
- Extended adapter conformance and release artifact smoke coverage for payload/stdin ingestion paths.

## 0.32.0 - 2026-06-24

- Added durable batched runtime ingestion with `batch enqueue`, `batch ingest-file`, `batch status`, and `batch flush`.
- Added SDK queue methods for high-frequency agent emitters and bounded batch flushes.
- Added `hulun.batch_ingest.v1` reports, schema fixture coverage, dead-letter handling, CI smoke coverage, and release policy updates.

## 0.31.0 - 2026-06-24

- Added the `openai-agents` trace adapter for OpenAI Agents SDK trace/span export payloads.
- Promoted OpenAI Agents SDK from generic bridge support to an integration-tested direct adapter in compatibility, trace doctor, onboarding, and integration kits.
- Added OpenAI Agents SDK coverage to `adapter-matrix` and documented the native field mapping and release gate.

## 0.30.0 - 2026-06-23

- Added `trace-doctor` for safe pre-import trace diagnostics across supported agent formats.
- Added `hulun.trace_doctor.v1` to the public schema compatibility gate and release validation surface.
- Added CI and Release workflow coverage for trace diagnostics before schema compatibility checks.

## 0.29.0 - 2026-06-23

- Promoted release verification to the installed `hulun release-verify` CLI.
- Moved release metadata and release verification logic into package modules shared by CLI commands and repository scripts.
- Added `hulun.github_release_verification.v1` to the public schema compatibility gate and clean-environment artifact smoke test.

## 0.28.0 - 2026-06-23

- Added a one-command GitHub release verifier for checksums, SBOM artifact hashes, and GitHub attestations.
- Added offline release-verifier coverage to CI and Release workflows.
- Added tests for release verifier success, tamper detection, and missing-asset failure paths.

## 0.27.0 - 2026-06-23

- Added release metadata generation for `SHA256SUMS` and CycloneDX 1.6 SBOM assets.
- Added release metadata verification to CI and Release workflows before asset upload.
- Documented checksum, SBOM, and GitHub artifact attestation verification for release consumers.

## 0.26.0 - 2026-06-23

- Added a clean-environment release artifact smoke test for built wheel and sdist files.
- Verified installed `hulun` commands, packaged schema fixtures, packaged threat-model docs, compatibility output, and first-run onboarding outside the source checkout.
- Added the artifact smoke test to CI and Release workflows before publishing assets.

## 0.25.1 - 2026-06-23

- Added `CODE_OF_CONDUCT.md` and GitHub issue-template configuration for a complete open-source community profile.
- Added bug report, adapter gap, feature request, and generic issue-template paths with explicit private-data boundaries.
- Updated contributor guidance to point maintainers at the full release gate.

## 0.25.0 - 2026-06-23

- Added `onboard` for zero-knowledge first-run agent onboarding across supported runtimes.
- Added `hulun.onboarding.v1` reports with generated kit locations, sample verification, sandbox import results, and next-step commands.
- Added onboarding verification to `doctor --run-validation`, CI, Release, and the PR checklist.
- Documented onboarding as the preferred first command for mainstream agent setup.

## 0.24.0 - 2026-06-20

- Added `integration-kit` for verified first-run onboarding packages across supported agent runtimes and trace formats.
- Added `hulun.integration_kit.v1` manifests with generated files, ingest command, sample trace path, and verification outcome.
- Added `ingest --init-if-missing` so generated kits can import into an empty project without a separate setup step.
- Wired integration kit verification into `doctor --run-validation`, CI, Release, PR checklist, release policy, schema docs, and security docs.
- Moved package maturity classifier from Alpha to Beta.

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
