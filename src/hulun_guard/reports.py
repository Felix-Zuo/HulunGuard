from __future__ import annotations

from html import escape
from typing import Any

from .util import status_counts, utc_now


def evidence_label(item: dict[str, Any]) -> str:
    evidence = item.get("evidence") or []
    return ", ".join(evidence) if evidence else "no evidence"


def humanize_key(value: str) -> str:
    return value.replace("_", " ").title()


def build_resume_markdown(state: dict[str, Any]) -> str:
    criteria = state.get("criteria") or state.get("success_criteria") or []
    active_steps = [
        step
        for step in state.get("steps", [])
        if step.get("status") in {"pending", "in_progress", "blocked"}
    ]
    lines: list[str] = [
        "# HulunGuard Resume Packet",
        "",
        f"Updated: {state.get('updated_at', '')}",
        "",
        "## Objective",
        state.get("objective", ""),
        "",
        "## Success Criteria",
    ]
    for item in criteria:
        lines.append(f"- {item['id']} [{item.get('status', 'pending')}]: {item.get('text', '')} ({evidence_label(item)})")
    if not criteria:
        lines.append("- None")

    lines.extend(["", "## Active Steps"])
    if active_steps:
        for step in active_steps:
            lines.append(f"- {step['id']} [{step.get('status', 'pending')}]: {step.get('text', '')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Latest Evidence"])
    for evidence in state.get("evidence", [])[-8:]:
        detail = evidence.get("path") or evidence.get("url") or evidence.get("command") or ""
        lines.append(f"- {evidence['id']} [{evidence.get('kind', '')}]: {evidence.get('summary', '')} {detail}".rstrip())
    if not state.get("evidence"):
        lines.append("- None")

    lines.extend(["", "## Latest Checkpoint"])
    if state.get("checkpoints"):
        checkpoint = state["checkpoints"][-1]
        lines.append(f"- {checkpoint['id']}: {checkpoint.get('summary', '')}")
        if checkpoint.get("next_action"):
            lines.append(f"- Next action: {checkpoint['next_action']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Risks"])
    for risk in state.get("risks", [])[-5:]:
        lines.append(f"- {risk['id']}: {risk.get('text', '')}")
    if not state.get("risks"):
        lines.append("- None")

    last_scan = state.get("last_scan")
    if last_scan:
        lines.extend(
            [
                "",
                "## Last HulunGauge",
                f"- Score: {last_scan.get('score')} ({last_scan.get('band')})",
                f"- Required action: {last_scan.get('required_action')}",
            ]
        )
    return "\n".join(lines) + "\n"


