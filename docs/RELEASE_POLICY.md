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
python .\hulun.py adapter-matrix --json
python .\hulun.py schema-check --json
python .\hulun.py cleanup --json
python .\hulun.py benchmark --events 10000
python .\hulun.py benchmark --suite real-world
python .\hulun.py doctor --run-validation
python -m build
```

## Version Steps

1. Update `pyproject.toml`.
2. Update `src/hulun_guard/__init__.py`.
3. Update docs for new commands, parameters, or product meaning.
4. Run tests, validation, calibration, calibration drift review, threat model check, agent compatibility, adapter matrix, schema compatibility, and retention cleanup dry-run.
5. Run scan benchmark, real-world benchmark, doctor, security, and build checks.
6. Commit with a versioned message.
7. Tag the version.
8. Push to `origin/main` with tags.
9. Confirm the Release workflow publishes artifacts with provenance.
10. Confirm required branch protection rules are active.

## Current Policy

- Patch versions: documentation, packaging metadata, or internal fixes that do not change public JSON shape or user-visible behavior.
- Minor versions: new CLI commands, adapters, validation suites, scoring dimensions, public JSON fields, schema migration behavior, or release gates.
- Major versions: incompatible CLI or schema changes once 1.0 compatibility rules are declared.

Supply-chain controls are defined in `docs/SUPPLY_CHAIN.md`. The local-first security boundary is defined in `docs/THREAT_MODEL.md`.
