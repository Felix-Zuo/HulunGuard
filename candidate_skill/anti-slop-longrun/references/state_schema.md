# HulunGuard State Schema

The CLI stores canonical task state in `<project-root>/.hulun/state.json`.

## Top-Level Fields

- `schema`: Schema id, currently `hulun.state.v1`.
- `created_at`, `updated_at`: UTC ISO timestamps.
- `objective`: The current user goal.
- `threshold`: HulunGauge block threshold, default `66`.
- `criteria`: Observable definitions of done. Each item has `id`, `text`, `status`, and `evidence`.
- `constraints`: User or environment constraints that must not be violated.
- `assumptions`: Assumptions that should be revisited when evidence contradicts them.
- `steps`: Current work plan. Each item has `id`, `text`, `status`, and `evidence`.
- `evidence`: Append-only evidence ledger. Each item has `id`, `kind`, `summary`, optional `command`, `path`, `url`, `sha256`, and `notes`.
- `events`: Action and observation stream used by HulunGauge.
- `risks`: Known blockers or unresolved doubts.
- `decisions`: Important implementation or research choices.
- `checkpoints`: Compact phase summaries used for resume.
- `last_scan`: Latest HulunGauge result.
- `last_verify`: Latest final-gate result.

## Status Values

Use `pending`, `in_progress`, `done`, `blocked`, or `dropped`.

## Evidence Rules

A completed success criterion should cite at least one evidence ID. A completed step should cite evidence unless it is purely administrative.

For local files, HulunGuard stores a SHA-256 hash when the file exists. For external sources, store the URL and a short summary. For commands, store the exact command and observed result summary.

## Generated Files

- `.hulun/resume.md`: Compact handoff packet.
- `.hulun/risk.json`: Structured HulunGauge score.
- `.hulun/risk_report.md`: Human-readable score report.
- `.hulun/verification_report.md`: Final gate result.
- `.hulun/dashboard.html`: Local visual risk dashboard.