def build_verify_markdown(result: dict[str, Any]) -> str:
    lines = ["# HulunGuard Verification Report", "", f"Updated: {utc_now()}", ""]
    lines.extend(["## Result", "PASS" if result["pass"] else "FAIL", ""])
    lines.append("## Failures")
    lines.extend([f"- {failure}" for failure in result["failures"]] or ["- None"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {warning}" for warning in result["warnings"]] or ["- None"])
    if result.get("risk"):
        risk = result["risk"]
        lines.extend(["", "## HulunGauge"])
        lines.append(f"- Score: {risk.get('score')} ({risk.get('band')})")
        lines.append(f"- Slop index: {risk.get('slop_index', risk.get('score'))}")
        lines.append(f"- Required action: {risk.get('required_action')}")
    return "\n".join(lines) + "\n"


def build_dashboard_html(state: dict[str, Any], risk: dict[str, Any]) -> str:
    criteria = state.get("criteria") or state.get("success_criteria") or []
    score = int(risk.get("score", 0))
    band = str(risk.get("band", "green"))
    color = {"green": "#1f9d55", "yellow": "#c68612", "red": "#c2410c"}.get(band, "#525252")
    reason_items = "\n".join(f"<li>{escape(reason)}</li>" for reason in risk.get("reasons", [])) or "<li>No risk reasons.</li>"
    component_items = "\n".join(
        f"<li>{escape(humanize_key(name))}: {value}"
        f" / {risk.get('weights', {}).get(name, '')}</li>"
        for name, value in risk.get("components", {}).items()
    )
    criterion_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item.get('id', ''))}</td>"
        f"<td>{escape(item.get('status', 'pending'))}</td>"
        f"<td>{escape(item.get('text', ''))}</td>"
        f"<td>{escape(evidence_label(item))}</td>"
        "</tr>"
        for item in criteria
    )
    evidence_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item.get('id', ''))}</td>"
        f"<td>{escape(item.get('kind', ''))}</td>"
        f"<td>{escape(item.get('summary', ''))}</td>"
        f"<td>{escape(item.get('path') or item.get('url') or item.get('command') or '')}</td>"
        "</tr>"
        for item in state.get("evidence", [])[-10:]
    )
    counts = status_counts(criteria)
    generated = utc_now()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>HulunGauge</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: #f7f7f4;
      color: #1d1d1b;
    }}
    body {{ margin: 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; border-bottom: 1px solid #d9d6cc; padding-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .subtitle {{ margin-top: 8px; color: #57534e; max-width: 760px; line-height: 1.5; }}
    .score {{ min-width: 220px; text-align: right; }}
    .score strong {{ font-size: 46px; color: {color}; }}
    .band {{ text-transform: uppercase; font-weight: 700; color: {color}; }}
    .gauge {{ height: 18px; background: #e7e5dc; border-radius: 4px; overflow: hidden; margin: 22px 0 8px; }}
    .fill {{ height: 100%; width: {score}%; background: {color}; transition: width .2s ease; }}
    .ticks {{ display: flex; justify-content: space-between; color: #78716c; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr); gap: 24px; }}
    .panel {{ border: 1px solid #d9d6cc; background: #fffdfa; border-radius: 8px; padding: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }}
    .metric {{ background: #efede6; border-radius: 6px; padding: 12px; }}
    .metric b {{ display: block; font-size: 24px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fffdfa; border: 1px solid #d9d6cc; }}
    th, td {{ text-align: left; border-bottom: 1px solid #ebe8df; padding: 10px; vertical-align: top; }}
    th {{ background: #efede6; font-size: 13px; }}
    td {{ font-size: 13px; line-height: 1.4; }}
    ul {{ margin: 0; padding-left: 20px; line-height: 1.55; }}
    code {{ background: #efede6; padding: 2px 5px; border-radius: 4px; }}
    @media (max-width: 860px) {{
      header, .grid {{ display: block; }}
      .score {{ text-align: left; margin-top: 18px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      main {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>糊弄 / HulunGauge</h1>
        <p class="subtitle">{escape(state.get("objective", ""))}</p>
      </div>
      <div class="score">
        <div class="band">{escape(band)}</div>
        <strong>{score}</strong><span>/100</span>
      </div>
    </header>
    <div class="gauge" aria-label="HulunGuard risk score"><div class="fill"></div></div>
    <div class="ticks"><span>0 continue</span><span>35 calibrate</span><span>66 block final</span><span>100</span></div>
    <div class="metrics">
      <div class="metric"><b>{counts.get("done", 0)}</b>criteria done</div>
      <div class="metric"><b>{counts.get("pending", 0)}</b>criteria pending</div>
      <div class="metric"><b>{len(state.get("evidence", []))}</b>evidence items</div>
      <div class="metric"><b>{len(state.get("events", []))}</b>events</div>
    </div>
    <div class="grid">
      <section class="panel">
        <h2>Risk Reasons</h2>
        <ul>{reason_items}</ul>
        <h2>Required Action</h2>
        <p><code>{escape(str(risk.get("required_action", "continue")))}</code></p>
      </section>
      <section class="panel">
        <h2>HulunIndex Components</h2>
        <ul>{component_items}</ul>
      </section>
    </div>
    <h2>Success Criteria</h2>
    <table><thead><tr><th>ID</th><th>Status</th><th>Criterion</th><th>Evidence</th></tr></thead><tbody>{criterion_rows}</tbody></table>
    <h2>Latest Evidence</h2>
    <table><thead><tr><th>ID</th><th>Kind</th><th>Summary</th><th>Reference</th></tr></thead><tbody>{evidence_rows}</tbody></table>
    <p class="subtitle">Generated at {escape(generated)}. Open this file again after running <code>hulun scan</code> or <code>hulun dashboard</code>.</p>
  </main>
</body>
</html>
"""


def build_board_html(monitors: list[dict[str, Any]], groups: dict[str, dict[str, Any]]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(item.get('id', ''))}</td>"
        f"<td>{escape(item.get('conversation', ''))}</td>"
        f"<td>{escape(item.get('group', ''))}</td>"
        f"<td><span class='pill {escape(item.get('band', 'green'))}'>{int(item.get('score', 0))} {escape(item.get('band', 'green'))}</span></td>"
        f"<td>{escape(item.get('status', 'active'))}</td>"
        f"<td>{escape((item.get('reasons') or [''])[0])}</td>"
        f"<td>{escape(item.get('updated_at', ''))}</td>"
        "</tr>"
        for item in monitors
    )
    group_cards = "\n".join(
        f"<div class='card'><div class='label'>{escape(name)}</div><div class='big {escape(data['band'])}'>{data['score']}</div><div>{escape(data['band'])} · {data['count']} monitors</div></div>"
        for name, data in groups.items()
    )
    if not group_cards:
        group_cards = "<div class='card'><div class='label'>No active groups</div><div class='big green'>0</div><div>Open a monitor first.</div></div>"
    generated = utc_now()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>HulunGuard Board</title>
  <style>
    body {{ margin: 0; font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif; background: #f7f7f4; color: #1d1d1b; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    .sub {{ color: #57534e; margin-bottom: 22px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .card {{ background: #fffdfa; border: 1px solid #d9d6cc; border-radius: 8px; padding: 16px; }}
    .label {{ color: #57534e; margin-bottom: 8px; }}
    .big {{ font-size: 42px; font-weight: 800; }}
    .green {{ color: #1f9d55; }}
    .yellow {{ color: #c68612; }}
    .red {{ color: #c2410c; }}
    table {{ width: 100%; border-collapse: collapse; background: #fffdfa; border: 1px solid #d9d6cc; }}
    th, td {{ text-align: left; border-bottom: 1px solid #ebe8df; padding: 10px; vertical-align: top; font-size: 13px; }}
    th {{ background: #efede6; }}
    .pill {{ display: inline-block; min-width: 84px; font-weight: 700; }}
    code {{ background: #efede6; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
<main>
  <h1>糊弄 / HulunGuard Board</h1>
  <div class="sub">All active conversation monitors and project-level HulunGauge scores. Generated {escape(generated)}.</div>
  <section class="cards">{group_cards}</section>
  <table>
    <thead><tr><th>ID</th><th>Conversation</th><th>Group</th><th>Risk</th><th>Status</th><th>Top Reason</th><th>Updated</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="sub">Open a widget with <code>hulun open --conversation "name" --group "project" --widget</code>.</p>
</main>
</body>
</html>
"""
