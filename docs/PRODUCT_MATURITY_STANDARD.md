# Product Maturity Standard

HulunGuard's target is a mature local-first reliability monitor for long-running AI agents.

## Product Definition

HulunGuard is not a single skill or plugin. It is a reliability monitoring engine with multiple surfaces:

- CLI and Python package.
- Local state ledger and risk engine.
- Conversation runtime monitor.
- Desktop gauge and project board.
- Skill, hook, MCP, HTTP collector, and trace adapters.

## Maturity Levels

### M0: Prototype

- Local CLI runs.
- Synthetic validation exists.
- Manual event recording works.

### M1: Developer Preview

- Portable installation path.
- Strict validation scenarios.
- CI, security scanning, and release checklist.
- Clear public definition and limits.
- No machine-specific adapter paths.

### M2: Reliable Developer Product

- Stable event schema.
- Privacy-safe trace redaction defaults.
- Public SDK for adapters.
- MCP stdio server.
- OpenTelemetry/OpenInference import/export path.
- 100 labeled agent trajectories with source, workflow, and redaction coverage reporting.
- Precision/recall and positive-support report for major risk classes.
- Calibration drift review against a checked-in public-safe baseline.
- Adapter conformance tests for CLI, SDK, MCP, and supported trace imports.
- Adapter integration matrix for OpenTelemetry/OpenInference round-trips and OpenHands/SWE-agent workflow streams.
- Hosted-platform fixture coverage for LangGraph, LangSmith, Langfuse, and Phoenix.
- Public-safe real-world benchmark suite across coding, research, ops, and artifact workflows.
- Agent compatibility matrix for direct adapters, standards paths, and generic JSON/JSONL bridge paths.
- Verified first-run integration kits for supported agent runtimes and trace formats.
- Retention cleanup for local project and conversation ledgers.
- Backward-compatible schema migration gate for public JSON outputs.
- Documented local-first threat model with an executable release gate.
- Provenance-backed release artifacts.

### M3: Production-Ready Open Source Product

- Async/batched event ingestion.
- In-memory and stdin runtime payload ingestion for host agents that already hold spans or stream events.
- Local HTTP collector for live OTLP/HTTP JSON traces and adapter payloads.
- Managed collector flush and scan loop for long-running local monitoring.
- Offline collector operations status for service health checks.
- Prometheus collector metrics for external service monitors.
- Prometheus alert-rule generation for collector health and HulunIndex risk signals.
- Cross-platform service templates for managed collector operation.
- Cross-platform service lifecycle controls for install, start, stop, restart, status, and uninstall review.
- Cross-platform UI and no hidden local assumptions.
- Native service export connectors beyond public-safe hosted fixture shapes.
- User-facing onboarding that works without repository-specific knowledge.
- One-command onboarding that verifies supported agent paths before real traces are imported.
- Trace diagnostics that identify format, importability, privacy mode, and next command before real traces are written.

### M4: Top-Tier Product

- Larger real-world benchmark coverage across more adapters and workflow variants.
- Calibrated scoring with tracked false positives and false negatives.
- Enterprise-ready adapter model.
- Open standards interoperability with GenAI tracing ecosystems.
- Release provenance, dependency review, branch protection, and Scorecard-backed security posture.

## Non-Negotiable Gates

- No final-gate relaxation without tests and a changelog entry.
- No adapter can contain a developer machine path.
- No release without CI, validation, calibration, calibration drift, threat model check, agent compatibility, integration kit verification, onboarding verification, adapter matrix, schema compatibility, retention cleanup dry-run, scan benchmark, real-world benchmark, and security scans.
- No public claim that HulunGuard detects intent or truth; it computes reliability risk.
- No private conversation logs in the repository.

## Current Target

The current target is M3 hardening. The privacy-safe redaction baseline, adapter SDK, MCP stdio server, local HTTP collector baseline, managed collector flush/scan baseline, collector operations status baseline, collector Prometheus metrics baseline, collector Prometheus alert-rule baseline, cross-platform collector service-template baseline, collector service-lifecycle baseline, OpenTelemetry/OpenInference import/export baseline, hosted-platform fixture baseline, OpenAI Agents SDK native trace adapter baseline, durable async/batched ingestion baseline, in-memory/stdin runtime payload baseline, release provenance baseline, installed release-verification baseline, 100-trajectory labeled calibration baseline, checked-in calibration drift baseline, adapter conformance baseline, adapter integration matrix baseline, expanded public-safe real-world benchmark baseline, agent compatibility matrix baseline, verified integration kit baseline, zero-knowledge onboarding baseline, trace-doctor diagnostic baseline, retention cleanup baseline, schema compatibility baseline, and threat-model baseline are implemented. The next gate is graceful shutdown/restart integration and richer collector health metrics beyond Prometheus basics.
