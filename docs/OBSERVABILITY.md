# Observability

HulunGuard exposes collector health and HulunIndex risk state through local JSON status, Prometheus metrics, and generated Prometheus alerting rules.

## Collector Status

Use status when a supervisor, CI job, or support script needs a structured local health report:

```powershell
python -m hulun_guard collector status --require-status-file --queue-pending-threshold 100 --json
```

The command reads `.hulun/ingest_queue.jsonl`, `.hulun/ingest_dead_letter.jsonl`, `.hulun/collector_status.json`, and `.hulun/risk.json`. It does not start a server.

The JSON payload includes `diagnostics.summary` and grouped diagnostics for queue, status freshness, runtime lifecycle, dead letters, managed flush, and latest HulunIndex risk. Diagnostics contain bounded counters, state names, error codes, messages, and action hints. They do not include local paths, tokens, or trace contents.

## Prometheus Metrics

Use the CLI for offline checks:

```powershell
python -m hulun_guard collector metrics --require-status-file --queue-pending-threshold 100 --dead-letter-threshold 0
```

Use the HTTP endpoint when the collector is running:

```text
GET http://127.0.0.1:4318/metrics
```

Metrics include queue depth, queue bytes, parse errors, dead-letter records, status-file presence and age, managed flush counters, runtime error state, runtime uptime, one-hot runtime lifecycle state, latest HulunIndex score, blocked state, and one-hot risk band gauges. Local filesystem paths are not exported as metric labels.

If the collector is started with `--token`, `/metrics` requires `Authorization: Bearer <token>` or `X-Hulun-Token`.

## Alert Rules

Generate Prometheus alerting rules:

```powershell
python -m hulun_guard collector alert-rules --output .hulun/collector-alerts --force --json
```

The generated `hulunguard-collector.rules.yml` file follows the Prometheus rule-file shape documented by Prometheus: a YAML document with `groups` and `rules`. See the Prometheus docs for [recording rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/) and [alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).

Check generated rules before deployment:

```text
promtool check rules .hulun/collector-alerts/hulunguard-collector.rules.yml
```

Default alerts cover:

- collector operations gate failure
- managed runtime error
- missing or stale managed status
- dead-lettered records
- queue backlog
- blocked HulunIndex state
- red HulunIndex score
- advisory collector warnings

The generator writes files only. It does not install Prometheus configuration, restart services, modify Alertmanager routing, or embed tokens.

## Thresholds

Tune alert sensitivity at generation time:

```powershell
python -m hulun_guard collector alert-rules `
  --queue-pending-threshold 200 `
  --status-stale-seconds 180 `
  --risk-red-threshold 70 `
  --dead-letter-threshold 0 `
  --force
```

Regenerate the files after changing thresholds and rerun `promtool check rules`.

