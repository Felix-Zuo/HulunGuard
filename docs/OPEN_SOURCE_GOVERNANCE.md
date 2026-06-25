# Open Source Governance

HulunGuard treats OpenSSF Scorecard as a release signal and separates code-remediable findings from repository-owner controls.

## Automated Controls

- GitHub Actions are pinned by immutable commit SHA. Version comments next to each SHA record the reviewed tag.
- CI, Security, Release, and Scorecard use least-privilege workflow permissions. Write permissions are scoped to the job that needs them.
- CI and Release install developer dependencies through `uv sync --locked --extra dev`; the lock file records package versions, sources, and hashes.
- Release artifacts are built from tags, include `SHA256SUMS`, include a CycloneDX SBOM, and receive GitHub build provenance attestations.
- Security policy entrypoints are present in `SECURITY.md`, `.github/SECURITY.md`, and README so users can find private reporting paths.

## Repository Owner Controls

Some Scorecard checks require repository settings or external services and cannot be completed by a source-only patch.

The repository owner should keep these controls enabled:

- Protect `main`.
- Require pull requests before merge.
- Require at least one approving review.
- Dismiss stale approvals when new commits are pushed.
- Require conversation resolution before merge.
- Require status checks before merge:
  - `CI / Python 3.10`
  - `CI / Python 3.11`
  - `CI / Python 3.12`
  - `CI / Python 3.13`
  - `Security / bandit`
  - `Security / codeql`
  - `OpenSSF Scorecard / scorecard`
- Disallow force pushes and branch deletion.

## Scorecard Disposition

| Check | Status | Evidence or owner action |
| --- | --- | --- |
| PinnedDependencies | Code-remediated | Actions use immutable SHAs; CI dependencies are locked in `uv.lock`. |
| TokenPermissions | Code-remediated | Workflows default to read-only; write scopes are job-level. |
| SecurityPolicy | Code-remediated | `SECURITY.md`, `.github/SECURITY.md`, README, and threat model link the private reporting path. |
| BranchProtection | Owner setting | Enable protection on `main` with the checklist above. |
| CodeReview | Owner/process signal | Require one approval and keep using PRs for all changes. Score improves as approved changesets accumulate. |
| Maintained | Time-based signal | Repository age is external to code. Keep releases, issues, and security scans active. |
| Fuzzing | Roadmap signal | Add a recognized fuzzing integration when parser and adapter fuzz targets are stable. |
| CIIBestPractices | External badge | Register the project with the OpenSSF Best Practices badge service when public governance metadata is ready. |

## Release Rule

Do not close a governance maturity issue unless:

- Code-remediable Scorecard findings have a source change or explicit reason they cannot be changed from source.
- Owner-setting findings have a concrete owner action and status.
- GitHub CI, Security, Scorecard, and Release checks pass on the release commit.
