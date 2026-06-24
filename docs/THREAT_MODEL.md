# HulunGuard Threat Model

HulunGuard is a local-first reliability monitor for agent work. It records execution evidence, runtime events, risk scores, and adapter-imported observations so an agent can be checked against proof and recovery signals.

This document defines what the product protects, what it does not protect, and which release gates keep those boundaries from drifting.

## Security Boundary

HulunGuard runs with the permissions of the local user who starts it. It is not a sandbox for untrusted code, a secret scanner, a malware detector, or an access-control layer.

The product boundary is:

- local project state under `<project>/.hulun`
- local conversation state under `HULUN_HOME/conversations`
- optional local desktop monitor files under `HULUN_HOME`
- user-provided trace files passed to `hulun ingest`
- runtime payloads submitted through SDK, MCP, or `batch ingest-stdin`
- runtime payloads submitted to the local HTTP collector
- explicit export paths passed to commands such as `export-otel`

Any agent, hook, or adapter that can write to those locations can affect HulunGuard state. Treat adapter processes as trusted local producers unless they are isolated by the host application.

## Local Data

HulunGuard may store these local records:

- project objective, criteria, assumptions, steps, risks, decisions, and checkpoints
- evidence summaries, command references, file references, URLs, hashes, and notes
- runtime events, phases, claims, evidence IDs, action keys, token counts, cost, latency, model name, and result status
- risk reports, validation reports, calibration reports, benchmark reports, schema compatibility reports, integration kit manifests, onboarding reports, retention cleanup reports, and threat model check reports
- conversation runtime events, monitor IDs, live scores, and board data

Generated runtime files are local artifacts. Do not commit `.hulun/`, `HULUN_HOME/conversations`, private traces, credentials, customer data, production logs, or private screenshots.

## Remote Behavior

HulunGuard does not send local state, traces, prompts, completions, tool arguments, tool results, evidence, or risk reports to a remote service by itself.

Remote activity can still happen outside HulunGuard when:

- the user runs GitHub, package, or release commands
- a host agent, MCP client, or OpenClaw hook sends data through its own integrations
- a user publishes release assets, docs, screenshots, or generated reports
- a user exports local data and uploads it manually

HulunGuard's release workflow uploads built wheel and sdist artifacts plus GitHub provenance for source releases. Release assets must not include private runtime ledgers or trace files.

## Adapter Inputs

Adapters may import user-provided local trace files in these formats:

- generic JSON or JSONL
- OpenTelemetry GenAI OTLP-style JSON or JSONL
- OpenInference-style spans
- OpenHands-like event logs
- SWE-agent-like trajectories
- in-memory or stdin JSON/JSONL payloads from supported runtime adapters
- local HTTP collector payloads posted to `/v1/traces`, `/ingest`, or `/ingest/<format>`
- CLI, Python SDK, MCP, and OpenClaw hook events

By default, imported observations preserve only scoring-relevant structure: event type, phase, result, sanitized summary, evidence IDs, sanitized references, action fingerprints, model pressure, latency, and privacy metadata.

Trace files are capped by `MAX_TRACE_BYTES`, currently 5 MiB, unless the user explicitly passes `--max-trace-bytes`. Oversized trace files fail before JSON parsing or persistence.

Runtime payloads submitted through SDK, MCP, or stdin are capped by the same default 5 MiB limit unless the caller explicitly raises `max_payload_bytes` or `--max-payload-bytes`. Queue metadata stores a redacted logical source name and a payload fingerprint instead of the raw payload text.

Runtime payloads submitted through `hulun collector serve` use the same default payload cap and redaction path. The collector binds to `127.0.0.1` by default. Binding to a non-loopback host requires both `--allow-remote` and `--token`. `/healthz` exposes only liveness and supported-format metadata; `/status` and POST ingestion require the configured token. The collector accepts JSON and JSONL payloads and rejects protobuf or opaque binary OTLP bodies.

Managed collector mode is opt-in through `--flush-interval-seconds`. It uses the existing batch flush path to move queued observations into `.hulun/state.json`, optionally initializes a minimal project ledger with `--init-if-missing`, writes `.hulun/collector_status.json`, and recomputes `.hulun/risk.json` only when `--scan-on-flush` is enabled. Flush or scan failures are reported in status output and do not stop HTTP ingestion.

`collector status` reads local queue, dead-letter, managed status, and risk files without starting the HTTP server. `collector service-template` only writes reviewed systemd, launchd, and Windows Scheduled Task template files; it does not install services, change host startup policy, or embed authentication tokens.

## Sensitive Data

Default mode is `redacted-default`.

HulunGuard redacts or withholds:

- known API key, token, password, bearer-token, AWS key, GitHub token, GitLab token, and private-key patterns
- email addresses
- local home directory paths
- URL query strings and fragments
- raw prompt, response, completion, output, content, tool argument, tool result, and message payloads from traces unless a safe summary exists

Redaction is best-effort pattern-based protection. It cannot guarantee removal of every private value, regulated identifier, or domain-specific secret. Users must still review artifacts before publication.

Use `--include-sensitive` only for trusted local debugging. Pair it with a short retention period, for example `--retention-days 7`.

## Retention And Cleanup

Stored events and evidence include `privacy.mode` and `privacy.retention_days`.

Cleanup is dry-run by default:

```powershell
python -m hulun_guard cleanup --json
```

Apply cleanup only in a trusted local working copy:

