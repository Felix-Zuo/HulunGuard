# HulunGuard Release Policy

Every version of HulunGuard must be committed and pushed to GitHub.

## Required Checks

Run these before every version push:

```powershell
python -m pytest -q
python .\hulun.py validate
python .\hulun.py calibrate
python .\hulun.py benchmark --events 10000
python .\hulun.py doctor --run-validation
```

## Version Steps

1. Update `pyproject.toml`.
2. Update `src/hulun_guard/__init__.py`.
3. Update docs for new commands, parameters, or product meaning.
4. Run tests, validation, and calibration.
5. Run the benchmark and doctor checks.
6. Commit with a versioned message.
7. Tag the version.
8. Push to `origin/main` with tags.
9. Confirm the Release workflow publishes artifacts with provenance.
10. Confirm required branch protection rules are active.

## Current Policy

- Patch versions: bug fixes, docs, small scoring fixes.
- Minor versions: new CLI commands, adapters, validation suites, scoring dimensions.
- Major versions: incompatible state schema or CLI changes.

Supply-chain controls are defined in `docs/SUPPLY_CHAIN.md`.
