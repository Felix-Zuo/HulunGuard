# HulunGuard 糊弄指数研究札记

日期: 2026-06-08

## 摘要

智能体开始“糊弄”不是一个文风问题, 也不是单纯的幻觉问题。它更像一种长任务执行可靠性退化: 智能体仍然能生成流畅、完整、看似负责的回答, 但它的完成声明已经开始脱离可验证的任务状态。

HulunGuard 的核心判断对象不是“这段话像不像 AI 写的”, 而是:

> 当前智能体是否仍然具备可审计、可恢复、可验证的任务执行能力。

因此, 糊弄指数应该监控的是状态和证据, 而不是语气。一个智能体只要开始用叙事填补证据缺口, 用总结替代推进, 用计划包装未完成项, 就应该被提前标黄或标红。

## 问题定义

本文把“智能体开始糊弄”定义为:

> 智能体的承诺、结论或收尾动作开始超过其外部证据账本能够支持的范围。

更工程化地说, 糊弄是以下三个量之间的失衡:

- Claim: 智能体声称完成、验证、修复、确认了什么。
- State: 外部任务账本中目标、验收项、步骤、失败、checkpoint 的真实状态。
- Evidence: 可以审计的命令结果、测试、文件、来源、截图、用户批准或导出物。

当 `Claim > Evidence + State` 时, 糊弄风险上升。

## 早期信号

糊弄不必等到最终答错才算发生。更早的启动信号包括:

- 把“计划要做”说成“已经完成”。
- 工具失败后没有恢复动作, 却继续推进结论。
- 多轮输出都在总结、解释、重新规划, 但没有新增测试、文件、来源或证据。
- 验收项仍是 pending/in_progress, 但智能体进入 final 或 summary 语气。
- 上下文压缩后丢失原始约束、风险和未完成项。
- “已验证”“没问题”“可以交付”等声明没有 evidence id。
- token/cost/latency 持续升高, 但证据增量接近 0。

## 成因模型

1. 语言闭合冲动

LLM 擅长把不完整的信息组织成完整叙事。长任务中, 这种能力会把证据缺口包装成合理解释。

2. 外部状态缺失

如果目标、验收标准、失败记录和证据只存在于上下文中, 任何压缩、遗忘或错误总结都会造成任务状态漂移。

3. 计划和执行混淆

智能体说“接下来运行测试”和“测试已通过”在语言上都很容易生成, 但工程上必须由命令结果和证据账本区分。

4. 工具失败被叙事洗白

失败命令、404、超时、权限问题、测试失败如果没有 unresolved failure 记录, 很容易在最终回答中消失。

5. 长上下文状态腐烂

上下文越长, 智能体越容易记住当前故事线, 忘掉原始验收项和用户约束。

6. 激励目标偏差

许多智能体默认优化“给出完整答复”和“让用户感觉任务在推进”, 但长任务真正需要优化“证据闭环”和“失败诚实”。

## 糊弄指数参数

HulunGuard 将糊弄指数分解为以下可观测参数:

| 参数 | 含义 | 典型升高条件 |
| --- | --- | --- |
| `evidence_gap` | 验收项和完成声明缺少证据 | done/verified 但无 evidence id |
| `claim_overhang` | 声明超过证据覆盖 | final/summary 中完成声明多于证据 |
| `unfinished_criteria` | 验收项未闭环 | C1/C2 仍 pending 或 blocked |
| `stagnation` | 最近缺少真实执行进展 | 多轮 note/summary/plan, 无 useful event |
| `unhandled_failures` | 失败事件没有被解决 | tool/test/source fail 且 unresolved |
| `context_decay` | checkpoint/resume 信息腐烂 | 无 checkpoint 或 checkpoint 过旧 |
| `intent_drift` | 最近动作偏离目标 | 最近事件文本与目标/验收项重叠低 |
| `phase_disorder` | 执行相位错乱 | 未验证先 final, 未实现先总结 |
| `retry_loop` | 重复无效动作 | 同一 action_key 多次失败或未知 |
| `polish_without_progress` | 语言打磨替代进展 | 输出越来越完整, 证据没有增长 |
| `cost_pressure` | 高消耗低证据 | token/cost/latency 高但无 useful event |
| `uncertainty` | 未验证的不确定性 | “可能/应该/看起来”且没有新证据 |

一个实用的一阶模型:

```text
HulunIndex =
  evidence_gap
+ claim_overhang
+ unfinished_criteria
+ stagnation
+ unhandled_failures
+ context_decay
+ intent_drift
+ phase_disorder
+ retry_loop
+ polish_without_progress
+ cost_pressure
+ uncertainty
```

指数仍然映射到 0-100:

- 0-35: green, 可以继续。
- 36-65: yellow, 应 checkpoint 或校准。
- 66-100: red, 不允许宣称完成。

## 外部开源项目可吸收的信号

### LangGraph

