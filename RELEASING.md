# Releasing

HulunGuard uses semantic versioning while it is pre-1.0:

- Patch: documentation, packaging metadata, or non-behavioral fixes.
- Minor: scoring behavior, adapter behavior, CLI commands, workflow changes, or user-visible features.
- Major: reserved for 1.0 compatibility guarantees.

## Release Gate

Run locally:

```powershell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m bandit -q -r src
python -m compileall -q src tests
python -m pytest -q
python -m hulun_guard validate
python -m hulun_guard calibrate
python -m hulun_guard calibration-drift
python -m hulun_guard threat-model-check --json
python -m hulun_guard compatibility --json
python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify --json
python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
python -m hulun_guard adapter-matrix --json
python -m hulun_guard schema-check --json
python -m hulun_guard cleanup --json
python -m hulun_guard benchmark --events 10000 --max-ms 1000
python -m hulun_guard benchmark --suite real-world
python -m build
```

GitHub must pass:

- CI matrix.
- CodeQL and Bandit.
- OpenSSF Scorecard.
- Release workflow with artifact provenance on tags.
- Dependabot has no unresolved critical updates.

## Version Checklist

1. Update `pyproject.toml`.
2. Update `src/hulun_guard/__init__.py`.
3. Update `CHANGELOG.md`.
4. Commit with a clear release-oriented message.
5. Tag the commit, for example `v0.6.0`.
6. Push `main` and tags.
7. Confirm GitHub Actions pass, including Release on tags.
8. Confirm GitHub Release assets were uploaded by the release workflow.
9. Confirm build provenance attestations exist for release artifacts.
10. Create or update GitHub issues for unfinished maturity work.

See `docs/SUPPLY_CHAIN.md` for branch protection and release approval gates. See `docs/THREAT_MODEL.md` for the local-first security boundary.

## Artifact Policy

Do not release generated private state:

- `.hulun/`
- private trace files
- credentials
- local screenshots with private data
- customer or production logs
