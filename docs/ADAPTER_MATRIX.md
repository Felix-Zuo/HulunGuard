# Adapter Integration Matrix

`adapter-matrix` is the release gate for supported trace and runtime adapter interoperability. It uses synthetic public-safe fixtures only; private traces, customer logs, screenshots, prompts, tool outputs, and credentials are not committed or required.

Run:

```powershell
python -m hulun_guard adapter-matrix --json
```

The JSON report uses schema `hulun.adapter_matrix.v1`.

## What It Checks

The gate verifies:

- OpenTelemetry import with Hulun-compatible attributes.
- OpenTelemetry export and OTLP re-import round-trip preservation.
- OpenInference import with Hulun-compatible attributes.
- OpenInference import to OpenTelemetry export to OTLP re-import preservation.
- OpenHands-like event streams with success, retry, recovery, summary, and finalization paths.
- SWE-agent-like trajectory streams with success, retry, recovery, summary, and finalization paths.
- Privacy redaction for secrets, emails, passwords, and URL query strings.
- Preservation of source references, evidence IDs, action keys, tokens, cost, latency, model, result, phase, and runtime event type.

## Support Tiers

| Tier | Surfaces | Meaning |
| --- | --- | --- |
| integration-tested | OpenTelemetry, OpenInference, OpenHands-like, SWE-agent-like | Public-safe fixture streams are imported through adapters and checked by `adapter-matrix`. |
| roundtrip-tested | OpenTelemetry, OpenInference | Hulun-compatible fields survive import, HulunGuard persistence, OTLP export, and OTLP re-import. |
| conformance | CLI, Python SDK, MCP, generic JSON | The shared adapter contract test verifies field preservation, redaction, and malformed payload rejection. |
| best-effort | LangGraph, LangSmith, Langfuse, Phoenix, custom JSON | Use generic JSON, OpenTelemetry, or OpenInference fields; unsupported provider-specific payloads are summarized or ignored. |

## Release Requirement

Every release must keep this command green:

```powershell
python -m hulun_guard adapter-matrix --json
```

The command is also included in `doctor --run-validation`, CI, Release, and the pull request checklist.
