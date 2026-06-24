# Integration Kits

Integration kits are first-run onboarding packages for agent runtimes and trace formats. They turn the compatibility matrix into files a user can run immediately.

For the simplest first-run check, use `onboard`. It generates the kit, verifies the sample trace, imports it in an isolated sandbox, and prints the real next command:

```powershell
python -m hulun_guard onboard --agent langgraph
python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
```

Generate one kit:

```powershell
python -m hulun_guard integration-kit --agent langgraph --verify
python -m hulun_guard integration-kit --agent openai-agents-sdk --verify
```

Generate and verify every supported kit:

```powershell
python -m hulun_guard integration-kit --agent all --output .hulun/integration-kits --force --verify
```

Each kit contains:

- `README.md`
- `hulun_integration.json`
- `run_ingest.ps1`
- `run_ingest.sh`
- a public-safe sample trace for the selected adapter

The generated runner commands include `ingest --init-if-missing`, so a fresh project can import a sample without running `init` first. The `--verify` flag parses the generated sample trace through the same adapter used by `ingest`. It does not persist the sample into the project ledger.

## Supported Agents

The command supports the agent ids reported by:

```powershell
python -m hulun_guard compatibility --json
```

Use `--agent all` for the release gate and `--agent <id>` for a single onboarding package.

## Safety

- Existing generated files are not overwritten unless `--force` is used.
- The samples are synthetic and public-safe.
- Do not commit private prompts, completions, tool arguments, credentials, customer files, or production logs.
- Standards-path kits still require the user to export OTLP JSON or OpenInference-compatible spans from their runtime.
