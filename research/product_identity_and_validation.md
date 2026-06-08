# HulunGuard 产品定位与糊弄指数验证记录

日期: 2026-06-08

## 结论

HulunGuard 不是单纯的 skill, 也不是普通插件。更准确的定位是:

> 面向长任务智能体的本地优先可靠性监控层, 用外部状态账本和轨迹事件计算糊弄风险指数。

它可以有多种外壳:

- CLI: `hulun init`, `hulun observe`, `hulun scan`, `hulun verify`, `hulun serve`。
- Desktop monitor: HulunGauge 小窗和 project board。
- Skill adapter: 给 Codex、Claude Code 等 agent 注入工作流约束。
- Plugin/hook adapter: 例如 OpenClaw hook。
- Future adapter: OpenTelemetry、Langfuse、Phoenix、OpenHands、SWE-agent、LangGraph、AgentOps、Helicone、LiteLLM。

所以产品本体不是 skill。skill 是接入方式之一。插件也是接入方式之一。HulunGuard 的核心是一个 agent reliability monitor / slop-risk runtime guard。

## 它能不能“确定”智能体正在糊弄

不能。

HulunGuard 当前计算的是:

> slop risk / reliability risk, 不是糊弄真相。

它更像疲劳驾驶预警, 不是测谎仪。它不能证明智能体有主观糊弄意图, 也不能保证低分时一定正确。它能做的是把以下风险外显出来:

- 声明超过证据。
- 失败没有处理。
- 验收项没有闭环。
- 多轮总结但无进展。
- checkpoint 缺失或过旧。
- 工具/动作重复失败。
- 高 token/cost/latency 但无证据增量。
- final/summary 相位过早出现。

因此, 正确命名应该是:

- HulunIndex: 糊弄风险指数。
- HulunGauge: 可视化风险表。
- HulunGuard: 阻止无证据 final 的监控和门禁层。

## 理论与工程证据

1. ReAct 和软件 agent 框架把 agent 明确建模为 thought/action/observation 或 reasoning/action/observation 循环。这支持监控轨迹相位, 而不是只看最终文本。

来源: https://arxiv.org/abs/2210.03629

2. SWE-agent 的 `.traj` 文件记录每一步 thought/action/observation, 说明轨迹本身是 agent 结果的一等产物。

来源: https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md

3. 2025 年软件工程 agent 轨迹研究统一分析 RepairAgent、AutoCodeRover、OpenHands 的 thought-action-result trajectories, 指出 iteration counts、token consumption、recurring action sequences、semantic coherence 等轨迹特征能帮助区分成功和失败模式。

来源: https://arxiv.org/abs/2506.18824

4. 另一项代码 agent 成败轨迹研究分析 OpenHands、SWE-agent、Prometheus 在 SWE-Bench 上的轨迹, 指出失败轨迹通常更长、方差更高, 且成功并不只取决于是否找到文件, 还取决于后续修改质量。

来源: https://arxiv.org/abs/2511.00197

5. AgentRx 研究从失败 agent execution trajectories 中定位关键失败步骤, 并强调 auditable validation log 和 evidence。它支持 HulunGuard 用失败债务、证据覆盖、逐步验证日志来做风险诊断。

来源: https://arxiv.org/abs/2602.02475

6. LangGraph persistence 把 graph state 保存为 checkpoints, 支持 human-in-the-loop、time travel debugging、fault-tolerant execution。这支持 HulunGuard 的 `context_decay`、checkpoint freshness 和 resume packet 设计。

来源: https://langchain-5e9cc07a.mintlify.app/oss/python/langgraph/persistence

7. OpenHands SDK 暴露 ActionEvent、ObservationEvent、AgentErrorEvent、Condensation、ConversationStateUpdateEvent 等事件。这说明工具调用、观察、错误、上下文压缩都可以被实时转成 HulunGuard 参数。

来源: https://docs.openhands.dev/sdk/api-reference/openhands.sdk.event

8. Langfuse 和 Phoenix 都把 tracing、tool calls、token/cost、latency、evals/human labels 作为 LLM/agent observability 的核心。HulunGuard 可以吃这些 trace, 但输出更窄: 是否允许宣称完成。

来源:

- https://langfuse.com/docs/observability/overview
- https://arize.com/docs/phoenix

9. AgentOps session 把 actions、LLM calls、tool usage、errors、cost、token counts 聚合到一个 session。Helicone alerts 支持 error rate、cost、latency、token metrics、request count。这支持 HulunGuard 的 `cost_pressure` 和 `unhandled_failures`, 但它们只能作为辅助信号。