```powershell
python -m hulun_guard cleanup --apply --write-report
```

Cleanup refuses to delete outside:

- `<project>/.hulun`
- `HULUN_HOME/conversations`

This protects against path traversal, symlink escape, and accidental deletion of source-controlled files.

## Threat Scenarios

| Scenario | Control |
| --- | --- |
| Malicious trace file attempts memory pressure | `MAX_TRACE_BYTES` and `--max-trace-bytes` reject oversized files before parsing. |
| Malformed trace JSON causes partial persistence | Ingest reads and normalizes observations before saving state; parse failures abort the command. `trace-doctor` can preflight parseability and adapter importability without writing the project ledger. |
| Trace contains prompts, tool outputs, or credentials | Default redaction withholds raw payload fields and applies secret/email/path/URL sanitizers. |
| User needs raw local trace text for debugging | `--include-sensitive` is explicit opt-in and writes `privacy.mode=sensitive-opt-in`. |
| Cleanup path escapes the intended state directory | Cleanup resolves candidate paths under the allowed base and reports safety violations. |
| Oversized public benchmark fixtures hide release risk | Real-world benchmark limits fixture size with `--max-case-bytes` and `--max-total-bytes`. |
| Generated onboarding samples accidentally include private data | Integration kits and onboarding samples use synthetic public-safe traces and are verified through adapters before release. |
| Generated report accidentally enters a release | Release asset policy excludes `.hulun/`, traces, credentials, customer logs, and private screenshots. |
| Future public JSON schema is guessed incorrectly | `schema-check` rejects unsupported future schema majors. |
| Adapter writes malformed runtime fields | SDK and MCP validation reject invalid phase/result values without persisting bad events. |
| Batched ingestion queue contains malformed records | `batch flush` moves malformed queue records to `.hulun/ingest_dead_letter.jsonl` and continues flushing valid records. |
| Host pipes an oversized runtime payload | `batch ingest-stdin`, SDK `enqueue_payload`, and MCP `hulun_batch_ingest_payload` reject oversized JSON payloads before queue persistence. |
| Local HTTP collector is accidentally exposed | Default bind is loopback-only; non-loopback bind requires `--allow-remote --token`; POST and `/status` require the token when configured. |
| OTLP producer sends protobuf or binary payloads | Collector rejects protobuf and `application/octet-stream`; configure the producer for OTLP/HTTP JSON. |
| Managed collector writes project state unexpectedly | Managed flush is off by default and requires explicit `--flush-interval-seconds`; scan is separate through `--scan-on-flush`. |
| Service template generation changes host startup state | `collector service-template` writes files only; operators must review and install them explicitly. |
| Desktop monitor leaks to a remote service | Monitor state is local JSON/HTML; remote exposure only occurs if the user or host publishes it. |

## Safe Usage Modes

Use default mode for normal work:

```powershell
python -m hulun_guard ingest --file .\trace.jsonl --scan
python -m hulun_guard trace-doctor --file .\trace.jsonl --json
python -m hulun_guard observe --type tool_result --summary "pytest passed" --scan
python -m hulun_guard batch enqueue --type tool_result --summary "pytest passed"
'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass"}' | python -m hulun_guard batch ingest-stdin --format generic
python -m hulun_guard collector smoke --json
python -m hulun_guard collector smoke --managed --scan --init-if-missing --json
python -m hulun_guard collector status --require-status-file --json
python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
python -m hulun_guard batch flush --scan
```

Use sensitive mode only in a trusted local working copy:

```powershell
python -m hulun_guard ingest --file .\trace.jsonl --include-sensitive --retention-days 7
```

Before publishing:

```powershell
python -m hulun_guard threat-model-check --json
python -m hulun_guard compatibility --json
python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify --json
python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
python -m hulun_guard adapter-matrix --json
python -m hulun_guard collector smoke --json
python -m hulun_guard collector smoke --managed --scan --init-if-missing --json
python -m hulun_guard collector status --require-status-file --json
python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
python -m hulun_guard trace-doctor --file trace-doctor-sample.jsonl --format generic --json
python -m hulun_guard cleanup --json
python -m hulun_guard schema-check --json
```

Do not publish private runtime files, local screenshots with private data, raw traces, credentials, customer files, production logs, or generated `.hulun/` reports.

## Release Rules

Every release must keep these checks green:

- `python -m hulun_guard threat-model-check --json`
- `python -m hulun_guard compatibility --json`
- `python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify --json`
- `python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json`
- `python -m hulun_guard adapter-matrix --json`
- `python -m hulun_guard collector smoke --json`
- `python -m hulun_guard collector smoke --managed --scan --init-if-missing --json`
- `python -m hulun_guard collector status --require-status-file --json`
- `python -m hulun_guard collector service-template --output .hulun/collector-service --force --json`
- `'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass"}' | python -m hulun_guard batch ingest-stdin --format generic --json`
- `python -m hulun_guard trace-doctor --file trace-doctor-sample.jsonl --format generic --json`
- `python -m hulun_guard schema-check --json`
- `python -m hulun_guard cleanup --json`
- adapter conformance tests
- redaction and sensitive-mode tests
- path-boundary cleanup tests
- release asset and provenance checks
- `python -m hulun_guard release-verify <tag> --json` for published checksum, SBOM, and attestation checks

Changes that alter local storage, adapter imports, redaction, retention, cleanup, export behavior, public JSON fields, or release asset policy require a minor version bump before 1.0.
