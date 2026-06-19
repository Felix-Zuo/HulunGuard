## Summary

## Validation

- [ ] `python -m ruff check .`
- [ ] `python -m bandit -q -r src`
- [ ] `python -m compileall -q src tests`
- [ ] `python -m pytest -q`
- [ ] `python -m hulun_guard validate`
- [ ] `python -m hulun_guard benchmark --events 10000 --max-ms 1000`

## Risk Notes

- Scoring changed: no / yes
- Adapter behavior changed: no / yes
- Security or privacy impact: no / yes

