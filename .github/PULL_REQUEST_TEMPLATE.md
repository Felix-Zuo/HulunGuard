## Summary

## Validation

- [ ] `python -m ruff check .`
- [ ] `python -m bandit -q -r src`
- [ ] `python -m compileall -q src tests`
- [ ] `python -m pytest -q`
- [ ] `python -m hulun_guard validate`
- [ ] `python -m hulun_guard calibrate`
- [ ] `python -m hulun_guard calibration-drift`
- [ ] `python -m hulun_guard threat-model-check --json`
- [ ] `python -m hulun_guard compatibility --json`
- [ ] `python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify --json`
- [ ] `python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json`
- [ ] `python -m hulun_guard adapter-matrix --json`
- [ ] `python -m hulun_guard collector smoke --json`
- [ ] `python -m hulun_guard collector smoke --managed --scan --init-if-missing --json`
- [ ] `python -m hulun_guard collector status --require-status-file --json`
- [ ] `python -m hulun_guard collector metrics --require-status-file`
- [ ] `python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json`
- [ ] `python -m hulun_guard collector service-template --output .hulun/collector-service --force --json`
- [ ] Batched ingestion smoke: enqueue, status, flush with `--init-if-missing`
- [ ] Public-safe `trace-doctor-sample.jsonl` created for trace diagnostics
- [ ] `python -m hulun_guard trace-doctor --file trace-doctor-sample.jsonl --format generic --json`
- [ ] `python -m hulun_guard schema-check --json`
- [ ] `python -m hulun_guard cleanup --json`
- [ ] `python -m hulun_guard benchmark --events 10000 --max-ms 1000`
- [ ] `python -m hulun_guard benchmark --suite real-world`

## Release / Supply Chain

- [ ] Version files updated when this changes release behavior
- [ ] Release workflow and provenance impact considered
- [ ] Branch protection requirements still satisfied

## Risk Notes

- Scoring changed: no / yes
- Adapter behavior changed: no / yes
- Security or privacy impact: no / yes
