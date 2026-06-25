# HulunGuard SDK And MCP

HulunGuard exposes stable adapter surfaces for agents that should record runtime state without shell glue:

- Python SDK: import `HulunGuardClient` and write events directly.
- MCP stdio server: run `hulun-mcp` or `python -m hulun_guard.mcp` from any MCP-capable host.
- CLI stdin bridge: pipe JSON/JSONL payloads to `hulun batch ingest-stdin`.
- Local HTTP collector: POST OTLP/HTTP JSON or adapter payloads to `hulun collector serve`.

All surfaces use the same event schema, privacy redaction defaults, and risk engine.

## Python SDK

```python
from hulun_guard import HulunGuardClient

client = HulunGuardClient(".")
client.init(
    objective="Ship an evidence-backed agent workflow",
    criteria=["final claims have verification evidence"],
)

observed = client.observe(
    event_type="tool_result",
    phase="verify",
    summary="pytest passed",
    result="pass",
    source_platform="my-agent",
    action_key="pytest",
    scan=True,
)

print(observed["risk"]["slop_index"])
```

For high-frequency emitters, queue first and flush in bounded batches:

```python
client.enqueue(
    event_type="tool_result",
    phase="verify",
    summary="pytest passed",
    result="pass",
    source_platform="my-agent",
)

print(client.queue_status()["queue"]["pending"])

flushed = client.flush_queue(limit=500, scan=True)
print(flushed["risk"]["slop_index"])
```

Queue an in-memory runtime payload when the host framework already has spans or stream events available:

```python
client.enqueue_payload(
    {
        "events": [
            {
                "type": "tasks",
                "event_type": "tool_result",
                "phase": "verify",
                "summary": "pytest passed",
                "result": "pass",
                "action_key": "pytest",
            }
        ]
    },
    source_format="langgraph",
    source_name="langgraph-stream",
)
client.flush_queue(scan=True)
```

### Project Methods

- `init(objective, criteria=None, constraints=None, assumptions=None, threshold=66, force=False)`: create `.hulun/state.json`.
- `observe(event_type, summary, ..., scan=False)`: record a project observation.
- `enqueue(event_type, summary, ...)`: append one normalized observation to the durable local batch queue.
- `enqueue_trace_file(file, source_format="auto", source_platform=None, max_trace_bytes=None)`: parse a supported trace file and queue normalized observations.
- `enqueue_payload(payload, source_format="auto", source_name=None, source_platform=None, max_payload_bytes=None)`: normalize an in-memory trace payload and queue its observations.
- `queue_status()`: report pending queue records, queue bytes, parse errors, and dead letters.
- `flush_queue(limit=500, scan=False, init_if_missing=False, ...)`: move queued observations into the project ledger and optionally recompute risk.
- `scan(threshold=None, final_attempt=False, checkpoint_stale_minutes=45)`: recompute project HulunIndex.
- `load_state()`: return the current project ledger.

Useful `observe` fields:

- `phase`: `explore`, `plan`, `implement`, `verify`, `recover`, `summarize`, `final`, or `orchestrate`.
- `claims`: completion or verification claims.
- `evidence`: evidence ids supporting the observation.
- `refs`: paths, URLs, trace ids, or command references.
- `action_key`: stable retry-loop fingerprint.
- `prompt_tokens`, `completion_tokens`, `cost`, `latency_ms`, `model`: model pressure signals.

### Conversation Methods

```python
conversation = client.start_conversation(name="codex-live-task", group="HulunGuard")

client.conversation_event(
    conversation_id=conversation["id"],
    event_type="tool_call",
    phase="verify",
    summary="Run pytest",
    action_key="pytest",
)

client.conversation_event(
    conversation_id=conversation["id"],
    event_type="tool_result",
    phase="verify",
    summary="pytest passed",
    action_key="pytest",
)
```

- `start_conversation(name, group="default", objective=None, monitor=False, widget=False)`: create a live runtime conversation.
- `conversation_event(conversation_id, event_type, summary, ...)`: record a live event and return conversation risk.
- `conversation_scan(conversation_id, checkpoint_stale_minutes=45)`: recompute conversation risk.
- `conversation_status(conversation_id)`: return conversation state.
- `close_conversation(conversation_id)`: close a conversation.

## MCP Server

Start a stdio MCP server for the current project root:

```powershell
hulun-mcp --root .
```

Equivalent module form:

```powershell
python -m hulun_guard.mcp --root .
```

The CLI also exposes:

```powershell
python .\hulun.py --root . mcp
```

Available tools:

- `hulun_project_init`: initialize a project ledger.
- `hulun_observe`: record a project observation and optionally scan.
- `hulun_scan`: scan the project ledger.
- `hulun_batch_enqueue`: append one observation to the durable batch queue.
- `hulun_batch_status`: inspect pending queue records and dead letters.
- `hulun_batch_ingest_payload`: normalize an in-memory trace payload and append its observations to the durable batch queue.
- `hulun_batch_flush`: flush queued observations into the project ledger and optionally scan.
- `hulun_conversation_start`: start a live conversation monitor.
- `hulun_conversation_event`: record a live conversation event.
- `hulun_conversation_scan`: scan a live conversation.

MCP responses include both human-readable text content and `structuredContent`.

The server implements the MCP Tools interface for protocol version `2025-11-25`.

## HTTP Collector

Start a local collector when the host runtime can emit HTTP traces:

```powershell
python -m hulun_guard collector serve
```

Default endpoint:

```text
http://127.0.0.1:4318/v1/traces
```

The collector accepts OTLP/HTTP JSON at `/v1/traces` and adapter payloads at `/ingest` or `/ingest/<format>`. It writes to `.hulun/ingest_queue.jsonl`; use `hulun batch flush --scan` to import queued observations into the project ledger.

For a long-running local monitor, enable managed flush:

```powershell
python -m hulun_guard collector serve --flush-interval-seconds 5 --scan-on-flush --init-if-missing
```

Check operations status without opening the HTTP server, or generate reviewed service templates for a local service manager:

```powershell
python -m hulun_guard collector status --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0 --json
python -m hulun_guard collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python -m hulun_guard collector shutdown-check --json
python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json
python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
python -m hulun_guard collector service-lifecycle --output .hulun/collector-service-lifecycle --force --json
```

Run the non-blocking smoke and operations checks in CI or release gates:

```powershell
python -m hulun_guard collector smoke --json
python -m hulun_guard collector smoke --managed --scan --init-if-missing --json
python -m hulun_guard collector status --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0 --json
python -m hulun_guard collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
python -m hulun_guard collector shutdown-check --json
python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json
python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
python -m hulun_guard collector service-lifecycle --output .hulun/collector-service-lifecycle --force --json
```

## Privacy Defaults

SDK and MCP use the same defaults as the CLI:

- Secrets, emails, private home paths, and URL query strings are redacted.
- Raw trace payloads should be summarized by adapters before recording.
- Stored events include `privacy.mode` and `privacy.retention_days`.

Only use sensitive mode for trusted local debugging:

```python
client = HulunGuardClient(".", include_sensitive=True, retention_days=7)
```

```powershell
hulun-mcp --root . --include-sensitive --retention-days 7
```

## Compatibility Contract

The SDK and MCP tools are intended as the stable adapter layer. Future releases may add optional fields, but should not remove existing methods, tool names, or core output keys without a minor-version migration note.

The shared adapter field contract and unsupported-field policy are defined in `docs/ADAPTER_CONFORMANCE.md`.
