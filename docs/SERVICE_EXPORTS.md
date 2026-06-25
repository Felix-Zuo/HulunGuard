# Service Exports

`service-export` connects HulunGuard to hosted observability services through explicitly configured export APIs. It is for teams that already store agent traces in a platform and want to bring a bounded, privacy-safe slice into HulunGuard for local diagnosis and monitoring.

Service exports are disabled until the user supplies all required connection settings. HulunGuard does not discover credentials, does not read default API key environment variables, and does not run background network sync.

## LangSmith

Run a bounded export:

```powershell
$env:LANGSMITH_API_KEY = "<key>"
python -m hulun_guard service-export langsmith `
  --project-id "<project-id>" `
  --api-key-env LANGSMITH_API_KEY `
  --output .\langsmith-runs.json `
  --max-runs 100 `
  --json
```

Then inspect and import:

```powershell
python -m hulun_guard trace-doctor --format langsmith --file .\langsmith-runs.json --json
python -m hulun_guard ingest --format langsmith --file .\langsmith-runs.json --scan --init-if-missing
```

The connector uses LangSmith's run query endpoint, `POST /v2/runs/query`, with `X-Api-Key` authentication, selected run fields, `project_ids`, `page_size`, and cursor pagination. The public LangSmith docs describe trace export options, the run data model, the query API, authentication, and trace query filters:

- `https://docs.langchain.com/langsmith/export-traces`
- `https://docs.langchain.com/langsmith/smith-api/runs/query-runs-v2`
- `https://docs.langchain.com/langsmith/run-data-format`
- `https://docs.langchain.com/langsmith/smith-api-ref`
- `https://docs.langchain.com/langsmith/trace-query-syntax`

## Langfuse

Run a bounded export:

```powershell
$env:LANGFUSE_PUBLIC_KEY = "<public-key>"
$env:LANGFUSE_SECRET_KEY = "<secret-key>"
python -m hulun_guard service-export langfuse `
  --public-key-env LANGFUSE_PUBLIC_KEY `
  --secret-key-env LANGFUSE_SECRET_KEY `
  --from-start-time "2026-06-25T00:00:00Z" `
  --to-start-time "2026-06-25T01:00:00Z" `
  --output .\langfuse-observations.json `
  --max-observations 100 `
  --json
```

Then inspect and import:

```powershell
python -m hulun_guard trace-doctor --format generic --file .\langfuse-observations.json --json
python -m hulun_guard ingest --format generic --file .\langfuse-observations.json --scan --init-if-missing
```

The connector uses Langfuse's Observations API v2, `GET /api/public/v2/observations`, with Basic Auth where the username is the Langfuse public key and the password is the Langfuse secret key. Each request must include `fromStartTime` and `toStartTime`. The default selected field groups are `core,basic,usage,trace_context`; raw `io`, `metadata`, and `prompt` field groups are rejected.

Langfuse documents the Public API authentication model, Observations API v2 endpoint, bounded time-window requirement, selective field groups, and cursor pagination here:

- `https://langfuse.com/docs/api-and-data-platform/features/public-api`
- `https://langfuse.com/docs/api-and-data-platform/features/observations-api`
- `https://langfuse.com/changelog/2026-05-15-v2-observations-trace-context`

## Export Shape

`service-export langsmith` writes a JSON file with schema `hulun.service_export.v1`:

- `provider`: `langsmith`
- `source`: redacted endpoint, project id, query path, and response key
- `privacy`: redaction mode and retention hint
- `runs`: sanitized LangSmith run dictionaries importable with `--format langsmith`

`service-export langfuse` writes the same schema:

- `provider`: `langfuse`
- `source`: redacted endpoint, API path, selected field groups, response key, and bounded time window
- `privacy`: redaction mode and retention hint
- `observations`: sanitized HulunGuard generic observation records importable with `--format generic`

The command report also uses `hulun.service_export.v1` and includes:

- request summary without secrets
- pagination status
- output path
- exported run or observation count
- next `trace-doctor` and `ingest` commands
- gate status

## Privacy Boundary

Default mode is `redacted-default`.

The LangSmith connector requests a selected field list for run metadata and metrics. It does not request raw inputs, outputs, attachments, prompts, completions, or tool argument payloads. If a service response contains unexpected raw payload fields, the sanitizer drops them from the exported `runs` list.

The Langfuse connector requests selected observation field groups only. It does not request raw IO, metadata, prompt, or payload groups. If a service response contains unexpected raw payload fields, the sanitizer drops them from the exported `observations` list.

The LangSmith API key is used only in the outbound `X-Api-Key` header. The Langfuse public and secret keys are used only in the outbound `Authorization: Basic ...` header. Credentials are not written to the export file, command report, logs, or errors. Endpoint URLs cannot contain usernames, passwords, query strings, or fragments.

Use `--include-sensitive` only in a trusted local working copy. It disables text redaction for selected metadata fields, but it does not widen the default LangSmith selected field list or the default Langfuse field groups.

## Pagination And Limits

Defaults:

- `--page-size 100`
- `--max-runs 100`
- `--limit 100`
- `--max-observations 100`
- `--timeout-seconds 30`

`--page-size` and `--limit` are bounded between 1 and 1000. `--max-runs` and `--max-observations` stop the export even if the service reports another cursor. The report marks `pagination.truncated=true` when a cursor remains or the service returned more records than requested.

Use time or query filters for production projects:

```powershell
python -m hulun_guard service-export langsmith `
  --project-id "<project-id>" `
  --api-key-env LANGSMITH_API_KEY `
  --min-start-time "2026-06-25T00:00:00Z" `
  --max-start-time "2026-06-25T01:00:00Z" `
  --filter 'eq(run_type, "llm")' `
  --output .\langsmith-hour.json `
  --json
```

For large historical exports, use the service's native bulk export workflow first, then import a bounded public-safe slice through HulunGuard.

## Failure Modes

| Failure | Behavior |
| --- | --- |
| Missing credentials | Command exits before any network request. |
| Endpoint with credentials or query string | Command exits before any network request. |
| HTTP 401 or 403 | Command reports authentication failure without echoing the key. |
| HTTP 429 | Command reports rate limiting and suggests lowering page size, lowering limit, or retrying later. |
| Non-2xx response | Command reports the status code without dumping the response body. |
| Malformed JSON | Command fails without writing a partial export. |
| Missing `runs`, `items`, `data`, or `observations` list | Command fails as malformed service response. |
| Langfuse missing bounded times | Command exits before any network request. |
| Langfuse raw field groups | Command exits before any network request. |
| Existing output file | Command refuses to overwrite unless `--force` is supplied. |

## Release Gate

The connector is verified without real credentials:

- unit tests inject mocked transports for success, auth failure, pagination, malformed response, and redaction
- `adapter-matrix` includes `langsmith_service_export` and `langfuse_service_export` native-export-tested cases
- `schema-check` covers `hulun.service_export.v1`
- `scripts/verify_release_artifacts.py` runs the installed CLI against loopback mock LangSmith and Langfuse servers and then runs `trace-doctor` on the exported files

