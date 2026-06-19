# Contributing

## Product Bar

HulunGuard is a reliability monitor, not a text-style detector. Contributions must improve one of these outcomes:

- Detect unsupported completion claims earlier.
- Reduce false positives on evidence-backed work.
- Improve adapter reliability and portability.
- Improve auditability, privacy, security, or release quality.
- Make setup and daily use simpler for agent users.

## Development Setup

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m hulun_guard validate
python -m hulun_guard benchmark --events 10000 --max-ms 1000
```

## Required Checks

Before a pull request:

```powershell
python -m ruff check .
python -m bandit -q -r src
python -m compileall -q src tests
python -m pytest -q
python -m hulun_guard validate
python -m hulun_guard benchmark --events 10000 --max-ms 1000
```

## Scoring Changes

Any change to HulunIndex or conversation scoring must include:

- A test showing the intended risk transition.
- A note in `CHANGELOG.md`.
- An explanation of false-positive and false-negative tradeoffs.

Do not relax validation to make a release pass. Update scenario expectations only when the scoring behavior is intentionally changed and tested.

