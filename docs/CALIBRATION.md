# Calibration Evidence

HulunGuard calibration is the release gate for HulunIndex scoring behavior. It checks labeled trajectories against expected risk components and fails when precision, recall, support coverage, or trajectory matches regress.

## Latest Snapshot

- Version candidate: 0.19.0
- Command: `python -m hulun_guard calibrate`
- Dataset size: 100 labeled trajectories
- Gate: pass
- Private logs in repository: none
- Drift baseline: `docs/calibration_baseline.json`

## Label Coverage

| Label | Count |
| --- | ---: |
| healthy | 10 |
| unsupported-final | 10 |
| failure-masking | 15 |
| retry-loop | 15 |
| context-decay | 10 |
| polish-without-progress | 10 |
| cost-pressure | 15 |
| uncertainty | 15 |

## Source Coverage

| Source class | Count |
| --- | ---: |
| curated-public-safe | 80 |
| external-public-swe-agent-trajectory | 5 |
| external-public-openhands-event-log | 5 |
| external-public-opentelemetry-genai-trace | 5 |
| external-public-openinference-trace | 5 |

## Workflow Coverage

| Workflow class | Count |
| --- | ---: |
| calibration | 80 |
| coding | 5 |
| ops | 5 |
| artifact | 5 |
| research | 5 |

## Redaction Coverage

| Redaction status | Count |
| --- | ---: |
| no-private-content | 80 |
| public-schema-derived-no-private-content | 20 |

## Public Source References

- [SWE-agent trajectory documentation](https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md)
- [OpenHands event architecture](https://docs.openhands.dev/sdk/arch/events)
- [OpenTelemetry GenAI observability](https://opentelemetry.io/blog/2026/genai-observability/)
- [OpenInference trace specification](https://github.com/Arize-ai/openinference/blob/main/spec/traces.md)

These references are used for public event-shape coverage only. HulunGuard does not vendor their datasets and does not publish private user or agent transcripts.

## Release Gate

For release review, run:

```powershell
python -m hulun_guard validate
python -m hulun_guard calibrate
python -m hulun_guard calibration-drift
python -m pytest -q
```

`calibrate` writes `.hulun/calibration_report.json` and `.hulun/calibration_report.md` with component support, precision, recall, false-positive rate, false-negative rate, source coverage, workflow coverage, redaction status, and source URIs.

`calibration-drift` compares current calibration against `docs/calibration_baseline.json`. It fails on lower dataset size, label coverage, source coverage, workflow coverage, redaction coverage, source URI coverage, component support, precision, or recall. Use `--rationale` only when an intentional regression has been reviewed and accepted.
