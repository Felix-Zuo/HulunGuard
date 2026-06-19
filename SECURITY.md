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
- Ruff import/syntax gate.
- Bandit scan for Python source.
- CodeQL analysis on GitHub.
- OpenSSF Scorecard workflow.

## Data Handling

HulunGuard is local-first. Users must not commit `.hulun/`, private traces, credentials, customer data, or production conversation logs.

Adapters should store summaries, references, and evidence IDs by default. Full prompts, completions, tool arguments, and file contents should be opt-in because they may contain sensitive data.

