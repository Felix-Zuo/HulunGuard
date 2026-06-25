# Agent Compatibility

HulunGuard is designed for agent frameworks that can expose runtime events, traces, spans, or JSON logs. Compatibility is grouped by the strongest supported path.

Run the local matrix:

```powershell
python -m hulun_guard compatibility
python -m hulun_guard compatibility --json
```

The JSON report uses schema `hulun.agent_compatibility.v1`.

Generate a runnable first-run kit for any listed agent id:

```powershell
python -m hulun_guard onboard --agent langgraph
python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
python -m hulun_guard integration-kit --agent langgraph --verify
python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify
```

## Direct Adapters

These surfaces have explicit ingest formats and fixture coverage:

| Agent or platform | Format | Gate |
| --- | --- | --- |
| OpenHands | `openhands` | adapter matrix, real-world benchmark |
| SWE-agent | `swe-agent` | adapter matrix, real-world benchmark |
| LangGraph | `langgraph` | hosted fixture, real-world benchmark |
| LangSmith file export | `langsmith` | hosted fixture, real-world benchmark |
| LangSmith service export | `service-export langsmith` then `ingest --format langsmith` | native-export-tested, adapter matrix, installed release smoke |
| Langfuse | `langfuse` | OTEL round-trip, real-world benchmark |
| Langfuse service export | `service-export langfuse` then `ingest --format generic` | native-export-tested, adapter matrix, installed release smoke |
| Phoenix | `phoenix` or `auto` for Phoenix CLI trace exports | OpenInference round-trip, Phoenix CLI export fixture, real-world benchmark |
| OpenAI Agents SDK | `openai-agents` | adapter matrix, integration kit |

## Standards Paths

Frameworks that emit OpenTelemetry or OpenInference traces can use the standards adapters:

| Framework | Preferred path |
| --- | --- |
| AutoGen | `opentelemetry` |
| CrewAI | `opentelemetry` through OpenTelemetry-native observability integrations |
| LlamaIndex | `opentelemetry`, `openinference`, or Phoenix |
| Haystack | `opentelemetry` |
| Semantic Kernel | `opentelemetry` |
| Any OTLP GenAI emitter | `opentelemetry` through `POST /v1/traces` or trace-file import |
| Any OpenInference emitter | `openinference` |

## Generic Bridge

Any agent can use HulunGuard if it can write JSON or JSONL records with these fields:

- `type`
- `summary`
- `result`
- `phase`
- `evidence`
- `refs`
- `action_key`
- `prompt_tokens`
- `completion_tokens`
- `cost`
- `latency_ms`
- `model`

Use:

```powershell
python -m hulun_guard ingest --format generic --file events.jsonl --scan
'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass"}' | python -m hulun_guard batch ingest-stdin --format generic
python -m hulun_guard collector serve
python -m hulun_guard collector serve --flush-interval-seconds 5 --scan-on-flush --init-if-missing
python -m hulun_guard collector shutdown-check --json
python -m hulun_guard collector status --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0 --json
python -m hulun_guard collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json
python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
python -m hulun_guard collector service-lifecycle --output .hulun/collector-service-lifecycle --force --json
```

For host runtimes that already hold events or spans in memory, use `HulunGuardClient.enqueue_payload(...)`, MCP `hulun_batch_ingest_payload`, `batch ingest-stdin`, or `collector serve`, and then flush the durable queue. This is the preferred path for live stream integrations where writing a trace file first would add latency or operational friction.

## Boundaries

- A listed framework does not mean HulunGuard controls that framework.
- Direct adapters mean HulunGuard can ingest compatible exported shapes.
- Standards paths require the user to export or submit OTLP JSON or OpenInference-compatible spans.
- Native service exports require explicit endpoint, project id, credentials, output path, and bounded page settings.
- The generic bridge requires the user to map agent events into HulunGuard event fields.
- The local HTTP collector accepts JSON/JSONL only; OTLP producers must use OTLP/HTTP JSON rather than protobuf.
- Raw private prompts, completions, tool arguments, credentials, and customer logs should not be committed.

