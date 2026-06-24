# HulunGuard Release Policy

Every version of HulunGuard must be committed and pushed to GitHub.

## Required Checks

Run these before every version push:

```powershell
python -m pytest -q
python .\hulun.py validate
python .\hulun.py calibrate
python .\hulun.py calibration-drift
python .\hulun.py threat-model-check --json
python .\hulun.py compatibility --json
python .\hulun.py integration-kit --agent all --output .\.hulun\integration-kits --force --verify --json
python .\hulun.py onboard --agent all --output .\.hulun\onboarding --force --json
python .\hulun.py adapter-matrix --json
python .\hulun.py collector smoke --json
python .\hulun.py collector smoke --managed --scan --init-if-missing --json
python .\hulun.py collector status --require-status-file --json
python .\hulun.py collector metrics --require-status-file
python .\hulun.py collector service-template --output .\.hulun\collector-service --force --json
python .\hulun.py batch enqueue --type tool_result --phase verify --summary "release batch smoke" --result pass --json
@'
{"type":"tool_result","phase":"verify","summary":"release stdin smoke","result":"pass","action_key":"stdin-smoke"}
'@ | python .\hulun.py batch ingest-stdin --format generic --json
python .\hulun.py batch status --json
python .\hulun.py batch flush --scan --init-if-missing --json
'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest","refs":["command:pytest"]}' | Set-Content -Encoding UTF8 trace-doctor-sample.jsonl
python .\hulun.py trace-doctor --file trace-doctor-sample.jsonl --format generic --json
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python .\hulun.py doctor --run-validation
python -m build
python scripts/generate_release_metadata.py --verify --json
python scripts/verify_release_artifacts.py
python .\hulun.py release-verify --asset-dir .\dist --skip-attestation --json
```

## Version Steps

1. Update `pyproject.toml`.
2. Update `src/hulun_guard/__init__.py`.
3. Update docs for new commands, parameters, or product meaning.
4. Run tests, validation, calibration, calibration drift review, threat model check, agent compatibility, integration kit verification, onboarding verification, adapter matrix, collector smoke, managed collector smoke, collector operations status, collector Prometheus metrics, collector service-template generation, batched ingestion and stdin payload smoke, trace doctor, schema compatibility, and retention cleanup dry-run.
5. Run scan benchmark, real-world benchmark, doctor, security, build, release metadata, release artifact smoke, and offline release verifier checks.
6. Commit with a versioned message.
7. Tag the version.
8. Push to `origin/main` with tags.
9. Confirm the Release workflow publishes artifacts with provenance.
10. Confirm `SHA256SUMS` and CycloneDX SBOM assets are present.
11. Confirm release artifacts install and run from a clean virtual environment.
12. Run the published-release verifier against the tag.
13. Confirm required branch protection rules are active.

## Current Policy

- Patch versions: documentation, packaging metadata, or internal fixes that do not change public JSON shape or user-visible behavior.
- Minor versions: new CLI commands, adapters, validation suites, scoring dimensions, public JSON fields, schema migration behavior, or release gates.
- Major versions: incompatible CLI or schema changes once 1.0 compatibility rules are declared.

Supply-chain controls are defined in `docs/SUPPLY_CHAIN.md`. The local-first security boundary is defined in `docs/THREAT_MODEL.md`.
