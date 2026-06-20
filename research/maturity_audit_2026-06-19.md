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

## Third Remediation Slice

- Add `HulunGuardClient` as the stable Python adapter SDK.
- Add a stdio MCP server with tool discovery and tool call support.
- Expose project init/observe/scan and conversation start/event/scan over MCP.
- Cover SDK and MCP behavior with tests, including live conversation pending-tool risk.

## Fourth Remediation Slice

- Add OpenTelemetry GenAI span ingestion for OTLP-style JSON and JSONL.
- Add OpenInference span ingestion for LLM and tool spans.
- Add OTLP-style export for HulunGuard event ledgers.
- Preserve privacy defaults by withholding prompt, output, and tool argument payloads unless sensitive mode is explicitly enabled.

## Fifth Remediation Slice

- Add a tag-triggered Release workflow that builds release artifacts from the tagged commit.
- Generate GitHub build provenance attestations for wheel and sdist artifacts.
- Document branch protection, release approval, and release asset controls.

## Sixth Remediation Slice

- Add a 60-item labeled trajectory calibration dataset covering healthy, unsupported-final, failure-masking, retry-loop, context-decay, and polish-without-progress cases.
- Add `hulun calibrate` with precision, recall, false-positive rate, false-negative rate, and mismatch reporting for HulunIndex components.
- Add calibration to the release gate so scoring changes must preserve measured component behavior.

## Seventh Remediation Slice

- Expand calibration to 80 labeled trajectories by adding cost-pressure and uncertainty positive cases.
- Add component support counts for every HulunIndex component.
- Fail calibration when a required component has zero expected-positive support unless the report declares an explicit waiver.

## Eighth Remediation Slice

- Add cross-process conversation write locking for runtime event writes, scans, and close operations.
- Change conversation saves to use atomic file replacement instead of direct overwrite.
- Add concurrent CLI process regression coverage so parallel agent or adapter writes keep every event with unique IDs.

## Ninth Remediation Slice

- Expand calibration to 100 labeled trajectories.
- Add public-source-derived fixture coverage for SWE-agent trajectory shape, OpenHands event logs, OpenTelemetry GenAI spans, and OpenInference traces.
- Report source class, workflow class, label source, redaction status, and source URI in calibration JSON and Markdown.
- Keep external fixtures schema-derived and public-safe; do not commit private conversation logs.

## Tenth Remediation Slice

- Add a checked-in public-safe calibration baseline summary derived from the accepted v0.14.0 calibration gate.
- Add `calibration-drift` to compare current calibration against baseline dataset size, label coverage, source coverage, workflow coverage, redaction coverage, source URI coverage, component support, precision, and recall.
- Fail unexplained calibration regressions while allowing an explicit `--rationale` path for reviewed intentional changes.
- Add calibration and calibration-drift gates to CI and Release workflows.

## Eleventh Remediation Slice

- Add shared adapter conformance coverage for CLI, Python SDK, MCP, generic trace import, OpenTelemetry, OpenInference, OpenHands-like traces, and SWE-agent-like trajectories.
- Preserve explicit Hulun-compatible telemetry attributes for event type, phase, result, summary, evidence, refs, action key, claims, cost, latency, and model pressure fields.
- Preserve explicit OpenHands/SWE-agent phase, result, and action key fields before falling back to inference.
- Add negative coverage for malformed SDK/MCP payloads and default raw sensitive payload retention.
- Document supported adapter contract fields and unsupported fields in `docs/ADAPTER_CONFORMANCE.md`.

## Product Position

HulunGuard is currently moving from developer preview toward a reliable developer product. The M2 calibration baseline now includes external public-source coverage, drift review, and adapter conformance coverage. It should not be marketed as production-ready until broader real-world benchmark coverage is in place without committing private logs.
