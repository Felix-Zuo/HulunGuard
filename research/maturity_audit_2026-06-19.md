# HulunGuard Maturity Audit

Date: 2026-06-19

## External Baselines

- OpenSSF Scorecard evaluates open source security posture with automated checks and a 0-10 score. HulunGuard should run Scorecard in GitHub Actions and use the result as an improvement signal, not as an absolute guarantee.
- SLSA defines controls for preventing tampering and improving artifact integrity. HulunGuard should move toward provenance-backed releases once packaging is stable.
- PyPA recommends `pyproject.toml` as the central build and metadata file. HulunGuard should keep package metadata, project URLs, optional dev dependencies, and tool config there.
- OpenTelemetry GenAI semantic conventions are moving into a GenAI-specific repository for spans, metrics, and events. HulunGuard should align future trace adapters with this ecosystem rather than inventing a closed telemetry schema.
- Langfuse, Phoenix, and LangSmith show the product bar for agent observability: traces, sessions, tool calls, cost/latency, evaluation, dashboards, and alerting.

Sources:

- https://github.com/ossf/scorecard
- https://github.com/ossf/scorecard-action
- https://slsa.dev/
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- https://github.com/open-telemetry/semantic-conventions-genai
- https://langfuse.com/docs/observability/overview
- https://github.com/arize-ai/phoenix
- https://www.langchain.com/langsmith/observability

## Current Findings

### Strengths

- CLI core is runnable.
- Synthetic validation exists.
- Conversation runtime monitoring exists.
- Local-first storage reduces SaaS dependency.
- Trace ingestion exists for generic, OpenHands-like, and SWE-agent-like files.

### Blocking Gaps

- Validation previously allowed a yellow expected scenario to pass as red, which weakened calibration evidence.
- Conversation runtime final-gate scoring was too lenient for unsupported final claims with pending tools or unresolved failures.
- OpenClaw integration contained a machine-specific path.
- CI, security scanning, issue templates, release policy, and contribution standards were missing.
- No labeled real trajectory dataset exists yet.
- No standard OpenTelemetry/OpenInference adapter exists yet.

## First Remediation Slice

- Make validation exact.
- Strengthen conversation final-gate scoring.
- Remove machine-specific OpenClaw paths.
- Add CI/security workflows.
- Add project governance docs.
- Create GitHub issues for the remaining maturity track.

## Second Remediation Slice

- Add default redaction for observations, conversation events, evidence records, and trace imports.
- Withhold raw trace payload fields by default while preserving scoring structure and action fingerprints.
- Add explicit `--include-sensitive` and `--retention-days` controls for trusted local debugging.
- Cover privacy behavior with tests for secrets, emails, URL query strings, conversation runtime events, and trace import modes.

## Product Position

HulunGuard is currently moving from developer preview toward a reliable developer product. It should not be marketed as production-ready until M2 gates are met with real trajectory data, adapter coverage, telemetry interoperability, and release provenance.
