# HulunGuard Release Policy

Every version of HulunGuard must be committed and pushed to GitHub.

## Required Checks

Run these before every version push:

```powershell
python -m pytest -q
python .\hulun.py validate
```

## Version Steps

1. Update `pyproject.toml`.
2. Update `src/hulun_guard/__init__.py`.
3. Update docs for new commands, parameters, or product meaning.
4. Run tests and validation.
5. Commit with a versioned message.
6. Push to `origin/main`.

## Current Policy

- Patch versions: bug fixes, docs, small scoring fixes.
- Minor versions: new CLI commands, adapters, validation suites, scoring dimensions.
- Major versions: incompatible state schema or CLI changes.
