# Onboarding

`onboard` is the first command for users who want to prove that a supported agent path works before importing real traces.

```powershell
python -m hulun_guard onboard --agent langgraph
python -m hulun_guard onboard --agent all --output .hulun/onboarding --force --json
```

For each selected agent, HulunGuard:

- generates a verified integration kit
- parses the public-safe sample trace through the selected adapter
- imports the sample into an isolated temporary sandbox
- scans the sandbox ledger
- returns the exact command to use with the user's real trace

The JSON report uses schema `hulun.onboarding.v1`.

## Output

Each agent item includes:

- `agent`: compatibility metadata
- `kit_dir`: generated kit directory
- `sample_trace`: public-safe sample trace path
- `verification`: adapter parse result
- `sandbox_import`: isolated import and scan result
- `next_steps.real_trace_command`: command for the user's real trace

## Safety

`onboard` does not import the sample into the user's project ledger. It only writes generated kit files to the requested output directory. Existing generated files are refused unless `--force` is used.

Do not put private prompts, completions, tool arguments, credentials, customer files, or production logs into onboarding samples.
