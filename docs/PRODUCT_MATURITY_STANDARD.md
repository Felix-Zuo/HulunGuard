# Product Maturity Standard

HulunGuard's target is a mature local-first reliability monitor for long-running AI agents.

## Product Definition

HulunGuard is not a single skill or plugin. It is a reliability monitoring engine with multiple surfaces:

- CLI and Python package.
- Local state ledger and risk engine.
- Conversation runtime monitor.
- Desktop gauge and project board.
- Skill, hook, MCP, and trace adapters.

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
- Provenance-backed release artifacts.

### M3: Production-Ready Open Source Product

- Async/batched event ingestion.
- Enforced retention cleanup for local ledgers.
- Cross-platform UI and no hidden local assumptions.
- Integration tests for supported adapters.
- Backward-compatible schema migrations.
- Documented security model and threat model.
- User-facing onboarding that works without repository-specific knowledge.

### M4: Top-Tier Product

- Real-world benchmark suite across coding, research, ops, and artifact tasks.
- Calibrated scoring with tracked false positives and false negatives.
- Enterprise-ready adapter model.
- Open standards interoperability with GenAI tracing ecosystems.
- Release provenance, dependency review, branch protection, and Scorecard-backed security posture.

## Non-Negotiable Gates

- No final-gate relaxation without tests and a changelog entry.
- No adapter can contain a developer machine path.
- No release without CI, validation, calibration, benchmark, and security scans.
- No public claim that HulunGuard detects intent or truth; it computes reliability risk.
- No private conversation logs in the repository.

## Current Target

The current target is M2. The privacy-safe redaction baseline, adapter SDK, MCP stdio server, OpenTelemetry/OpenInference import/export baseline, release provenance baseline, 100-trajectory labeled calibration baseline, and checked-in calibration drift baseline are implemented. The next gates are stronger adapter conformance tests and broader real-world benchmark coverage without committing private logs.
