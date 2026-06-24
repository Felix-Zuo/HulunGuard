# Local HTTP Collector

`hulun collector serve` runs a local HTTP ingestion endpoint for live agent runtimes.

Use it when an agent, IDE, framework, or observability pipeline can emit OTLP/HTTP JSON or POST JSON/JSONL events, and you want HulunGuard to monitor the run without writing trace files first.

## Start

```powershell
python -m hulun_guard collector serve
```

Default bind:

- host: `127.0.0.1`
- port: `4318`
- OTLP traces endpoint: `http://127.0.0.1:4318/v1/traces`

Smoke-test the installed collector without leaving a long-running server:

```powershell
python -m hulun_guard --root . collector smoke --json
python -m hulun_guard --root . collector smoke --managed --scan --init-if-missing --json
python -m hulun_guard batch status --json
python -m hulun_guard batch flush --scan --init-if-missing --json
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Liveness and supported formats. |
| `GET` | `/status` | Queue status. Requires token when `--token` is set. |
| `POST` | `/v1/traces` | OTLP/HTTP JSON traces. |
| `POST` | `/ingest` | Auto-detected JSON or JSONL runtime payload. |
| `POST` | `/ingest/<format>` | Explicit adapter payload format. |

Supported explicit formats:

- `generic`
- `opentelemetry`
- `openinference`
- `openhands`
- `swe-agent`
- `langgraph`
- `langsmith`
- `langfuse`
- `phoenix`
- `openai-agents`

The collector queues normalized observations into `.hulun/ingest_queue.jsonl`. It does not rewrite `.hulun/state.json` on every request. Use `hulun batch flush --scan` to import queued observations and recalculate the HulunIndex.

## Managed Flush

Queue-only mode is the default. Use managed mode when this process should keep the local project ledger and HulunIndex current without a separate scheduler:

```powershell
python -m hulun_guard collector serve `
  --flush-interval-seconds 5 `
  --flush-limit 500 `
  --scan-on-flush `
  --init-if-missing
```

Managed mode:

- flushes at most `--flush-limit` queued observations per cycle
- uses the same `batch flush` safety path, redaction, dead-letter handling, and initialization controls
- writes `.hulun/collector_status.json`
- updates `.hulun/risk.json` when `--scan-on-flush` imports observations
- reports flush failures in `/status` and the status file without stopping HTTP ingestion

Use `GET /status` to inspect queue state and managed runtime counters.

## OTLP JSON

Configure OTLP producers for HTTP JSON:

```powershell
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/json"
```

If a runtime supports a trace-specific endpoint, use:

```powershell
$env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = "http://127.0.0.1:4318/v1/traces"
$env:OTEL_EXPORTER_OTLP_TRACES_PROTOCOL = "http/json"
```

The collector rejects protobuf payloads. This keeps the implementation dependency-free and makes request bodies auditable during adapter development.

## Security Controls

Default mode is local-only:

```powershell
python -m hulun_guard collector serve --host 127.0.0.1
```

Remote bind requires both an explicit flag and a token:

```powershell
python -m hulun_guard collector serve --host 0.0.0.0 --allow-remote --token "<local-token>"
```

Authenticated requests can use either header:

```text
Authorization: Bearer <local-token>
X-Hulun-Token: <local-token>
```

Payloads are capped by `--max-payload-bytes`, defaulting to the same 5 MiB trace limit used by file and stdin ingestion. Sensitive fields are redacted by default; use `--include-sensitive --retention-days 7` only for trusted local debugging.

## Adapter Payloads

Generic JSON:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:4318/ingest/generic `
  -ContentType "application/json" `
  -Body '{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest"}'
```

LangGraph-style stream payload:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:4318/ingest/langgraph `
  -ContentType "application/json" `
  -Body '{"events":[{"type":"tasks","phase":"verify","summary":"test task passed","result":"pass","action_key":"test-task"}]}'
```

Queue and flush:

```powershell
python -m hulun_guard batch status
python -m hulun_guard batch flush --scan --init-if-missing
```