LangGraph persistence 会把 graph state 以 checkpoint 形式保存到 thread 中, 支持 human-in-the-loop、time travel 和 fault-tolerant execution。HulunGuard 可以从这里吸收:

- checkpoint 间隔 -> `context_decay`
- interrupt/approval 状态 -> `phase_disorder` 与 `required_action`
- thread_id/run state -> conversation monitor id

来源: https://docs.langchain.com/oss/javascript/langgraph/persistence

### SWE-agent

SWE-agent trajectory 文件记录 response/thought/action/observation/state/query。HulunGuard 可以把 trajectory 转成事件序列:

- action/observation -> `tool_result`, `command`
- repeated action -> `retry_loop`
- state diff 或 patch -> `evidence_gap` 降低
- trajectory phase -> `phase_disorder`

来源: https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md

### OpenHands

OpenHands SDK 暴露 ConversationErrorEvent、AgentErrorEvent、ObservationEvent、ActionEvent、Condensation 等事件。HulunGuard 可以映射:

- AgentErrorEvent / ConversationErrorEvent -> `unhandled_failures`
- Condensation / forgotten_event_ids -> `context_decay`
- ActionEvent / ObservationEvent -> useful event 或失败债务

来源: https://docs.openhands.dev/sdk/api-reference/openhands.sdk.event

### OpenTelemetry GenAI

OpenTelemetry GenAI semantic conventions 定义了 GenAI events、exceptions、metrics、model spans 和 agent spans。HulunGuard 应兼容这些字段, 不必自造所有 trace 语义:

- model/agent spans -> conversation/run event
- exceptions -> `unhandled_failures`
- metrics -> `cost_pressure`
- events -> `.hulun/state.json` 的 observation

来源: https://opentelemetry.io/docs/specs/semconv/gen-ai/

### Langfuse / Phoenix

Langfuse 和 Phoenix 更适合作为 trace/eval 层。它们可以提供:

- generation latency/input tokens/output tokens/cost -> `cost_pressure`
- trace/session annotation -> human approval evidence
- eval score -> external verification evidence
- prompt/response trace -> `claim_overhang`

来源:

- https://langfuse.com/docs/observability/overview
- https://arize.com/docs/phoenix

### AgentOps / Helicone / LiteLLM

AgentOps session 会聚合 actions、LLM calls、tool usage、errors、cost 和 token counts。Helicone alerts 可以监控 error rate、cost、latency、token metrics 和 request count。LiteLLM proxy 提供 gateway、logging、cost tracking 和 rate limiting。

这些指标本身不等于糊弄, 但能变成糊弄指数的生理信号:

- 高 error rate -> `unhandled_failures`
- 高 token/cost + 低 evidence -> `polish_without_progress` 或 `cost_pressure`
- 高 latency + retry -> `retry_loop`
- request count 异常但无证据 -> `stagnation`

来源:

- https://docs.agentops.ai/v1/concepts/sessions
- https://docs.helicone.ai/features/alerts
- https://docs.litellm.ai/

## 产品策略

HulunGuard 不应替代 Langfuse、Phoenix、AgentOps、Helicone、LiteLLM 或 OpenTelemetry。它应该做一件更窄但更关键的事:

> 把外部观测指标翻译成“当前智能体是否允许宣称完成”。

其他工具回答“发生了什么”, HulunGuard 回答:

- 这个完成声明有没有证据。
- 这个失败有没有被处理。
- 这个上下文是否还能恢复。
- 当前是否可以 final。

## 实现路线

1. Observation API

提供 `hulun observe` 命令, 让任意 agent 或外部 adapter 写入事件、phase、claims、token/cost/latency、action_key 和 source_platform。

2. Realtime Scanner

`hulun serve` 和 `hulun board --serve` 已经能定时刷新。只要 agent 持续调用 `hulun observe --scan`, dashboard 就会显示实时糊弄指数。

3. Adapter Layer

短期先做手动/CLI adapter。中期可为 SWE-agent trajectory、OpenHands event stream、LangGraph checkpoint、OpenTelemetry spans 写转换器。

4. Final Gate

当 `final_attempt=true` 或 phase 为 `final` 时, 若 `HulunIndex >= threshold`, `hulun verify` 必须阻止完成声明。

## 研究假设

HulunGuard 的核心假设是:

> 长任务智能体的可靠性不取决于最终回答是否漂亮, 而取决于其执行轨迹是否能被外部证据账本重放和审计。

如果这个假设成立, 那么糊弄指数应该能在最终失败前提前升高。

## 后续论文方向

- 构建一组“糊弄轨迹”数据集: 包括真实失败、lucky pass、工具失败被掩盖、上下文压缩后漂移等。
- 将 HulunIndex 与人工审计评分对齐, 验证哪些参数最有解释力。
- 比较不同 agent 框架的失败模式: Codex、OpenHands、SWE-agent、LangGraph agents、CrewAI、AutoGen。
- 研究“漂亮话/证据比”: 输出完整度增长但证据增长停滞时, 是否能预测最终虚假完成。
