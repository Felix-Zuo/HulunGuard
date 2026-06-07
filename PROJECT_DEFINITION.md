# 糊弄 / HulunGuard

## Name

中文名：糊弄  
英文名：HulunGuard  
CLI：`hulun`  
核心仪表：HulunGauge  
一句话：Catch drift before confidence.

`HulunGuard` 是一个通用的智能体可靠性层，用于在长线任务中实时监控“糊弄风险”：当智能体开始目标漂移、证据不足、上下文断裂、空转总结、工具失败后继续下结论时，它不等最终失败才追责，而是在运行中显示风险、触发校准、阻止无证据完成声明。

## Why This Name

`SlopGuard`、`NoSlop`、`Slopometer` 已经被多个代码质量、写作检测或 agent rule 项目使用。`HulunGuard` 保留中文“糊弄”的语义，但避免和现有英文产品强撞名。

命名层级：

- `糊弄 / HulunGuard`：完整项目和协议。
- `HulunGauge`：可视化风险进度条。
- `hulun`：命令行工具。
- `Hulun Skill`：可移植 skill 包，适配 Codex、Claude Code、OpenClaw、Cursor、Windsurf、OpenHands 等 agent 环境。

## Product Definition

HulunGuard is a proof-first reliability layer for long-running AI agents.

它不是 AI detector，也不是普通 hallucination checker。它判断的不是“内容像不像 AI 写的”，而是“当前 agent 是否正在失去可验证的任务执行能力”。

## Core User Problem

长线任务里，智能体常常不是一开始就失败，而是逐步进入失真状态：

- 目标从“完成项目”变成“解释项目应该怎么完成”。
- 计划越来越多，证据越来越少。
- 上下文压缩后丢掉验收标准。
- 工具失败后仍然给出完成结论。
- 多轮都在总结，但没有新文件、新测试、新来源、新 artifact。
- 最终回复看起来完整，却缺少可审计证明。

HulunGuard 的目标是把这种隐性失真变成可观测、可阈值控制、可恢复的工程信号。

## Design Thesis

真正有用的“糊弄进度条”不能只看文本风格。它必须组合 5 类信号：

1. Intent Fidelity：当前行为是否仍贴合最初目标和验收标准。
2. Evidence Coverage：完成声明是否被证据支撑。
3. Execution Freshness：最近是否真的推进了文件、命令、来源、测试或 artifact。
4. State Continuity：checkpoint、resume packet、上下文恢复是否健康。
5. Failure Honesty：工具失败、阻塞、假设不确定时是否被明确记录，而不是被最终话术掩盖。

## Architecture

```text
Agent Runtime
  |
  | event: plan, tool_call, tool_result, file_change, source, test, final_attempt
  v
Hulun Event Collector
  |
  +--> Durable Run Ledger       .hulun/state.json
  +--> Evidence Store           .hulun/evidence/*
  +--> Trace Adapter            Langfuse / Phoenix / LangSmith / OpenTelemetry
  +--> Memory Adapter           Cognee / Graphiti / Mem0 / Letta
  |
  v
Risk Engine
  |
  +--> evidence_gap_score
  +--> intent_drift_score
  +--> stagnation_score
  +--> context_decay_score
  +--> unhandled_failure_score
  +--> final_claim_risk_score
  |
  v
HulunGauge UI
  |
  +--> green: continue
  +--> yellow: calibrate soon
  +--> red: block final, require recovery
```

## Core Data Model

```json
{
  "objective": "what the user actually wants",
  "criteria": [
    {
      "id": "C1",
      "text": "observable definition of done",
      "status": "pending|done|blocked",
      "evidence": ["E1"]
    }
  ],
  "events": [
    {
      "id": "EV1",
      "type": "tool_result|file_change|source|test|checkpoint|final_attempt",
      "summary": "what happened",
      "result": "pass|fail|unknown",
      "refs": ["path or url"],
      "time": "iso timestamp"
    }
  ],
  "risk": {
    "score": 0,
    "band": "green|yellow|red",
    "reasons": [],
    "required_action": "continue|checkpoint|recover|ask_user|block_final"
  }
}
```

## Risk Scoring

Default score: 0-100, higher means more likely to drift into useless or unverifiable output.

