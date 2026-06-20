# Security Policy

## Supported Versions

HulunGuard is pre-1.0. Security fixes target the latest released minor version only.

## Reporting A Vulnerability

Do not publish private vulnerability details in a public issue.

Report privately by opening a GitHub security advisory in the repository. Include:

- Affected command, adapter, or file path.
- Minimal reproduction steps.
- Impact and expected privilege boundary.
- Whether private conversation data, credentials, local files, or command execution are exposed.

## Security Baseline

Every release must pass:

- Unit tests.
- Built-in HulunGuard validation scenarios.
- Benchmark gate for expected scan latency.
- Retention cleanup dry-run gate.
- Ruff import/syntax gate.
- Bandit scan for Python source.
- CodeQL analysis on GitHub.
- OpenSSF Scorecard workflow.

## Data Handling

HulunGuard is local-first. Users must not commit `.hulun/`, private traces, credentials, customer data, or production conversation logs.

Runtime observations, conversation events, evidence records, and trace imports are redacted by default. Stored records include privacy metadata with `mode` and `retention_days`.

Adapters should store summaries, references, evidence IDs, cost/latency/token pressure, and stable action fingerprints by default. Full prompts, completions, tool arguments, tool results, and file contents require explicit `--include-sensitive` opt-in because they may contain private or regulated data.

Use `hulun cleanup --json` to preview expired local records and `hulun cleanup --apply` only in trusted local working copies. Cleanup refuses to delete paths outside the project `.hulun` directory or `HULUN_HOME/conversations`. See `docs/RETENTION.md`.
