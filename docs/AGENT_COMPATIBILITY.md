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
| LangSmith | `langsmith` | hosted fixture, real-world benchmark |
| Langfuse | `langfuse` | OTEL round-trip, real-world benchmark |
| Phoenix | `phoenix` | OpenInference round-trip, real-world benchmark |

## Standards Paths

Frameworks that emit OpenTelemetry or OpenInference traces can use the standards adapters:

| Framework | Preferred path |
| --- | --- |
| AutoGen | `opentelemetry` |
| CrewAI | `opentelemetry` through OpenTelemetry-native observability integrations |
| LlamaIndex | `opentelemetry`, `openinference`, or Phoenix |
| Haystack | `opentelemetry` |
| Semantic Kernel | `opentelemetry` |
| Any OTLP GenAI emitter | `opentelemetry` |
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
```

OpenAI Agents SDK traces can use this bridge through exported trace events, or a tracing processor can emit OTLP JSON for the OpenTelemetry adapter.

## Boundaries

- A listed framework does not mean HulunGuard controls that framework.
- Direct adapters mean HulunGuard can ingest compatible exported shapes.
- Standards paths require the user to export OTLP JSON or OpenInference-compatible spans.
- The generic bridge requires the user to map agent events into HulunGuard event fields.
- Raw private prompts, completions, tool arguments, credentials, and customer logs should not be committed.

