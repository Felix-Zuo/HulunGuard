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
python scripts/verify_release_artifacts.py
python scripts/generate_release_metadata.py --verify --json
```

Release-specific steps are maintained in `RELEASING.md`.

## Community Standards

All participation is covered by `CODE_OF_CONDUCT.md`. Use the issue forms for bugs, adapter gaps, and feature requests. Reports and examples must stay public-safe: do not post private prompts, credentials, customer data, production logs, or sensitive traces.

## Scoring Changes

Any change to HulunIndex or conversation scoring must include:

- A test showing the intended risk transition.
- A note in `CHANGELOG.md`.
- An explanation of false-positive and false-negative tradeoffs.

Do not relax validation to make a release pass. Update scenario expectations only when the scoring behavior is intentionally changed and tested.
