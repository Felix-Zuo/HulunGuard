# Releasing

HulunGuard uses semantic versioning while it is pre-1.0:

- Patch: documentation, packaging metadata, or non-behavioral fixes.
- Minor: scoring behavior, adapter behavior, CLI commands, workflow changes, or user-visible features.
- Major: reserved for 1.0 compatibility guarantees.

## Release Gate

Run locally:

```powershell
uv sync --locked --extra dev
uv run python -m ruff check .
uv run python -m bandit -q -r src
uv run python -m compileall -q src tests
uv run python -m pytest -q
uv run python -m hulun_guard validate
uv run python -m hulun_guard calibrate
uv run python -m hulun_guard calibration-drift
uv run python -m hulun_guard threat-model-check --json
uv run python -m hulun_guard compatibility --json
uv run python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify --json
uv run python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
uv run python -m hulun_guard adapter-matrix --json
uv run python -m hulun_guard collector smoke --json
uv run python -m hulun_guard collector smoke --managed --scan --init-if-missing --json
uv run python -m hulun_guard collector shutdown-check --json
uv run python -m hulun_guard collector status --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0 --json
uv run python -m hulun_guard collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
uv run python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json
uv run python -m hulun_guard collector service-template --output .hulun/collector-service --force --json
uv run python -m hulun_guard collector service-lifecycle --output .hulun/collector-service-lifecycle --force --json
'{"type":"tool_result","phase":"verify","summary":"pytest passed","result":"pass","action_key":"pytest","refs":["command:pytest"]}' | Set-Content -Encoding UTF8 trace-doctor-sample.jsonl
uv run python -m hulun_guard trace-doctor --file trace-doctor-sample.jsonl --format generic --json
uv run python -m hulun_guard schema-check --json
uv run python -m hulun_guard cleanup --json
uv run python -m hulun_guard benchmark --events 10000 --max-ms 1000
uv run python -m hulun_guard benchmark --suite real-world
uv run python -m build
uv run python scripts/generate_release_metadata.py --verify --json
uv run python scripts/verify_release_artifacts.py
uv run python -m hulun_guard release-verify --asset-dir dist --skip-attestation --json
```

GitHub must pass:

- CI matrix.
- CodeQL and Bandit.
- OpenSSF Scorecard.
- Release workflow with artifact provenance on tags.
- Dependabot has no unresolved critical updates.

Native service export connectors must be release-tested with public-safe mocked transports or loopback mock servers. CI and artifact smoke tests must not require real hosted service credentials.

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
10. Confirm `SHA256SUMS` and the CycloneDX SBOM are uploaded with the release.
11. Confirm release artifact smoke testing passed from a clean virtual environment.
12. Run `python -m hulun_guard release-verify vX.Y.Z --json` against the published release.
13. Create or update GitHub issues for unfinished maturity work.

See `docs/SUPPLY_CHAIN.md` for branch protection and release approval gates. See `docs/OPEN_SOURCE_GOVERNANCE.md` for Scorecard owner actions. See `docs/THREAT_MODEL.md` for the local-first security boundary.

## Artifact Policy

Do not release generated private state:

- `.hulun/`
- private trace files
- credentials
- local screenshots with private data
- customer or production logs
