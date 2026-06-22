# Supply Chain And Release Controls

HulunGuard releases must be traceable from source commit to published artifact.

## Provenance

Tag releases run `.github/workflows/release.yml`.

The workflow:

- Builds wheel and sdist from the tagged commit.
- Uploads `dist/*` as workflow artifacts.
- Generates GitHub build provenance attestations for `dist/*` with `actions/attest`.
- Generates `SHA256SUMS` and a CycloneDX 1.6 SBOM for the release artifacts.
- Uploads the same files and release metadata to the GitHub Release.

Required workflow permissions:

- `contents: write` for release assets.
- `id-token: write` for OIDC signing.
- `attestations: write` for artifact attestations.
- `artifact-metadata: write` for artifact metadata records.

Published releases include:

- `hulun_guard-<version>-py3-none-any.whl`
- `hulun_guard-<version>.tar.gz`
- `hulun_guard-<version>-sbom.cdx.json`
- `SHA256SUMS`

Consumers can verify checksums after downloading a release:

```bash
sha256sum -c SHA256SUMS
```

HulunGuard includes an installed release verifier that downloads the release, checks `SHA256SUMS`, validates the SBOM artifact hashes, and verifies GitHub attestations:

```bash
python -m hulun_guard release-verify v0.29.0 --json
```

For offline verification of already downloaded assets:

```bash
python -m hulun_guard release-verify v0.29.0 --asset-dir ./release-assets --skip-attestation --json
```

Consumers can verify build provenance with GitHub's attestation verification flow:

```bash
gh attestation verify hulun_guard-<version>-py3-none-any.whl -R Felix-Zuo/HulunGuard
gh attestation verify hulun_guard-<version>.tar.gz -R Felix-Zuo/HulunGuard
```

The SBOM follows CycloneDX JSON 1.6 and records the package, release artifacts, SHA-256 hashes, license, public repository, documentation, and release references.

## Branch Protection Checklist

The `main` branch should require:

- Pull request before merge.
- At least one approving review.
- Dismiss stale approvals when new commits are pushed.
- Require conversation resolution before merge.
- Require status checks:
  - `CI / Python 3.10`
  - `CI / Python 3.11`
  - `CI / Python 3.12`
  - `CI / Python 3.13`
  - `Security / bandit`
  - `Security / codeql`
  - `OpenSSF Scorecard / scorecard`
- Require branches to be up to date before merge.
- Restrict force pushes and branch deletion.
- Require signed commits when repository policy allows it.

## Release Approval Gate

Before pushing a tag:

1. Local gates pass: Ruff, Bandit, compileall, pytest, validation, calibration, calibration drift, threat model check, agent compatibility, integration kit verification, onboarding verification, adapter matrix, schema compatibility, retention cleanup dry-run, scan benchmark, real-world benchmark, and build.
2. `CHANGELOG.md`, `pyproject.toml`, and `src/hulun_guard/__init__.py` agree on the release version.
3. The release commit is on `main`.
4. The release tag points at the reviewed commit.
5. GitHub CI, Security, Scorecard, and Release workflows pass.
6. Release assets have provenance attestations.
7. Release assets include `SHA256SUMS` and a CycloneDX SBOM.
8. The published tag passes `python -m hulun_guard release-verify <tag> --json`.
9. Open maturity issues are updated or closed with evidence.

## Release Asset Policy

Do not publish:

- `.hulun/` state.
- Private traces.
- Credentials or tokens.
- Customer logs.
- Screenshots containing private data.
- Local machine paths unless they are intentionally part of a public example.

The threat model for local data, adapters, retention, and release assets is documented in `docs/THREAT_MODEL.md`.
