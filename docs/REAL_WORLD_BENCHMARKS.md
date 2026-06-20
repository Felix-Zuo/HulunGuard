# Real-World Benchmarks

HulunGuard's real-world benchmark suite is a public-safe regression gate for agent reliability monitoring. It is separate from calibration: calibration estimates scoring quality over labeled trajectories, while this benchmark checks representative workflow behavior, scan speed, fixture size, component stability, and false-positive or false-negative behavior.

Run it before releases:

```powershell
python -m hulun_guard benchmark --suite real-world
python -m hulun_guard benchmark --suite real-world --json
```

The command writes:

- `.hulun/real_world_benchmark_report.json`
- `.hulun/real_world_benchmark_report.md`

The JSON report uses schema `hulun.real_world_benchmark.v1`.

## Current Coverage

The suite contains 12 public-safe cases:

| Workflow | Cases | Source shape |
| --- | ---: | --- |
| coding | 3 | SWE-agent trajectories and OpenHands event logs |
| research | 3 | OpenInference traces |
| ops | 3 | OpenTelemetry GenAI spans |
| artifact | 3 | OpenHands events and SWE-agent trajectories |

Each case records:

- workflow class
- public source URI
- redaction status
- expected risk band
- expected risk components
- fixture byte size
- scan latency
- false-positive / false-negative status
- component misses and unexpected components

## Gate Rules

The gate fails when:

- any public-safe fixture exceeds `--max-case-bytes`
- total fixture size exceeds `--max-total-bytes`
- any case exceeds `--max-case-ms`
- any expected risk case scans green
- any expected green case scans yellow or red
- any expected component is missing
- any unexpected component appears
- false-positive rate exceeds `--max-false-positive-rate`
- false-negative rate exceeds `--max-false-negative-rate`
- component stability falls below `--min-component-stability`

Defaults are intentionally strict for release review:

```text
--max-case-ms 50
--max-case-bytes 65536
--max-total-bytes 524288
--min-component-stability 1.0
--max-false-positive-rate 0.0
--max-false-negative-rate 0.0
```

## Adding Cases

Add cases in `src/hulun_guard/benchmarks.py`.

A new case must:

- use one of the workflow classes: `coding`, `research`, `ops`, or `artifact`
- be derived from a public schema, public documentation, or a fully synthetic scenario
- include a public `source_uri`
- include a short `label_source`
- include `redaction_status="public-schema-derived-no-private-content"`
- define `expected_band`
- define the exact `expected_components`
- stay below the default fixture-size limit
- avoid raw prompts, completions, tool arguments, credentials, customer records, production logs, or private conversation text

Allowed source material:

- public documentation explaining trace or event shape
- public schema examples with secrets removed
- synthetic event summaries that describe behavior without copying a private transcript

Disallowed source material:

- private HulunGuard `.hulun/` state
- real customer logs
- personal email addresses
- API keys, tokens, passwords, cookies, headers, or session IDs
- screenshots or files from private work
- production incident logs unless rewritten into a synthetic public-safe summary

When changing scoring behavior, run:

```powershell
python -m hulun_guard benchmark --suite real-world --json
```

If a component changes, update the fixture label only when the new behavior is intentional and the issue or pull request explains why.

## Public Sources

The current suite uses schema-derived fixtures from:

- OpenHands event documentation: `https://docs.openhands.dev/sdk/arch/events`
- SWE-agent trajectory documentation: `https://swe-agent.com/latest/usage/trajectories/`
- OpenTelemetry GenAI attributes: `https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/`
- OpenInference specification: `https://arize-ai.github.io/openinference/spec/`