来源:

- https://docs.agentops.ai/v1/concepts/sessions
- https://docs.helicone.ai/features/alerts

10. OpenTelemetry GenAI semantic conventions 正在标准化 GenAI spans、events、metrics、exceptions。HulunGuard 后续不应该只做私有日志, 应该提供 OTel adapter。

来源: https://opentelemetry.io/docs/specs/semconv/gen-ai/

## 本地实验

实验方式: 使用 HulunGuard CLI 在临时目录中构造 4 条受控轨迹, 每条轨迹运行 `hulun scan --json`, 记录最终 HulunIndex。

实验命令类型:

- `hulun init`
- `hulun record-evidence`
- `hulun set-criterion`
- `hulun checkpoint`
- `hulun observe --scan`
- `hulun scan --json`

### 实验结果

| 场景 | 预期 | HulunIndex | band | action | 关键分量 |
| --- | --- | ---: | --- | --- | --- |
| healthy_proof_backed | 健康 | 7 | green | continue | evidence_gap=0, claim_overhang=0 |
| unsupported_final_claim | 开始糊弄风险 | 64 | yellow | checkpoint | evidence_gap=16, claim_overhang=14, unfinished_criteria=14, phase_disorder=4, cost_pressure=2 |
| failure_loop_then_final | 高风险 | 83 | red | recover | unhandled_failures=11, retry_loop=3, claim_overhang=14 |
| expensive_polish_no_progress | 高风险 | 73 | red | recover | polish_without_progress=4, cost_pressure=2, stagnation=11 |

### 观察

1. 健康闭环轨迹能降到绿灯, 说明证据、验收项、checkpoint 和 final claim 能相互抵消风险。

2. 无证据 final claim 被打到黄灯 64, 接近红线但没有直接红灯。这是合理的: 如果只是一次无证据收尾, 系统应该要求 checkpoint/补证据, 而不是立刻判死刑。

3. 失败循环后仍 final 被打到红灯 83。这里 `unhandled_failures`、`retry_loop`、`phase_disorder` 和 `claim_overhang` 叠加, 符合“工具失败被语言洗白”的糊弄模式。

4. 高消耗空转总结被打到红灯 73。这里不是因为 cost 本身, 而是 cost/token/latency 与无证据、多轮 summary、未完成验收项共同出现。

5. 实验过程中发现一个误报: 健康轨迹里多个 completion markers 共享同一 evidence 时, 旧算法会低估覆盖率。已修正为逐事件判断 claim 是否被证据或已完成验收项支持。

## 当前参数可信度分级

高可信核心信号:

- `evidence_gap`
- `claim_overhang`
- `unfinished_criteria`
- `unhandled_failures`
- `phase_disorder`
- `retry_loop`

中可信状态信号:

- `stagnation`
- `context_decay`
- `intent_drift`

辅助告警信号:

- `cost_pressure`
- `polish_without_progress`
- `uncertainty`

辅助信号不能单独判断糊弄, 只能和证据缺口、失败债务、未完成验收项一起解释。

## 仍然不能证明的东西

- 不能证明智能体“有意”糊弄。
- 不能证明低分输出一定正确。
- 不能证明所有领域的阈值都一样。
- 不能完全识别“证据本身是假的”。
- 不能替代人工审计、测试、评审和外部 eval。

## 下一步真实验证计划

1. 构造 30-100 条带人工标签的轨迹:

- 正常完成。
- 无证据宣称完成。
- 工具失败被掩盖。
- 长上下文漂移。
- 盲目重试。
- Lucky pass。
- 高 token 空转。

2. 每条轨迹都转成 `.hulun/state.json` 事件。

3. 记录 HulunIndex, 与人工标签比较:

- precision/recall。
- false positive。
- false negative。
- 哪些分量最有解释力。

4. 逐步调权重:

- 先规则权重。
- 再用小规模标注集做 logistic calibration。
- 最后接入 OTel/Langfuse/Phoenix/OpenHands/SWE-agent adapter 获取真实轨迹。

## 产品命名建议

公开表述:

> HulunGuard is a local-first reliability monitor and final-gate for long-running AI agents. It computes a slop-risk index from evidence coverage, execution trajectory, unresolved failures, checkpoint health, and completion claims.

中文表述:

> HulunGuard 是一个本地优先的长任务智能体可靠性监控与最终门禁层。它通过证据覆盖、执行轨迹、未处理失败、checkpoint 健康度和完成声明计算糊弄风险指数。
