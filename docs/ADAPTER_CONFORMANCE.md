# Adapter Conformance

HulunGuard adapters must preserve the same runtime semantics whether an agent writes through the CLI, Python SDK, MCP server, or a supported trace import format.

## Contract Fields

Every supported adapter should preserve these fields when the source provides them:

| Field | Meaning |
| --- | --- |
| `type` | Runtime event type such as `tool_result`, `llm_call`, `command`, `source`, or `final_attempt`. |
| `phase` | One of `explore`, `plan`, `implement`, `verify`, `recover`, `summarize`, `final`, or `orchestrate`. |
| `result` | `pass`, `fail`, or `unknown`. |
| `summary` | Short privacy-safe event summary. |
| `evidence` | Evidence IDs already known to the project ledger. |
| `refs` | Paths, URLs, trace IDs, span IDs, or command references. |
| `action_key` | Stable retry-loop key. |
| `prompt_tokens` | Prompt/input token count. |
| `completion_tokens` | Completion/output token count. |
| `cost` | Numeric model or tool cost. |
| `latency_ms` | Latency in milliseconds. |
| `model` | Model name. |

Stored events must also include `privacy.mode` and `privacy.retention_days`.

## Supported Surfaces

The adapter conformance test covers:

- CLI `observe`
- Python `HulunGuardClient.observe`
- MCP `hulun_observe`
- CLI `batch enqueue` plus `batch flush`
- Python `HulunGuardClient.enqueue` plus `flush_queue`
- MCP `hulun_batch_enqueue` plus `hulun_batch_flush`
- CLI `batch ingest-stdin` plus `batch flush`
- Python `HulunGuardClient.enqueue_payload` plus `flush_queue`
- MCP `hulun_batch_ingest_payload` plus `hulun_batch_flush`
- `ingest --format generic`
- HTTP collector `/ingest/generic`
- HTTP collector `/v1/traces`
- Managed HTTP collector flush plus scan
- `ingest --format opentelemetry`
- `ingest --format openinference`
- `ingest --format openhands`
- `ingest --format swe-agent`
- `ingest --format langgraph`
- `ingest --format langsmith`
- `ingest --format langfuse`
- `ingest --format phoenix`
- `ingest --format openai-agents`

Each surface must be able to record the contract event, redact sensitive payloads by default, write `.hulun/risk.json` when scan is requested, and reject malformed SDK/MCP payloads without silently persisting a bad event. Batched surfaces must also preserve contract fields after queue flush and must not let malformed queued records block valid records.

Trace-file adapters must reject files above the configured `--max-trace-bytes` limit before parsing or persisting events. The default limit is 5 MiB.

Runtime payload adapters must reject JSON-serialized payloads above the configured `--max-payload-bytes` limit before queueing events. The default limit is 5 MiB. Queue metadata stores a source name and payload fingerprint, not the raw host path or raw private payload.

HTTP collector adapters must use JSON or JSONL, must queue through the same durable batch path, must reject oversized payloads before queueing, and must refuse non-loopback binds unless explicitly started with `--allow-remote --token`. Managed collector mode must preserve the same fields after automatic flush and scan.

Integration coverage is defined in `docs/ADAPTER_MATRIX.md`. The conformance test proves each adapter can write the shared contract; `adapter-matrix` proves supported trace families survive realistic import, export, redaction, and workflow-path checks.

## Support Tiers

| Tier | Surfaces | Gate |
| --- | --- | --- |
| integration-tested | OpenTelemetry, OpenInference, OpenHands-like, SWE-agent-like, OpenAI Agents SDK | `python -m hulun_guard adapter-matrix --json` |
| collector-smoke-tested | OTLP/HTTP JSON, generic HTTP adapter payload path, managed flush/scan, Prometheus metrics | `python -m hulun_guard collector smoke --json`, `python -m hulun_guard collector smoke --managed --scan --init-if-missing --json`, and `python -m hulun_guard collector metrics --require-status-file` |
| hosted-fixture-tested | LangGraph, LangSmith, Langfuse, Phoenix | Synthetic public-safe hosted platform fixture shapes |
| roundtrip-tested | OpenTelemetry, OpenInference, Langfuse, Phoenix | Import to persisted events to OTLP export to OTLP re-import |
| conformance | CLI, Python SDK, MCP, generic JSON | `tests/test_adapter_conformance.py` |
| best-effort | Custom JSON or provider-specific exports without supported fields | Generic JSON, OpenTelemetry, or OpenInference field mapping |

## Telemetry Compatibility Fields

OpenTelemetry and OpenInference imports recognize these Hulun-compatible attributes:

| Attribute | Maps to |
| --- | --- |
| `hulun.event.type` or `hulun.type` | `type` |
| `hulun.event.summary` or `hulun.summary` | `summary` |
| `hulun.event.result` or `hulun.result` | `result` |
| `hulun.event.phase` or `hulun.phase` | `phase` |
| `hulun.evidence.ids`, `hulun.event.evidence`, or `hulun.evidence` | `evidence` |
| `hulun.refs`, `hulun.event.refs`, or `hulun.ref` | `refs` |
| `hulun.action_key` or `hulun.event.action_key` | `action_key` |
| `hulun.claims` or `hulun.event.claims` | `claims` |
| `hulun.cost` | `cost` |
| `hulun.latency_ms` | `latency_ms` |

Generic GenAI fields such as `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`, `llm.token_count.prompt`, `llm.token_count.completion`, and `llm.model_name` are also mapped when present.

## OpenAI Agents SDK Fields

OpenAI Agents SDK imports recognize exported `trace.span` payloads with these fields:

| Field | Maps to |
| --- | --- |
| `span_data.type` | runtime event type inference |
| `span_data.name` or `span_data.data.sdk_span_type` | summary and phase inference |
| `span_data.model` | `model` |
| `span_data.usage.input_tokens` | `prompt_tokens` |
| `span_data.usage.output_tokens` | `completion_tokens` |
| `started_at` and `ended_at` | `latency_ms` |
| `error` | failed result and recovery signal |
| `id` and `trace_id` | refs and fallback action key |
| `metadata.hulun.*` | explicit HulunGuard event fields when provided |

## Privacy Contract

Default adapter writes redact known secrets, emails, private home paths, URL query strings, summaries, claims, references, action keys, and model names before persistence. Raw trace fields such as prompts, completions, outputs, tool arguments, and tool results are withheld unless `--include-sensitive` or SDK/MCP sensitive mode is explicitly enabled.

Use sensitive mode only for trusted local debugging with a short retention period.

## Unsupported Fields

HulunGuard currently does not guarantee semantic preservation for:

- Full prompt/completion/tool payload text in default mode.
- Nested multimodal payloads, binary blobs, screenshots, files, or attachments.
- Provider-specific span fields that do not map to the contract fields above.
- Cross-run trace parent/child topology beyond stored trace/span references.
- External evidence objects that have not already been recorded or imported as HulunGuard evidence IDs.

Unsupported fields should be either redacted, summarized, fingerprinted, or ignored rather than persisted as raw private content.
