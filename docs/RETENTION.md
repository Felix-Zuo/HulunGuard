# Retention Cleanup

HulunGuard is local-first, but local runtime ledgers can still contain sensitive operational history. The cleanup command removes expired local runtime records and generated reports without touching source-controlled documentation.

Preview cleanup:

```powershell
python -m hulun_guard cleanup
python -m hulun_guard cleanup --json
```

Apply cleanup:

```powershell
python -m hulun_guard cleanup --apply
python -m hulun_guard cleanup --apply --write-report
```

The command defaults to dry-run. `--apply` is required before any record or report is removed.

## What Is Cleaned

Project ledger:

- expired `.hulun/state.json` events
- expired `.hulun/state.json` evidence records
- evidence references from criteria, steps, and retained events when the referenced evidence expires
- stale `last_scan` values

Conversation ledger:

- expired events in `HULUN_HOME/conversations/*.json`
- stale per-conversation `last_scan` values

Generated project reports:

- `.hulun/risk.json`
- `.hulun/risk_report.md`
- `.hulun/validation_report.json`
- `.hulun/validation_report.md`
- `.hulun/calibration_report.json`
- `.hulun/calibration_report.md`
- `.hulun/calibration_drift_report.json`
- `.hulun/calibration_drift_report.md`
- `.hulun/benchmark_report.json`
- `.hulun/real_world_benchmark_report.json`
- `.hulun/real_world_benchmark_report.md`
- `.hulun/verification_report.md`
- `.hulun/dashboard.html`
- `.hulun/resume.md`
- `.hulun/retention_cleanup_report.json`
- `.hulun/retention_cleanup_report.md`

Cleanup does not delete files under `docs/`, `research/`, source code, tests, release assets, or any path outside the HulunGuard state directories.

## Retention Rules

Events and evidence records are evaluated with their own `privacy.retention_days` value. If an older record does not have privacy metadata, cleanup uses `--default-retention-days`, which defaults to 30 days.

Generated JSON reports use their `generated_at` timestamp when present. Markdown and HTML reports use file modification time.

Examples:

```powershell
python -m hulun_guard cleanup --default-retention-days 14 --json
python -m hulun_guard cleanup --default-retention-days 14 --apply --write-report
python -m hulun_guard cleanup --skip-conversations --apply
python -m hulun_guard cleanup --skip-reports --apply
```

## Safety Boundary

Every delete and write operation is checked against an allowed base directory:

- project cleanup must stay inside `<project>/.hulun`
- conversation cleanup must stay inside `HULUN_HOME/conversations`
- project `.hulun` itself must be a real project-local directory, not a symlink

If a candidate path resolves outside its allowed base, cleanup reports a safety violation, returns exit code `2`, and leaves the external path untouched.

This protects against path traversal, symlink escape, and accidental deletion of source-controlled documentation.

## Maintainer Expectations

- Run `python -m hulun_guard cleanup --json` before release review.
- Use `--apply` only for trusted local working copies.
- Do not commit `.hulun/` cleanup reports unless a release policy explicitly asks for a public-safe excerpt.
- Keep cleanup tests for dry-run behavior, apply behavior, and outside-directory protection.
