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