| Signal | Weight | Meaning |
| --- | ---: | --- |
| Evidence gap | 25 | Criteria or claims lack attached evidence |
| Unfinished criteria | 20 | Required outcomes still pending or blocked |
| Stagnation | 15 | Repeated summaries/plans without new execution evidence |
| Unhandled failures | 15 | Failed tools/tests/sources not resolved or disclosed |
| Context decay | 10 | Checkpoint stale, resume packet missing, compaction likely |
| Intent drift | 10 | Current action no longer matches objective/criteria |
| Uncertainty inflation | 5 | More hedging language without verification |

Bands:

- 0-35 green: continue.
- 36-65 yellow: checkpoint or recalibrate.
- 66-100 red: block final; recover state before continuing.

## Intervention Policy

HulunGuard 不应该频繁打断正常工作。只在下面情况硬拦截：

- Agent 准备发送 final，但 verify 或 risk scan 不通过。
- 风险超过用户设置阈值。
- 工具失败后 agent 仍准备声称完成。
- 上下文恢复信息缺失，但任务仍是长线/高风险。
- 关键验收标准没有任何证据。

红线提示模板：

```text
HulunGuard: 当前继续给结论会有高糊弄风险。

风险：72 / 100
原因：
- C2 没有证据
- S4 仍是 in_progress
- 最近 5 个事件没有新增 artifact 或测试

我需要先执行校准：
1. 读取 resume packet
2. 补齐 C2 的证据
3. 重新运行 verify
```

## Differentiation

HulunGuard 和现有工具的区别：

- 不只做 LLM trace，而是做 state transition observability。
- 不只评估最终文本，而是持续评估任务执行过程。
- 不只检查 hallucination，而是检查 proof gap、context decay、intent drift。
- 不绑定单一平台，可作为 skill、CLI、MCP、SDK、browser dashboard 使用。
- 本地优先，证据和状态默认放在项目目录内，便于审计和迁移。

## Inspirations To Combine

- LangGraph: checkpoint, thread state, replay, human-in-loop.
- Temporal: durable execution, retry, signals, timers.
- Letta: stateful agents, persisted messages, memory hierarchy.
- Cognee / Graphiti / Mem0: long-term memory and knowledge graph recall.
- SWE-agent / OpenHands: trajectory and action-observation audit logs.
- Langfuse / Phoenix / LangSmith / Braintrust: traces, evals, observability dashboards.
- Guardrails / schema validators: output and tool-boundary validation.
- NoSlop: repository-local assertions and attestation workflow.

## First Product Shape

Phase 1: Local-first CLI and skill

- `hulun init`
- `hulun event`
- `hulun evidence`
- `hulun checkpoint`
- `hulun scan`
- `hulun verify`
- `hulun dashboard`

Phase 2: Universal adapters

- Codex skill adapter.
- Claude Code skill adapter.
- OpenClaw hook adapter.
- MCP server.
- OpenTelemetry exporter.
- Langfuse/Phoenix trace exporter.

Phase 3: Advanced runtime

- Intent drift embedding scorer.
- Claim-to-evidence extraction.
- Tool failure classifier.
- Stagnation detector.
- Automatic calibration prompts.
- Human approval and attestation ledger.

## Success Criteria

HulunGuard is useful only if it can prove these outcomes:

- It catches false-completion attempts before final answer.
- It makes long-task resume faster after context compaction.
- It reduces repeated user corrections like “你又在糊弄”.
- It produces audit artifacts that another agent or human can inspect.
- It works without requiring a hosted SaaS dependency.

## Current Implementation

Version 0.1 now has the local-first core:

- `.hulun/state.json` durable state.
- `.hulun/resume.md` resume packet.
- `hulun scan` risk engine.
- `.hulun/risk.json` and `.hulun/risk_report.md`.
- `hulun verify` final gate.
- `.hulun/dashboard.html` with HulunGauge.
- Codex skill adapter retained as one adapter, not the whole product.

## Immediate Next Step

Build the first universal adapter layer:

- OpenClaw hook adapter.
- MCP server wrapper.
- Optional Langfuse/Phoenix/OpenTelemetry exporter.
- Better intent drift scoring with embeddings when an embedding provider is configured.
