# Schema Compatibility

HulunGuard public JSON outputs are versioned with `hulun.<kind>.v<major>`.

Current public schemas:

| Kind | Current schema |
| --- | --- |
| state | `hulun.state.v1` |
| risk | `hulun.risk.v1` |
| conversation | `hulun.conversation.v1` |
| conversation risk | `hulun.conversation_risk.v1` |
| validation | `hulun.validation.v1` |
| trajectory dataset | `hulun.trajectory_dataset.v1` |
| calibration | `hulun.calibration.v1` |
| calibration baseline | `hulun.calibration_baseline.v1` |
| calibration drift | `hulun.calibration_drift.v1` |
| scan benchmark | `hulun.benchmark.v1` |
| real-world benchmark | `hulun.real_world_benchmark.v1` |
| real-world fixture | `hulun.real_world_fixture.v1` |
| retention cleanup | `hulun.retention_cleanup.v1` |
| doctor | `hulun.doctor.v1` |
| OpenTelemetry export command report | `hulun.export.opentelemetry.v1` |
| adapter integration matrix report | `hulun.adapter_matrix.v1` |
| agent compatibility report | `hulun.agent_compatibility.v1` |
| integration kit report | `hulun.integration_kit.v1` |
| schema compatibility report | `hulun.schema_compatibility.v1` |
| threat model check report | `hulun.threat_model_check.v1` |

The OpenTelemetry export file itself follows OTLP JSON. The HulunGuard command report around that export is versioned.

## Compatibility Promise

Within schema major `v1`, HulunGuard may add optional fields but must not rename or remove existing public fields without a migration path.

The loader normalizes older project and conversation ledgers into current schemas before use. Migration must preserve:

- evidence records and evidence references
- privacy metadata
- runtime events
- checkpoints
- last risk scan fields
- monitor and conversation ids
- calibration, benchmark, and adapter report gate fields
- adapter matrix support tiers, public-safe fixture policy, case outcomes, and gate failures
- agent compatibility categories, tiers, source URIs, ingest formats, and commands
- integration kit generated files, ingest commands, sample trace paths, and verification outcomes

Unsupported future schema majors fail the compatibility gate instead of being guessed.

## Release Gate

Run:

```powershell
python -m hulun_guard schema-check --json
```

The gate loads built-in legacy fixtures from `hulun_guard/schema_fixtures` unless `--fixture-dir` is supplied. It normalizes each legacy payload and verifies that the output schema matches the current registry in `src/hulun_guard/schemas.py`.

Schema compatibility is also included in `python -m hulun_guard doctor --run-validation`.

## Versioning Rules

Use a minor version bump when a change:

- adds a public JSON schema
- adds, removes, or renames public JSON fields
- changes migration or normalization behavior
- changes threat model check behavior
- changes adapter matrix report behavior
- changes integration kit report behavior
- changes adapter import/export report fields
- changes release gate behavior for schemas

Use a patch version only for documentation, packaging metadata, or implementation fixes that do not change public JSON shape or compatibility behavior.

Pre-1.0 major compatibility is enforced by the release gate, not by claiming frozen APIs.
