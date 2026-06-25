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
- Langfuse OTEL import to HulunGuard persistence to OTLP re-import preservation.
- Phoenix/OpenInference import to HulunGuard persistence to OTLP re-import preservation.
- OpenHands-like event streams with success, retry, recovery, summary, and finalization paths.
- SWE-agent-like trajectory streams with success, retry, recovery, summary, and finalization paths.
- LangGraph stream parts with success, retry, recovery, summary, and finalization paths.
- LangSmith run exports with success, retry, recovery, summary, and finalization paths.
- LangSmith service export through a mocked HTTP transport with explicit auth, selected fields, pagination, redaction, and importability.
- Langfuse Observations API v2 service export through a mocked HTTP transport with Basic Auth, bounded time windows, selected field groups, pagination, redaction, and generic importability.
- OpenAI Agents SDK trace/span exports with success, retry, recovery, summary, and finalization paths.
- Privacy redaction for secrets, emails, passwords, and URL query strings.
- Preservation of source references, evidence IDs, action keys, tokens, cost, latency, model, result, phase, and runtime event type.

## Support Tiers

| Tier | Surfaces | Meaning |
| --- | --- | --- |
| integration-tested | OpenTelemetry, OpenInference, OpenHands-like, SWE-agent-like, OpenAI Agents SDK | Public-safe fixture streams are imported through adapters and checked by `adapter-matrix`. |
| hosted-fixture-tested | LangGraph, LangSmith file exports, Langfuse, Phoenix | Hosted platform fixture shapes are checked with synthetic public-safe exports and no private service trace data. |
| native-export-tested | LangSmith service export, Langfuse service export | Mocked service HTTP export checks explicit auth, selected fields, bounded windows, pagination, redaction, and importability without real credentials. |
| roundtrip-tested | OpenTelemetry, OpenInference, Langfuse, Phoenix | Hulun-compatible fields survive import, HulunGuard persistence, OTLP export, and OTLP re-import. |
| conformance | CLI, Python SDK, MCP, stdin payloads, in-memory payloads, generic JSON | The shared adapter contract test verifies field preservation, redaction, and malformed payload rejection. |
| best-effort | Custom JSON or provider-specific exports without supported fields | Use generic JSON, OpenTelemetry, or OpenInference fields; unsupported provider-specific payloads are summarized or ignored. |

## Release Requirement

Every release must keep this command green:

```powershell
python -m hulun_guard adapter-matrix --json
```

The command is also included in `doctor --run-validation`, CI, Release, and the pull request checklist.

## Source Alignment

- LangGraph stream parts: `https://docs.langchain.com/oss/python/langgraph/streaming`
- LangSmith trace and run model: `https://docs.langchain.com/langsmith/observability-concepts`
- LangSmith run query API: `https://docs.langchain.com/langsmith/smith-api/runs/query-runs-v2`
- Langfuse OTEL ingestion: `https://langfuse.com/integrations/native/opentelemetry`
- Langfuse Observations API: `https://langfuse.com/docs/api-and-data-platform/features/observations-api`
- OpenInference/Phoenix semantic conventions: `https://arize-ai.github.io/openinference/spec/semantic_conventions.html`
- OpenAI Agents SDK tracing: `https://openai.github.io/openai-agents-python/tracing/`
