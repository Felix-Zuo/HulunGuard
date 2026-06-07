# 长线智能体防糊弄工业级方案

日期：2026-06-08  
工作目录：`D:\0A OpenClaw\projects\展示项目\skill开发`

## 结论

长时间对话后的“糊弄”通常不是单一模型问题，而是运行系统没有把目标、约束、进度、证据和恢复点外置成可靠状态。上下文压缩后，模型只能依赖不完整摘要，于是容易出现：

- 把“计划要做”误认为“已经做完”。
- 丢失用户约束、验收标准、风险和未完成步骤。
- 生成漂亮但无法验证的结论。
- 重复探索，或者跳过关键验证。
- 在最终回复里只说结果，不给证据。

工业级解决方案不是再写一段更严厉的提示词，而是给智能体加一个外部运行账本和最终验证闸门。

## 推荐架构

### 1. 运行状态层

把每次长线任务的唯一事实源写入项目内 `.longrun_guard/state.json`：

- 目标：当前用户真实要完成的事。
- 验收标准：每条都必须可观察、可证明。
- 约束和假设：用户要求、环境限制、不能做的事。
- 步骤：pending / in_progress / done / blocked / dropped。
- 风险：阻塞项、未验证假设、可能过期的信息。
- 决策：为什么选择某个技术路线。

这对应 LangGraph 的 checkpoint/thread 思路：LangGraph 文档说明它会把 graph state 作为 checkpoints 保存，并支持人类检查、time travel 和 fault-tolerant execution；生产环境应使用 Postgres、MongoDB 或 Redis 等持久 store，而不是只靠内存。来源：[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

### 2. 证据账本层

每个完成声明都要对应证据 ID：

- 测试命令和结果。
- 创建或修改的文件路径和 SHA-256。
- 来源链接。
- 截图、导出物、包和 checksum。
- 用户批准或明确放弃的项。

SWE-agent 的 trajectory 设计很有借鉴价值：它把每一步 response / thought / action / observation / state / query 都写入 `.traj`，方便后续检查代理到底做了什么。来源：[SWE-agent trajectories](https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/trajectories.md)。

### 3. 压缩恢复层

不要让系统自动摘要决定保留什么。每个阶段主动生成 `.longrun_guard/resume.md`：

- 目标。
- 已完成和未完成验收标准。
- 活跃步骤。
- 最新证据。
- 最新 checkpoint。
- 风险和下一步。

Letta 的 stateful agent 设计也支持这个原则：其文档强调消息、记忆、推理和工具调用都会持久化，旧消息即使从上下文中被驱逐，仍可由 API 或检索工具取回。来源：[Letta stateful agents](https://docs.letta.com/guides/core-concepts/stateful-agents)。

### 4. 记忆层

记忆层用于跨任务复用知识，不应替代当前任务状态。推荐按规模选：

- 小规模固定规则：写入 skill 的 `SKILL.md` 或 `.longrun_guard/state.json`。
- 项目级长期知识：Cognee、Graphiti/Zep、Mem0、Letta。
- 大量资料或业务数据：图谱 + 向量 + 全文混合检索。

Graphiti/Zep 的优势是 temporal context graph：事实变化时保留历史并失效旧关系，检索组合 vector、full-text 和 graph traversal。来源：[Graphiti](https://www.getzep.com/platform/graphiti/)。

Cognee 的优势是面向 agent 的 memory control plane，支持 session memory、permanent knowledge graph、工具调用捕获、PreCompact 保留和 OpenClaw/Claude Code 等集成方向。来源：[Cognee GitHub](https://github.com/topoteretes/cognee)。

Mem0 的优势是通用记忆层，支持 User / Session / Agent 多级记忆和 SDK/自托管/云部署。来源：[Mem0 GitHub](https://github.com/mem0ai/mem0)。

### 5. 持久执行层

如果智能体要作为服务长期运行，状态账本应升级到 LangGraph 或 Temporal：

- LangGraph：适合图状态、分支、子图、human-in-loop、checkpoint replay。
- Temporal：适合周级/月级工作流、重试、等待、信号、人类审批、服务崩溃恢复。

Temporal 的官方说明强调 workflow 会在每一步捕获状态，失败后可从中断处继续，并且能运行 days/weeks/months。来源：[Temporal durable execution](https://temporal.io/)。

### 6. 观测和评测层

为了避免“看起来很顺但实际失败”，要保留可查询 trace：

- Langfuse：开源 LLM engineering platform，覆盖 tracing、evals、prompt management、datasets。来源：[Langfuse GitHub](https://github.com/langfuse/langfuse)。
- Phoenix：开源 LLM tracing and evaluation，支持 OpenTelemetry / OpenInference。来源：[Phoenix docs](https://arize.com/docs/phoenix)。
- OpenTelemetry GenAI semantic conventions 正在发展，可作为统一 trace 字段方向。来源：[OpenTelemetry GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)。

### 7. 闸门层

Guardrails、结构化输出校验、LLM-as-judge 可以辅助，但最终任务是否完成必须由“验收标准 + 证据”决定。Guardrails AI 的核心价值是输入/输出 guards 和结构化数据校验。来源：[Guardrails GitHub](https://github.com/guardrails-ai/guardrails)。

## 对现有开源项目的取舍

### 值得吸收

- LangGraph：checkpoint、store、thread_id、replay、state update。
- Temporal：workflow/activity、自动重试、signals、durable timers。
- Letta：context hierarchy、core memory、archival memory、持久消息。
- Graphiti/Zep：temporal graph memory、混合检索、事实失效。
- Cognee：agent memory control plane、session to graph、PreCompact hooks。
- SWE-agent：trajectory log 和 inspector。
- OpenHands：sandbox、SDK/CLI/local GUI、可扩展 agent 运行环境。
- CrewAI/AutoGen：多智能体编排、planner、tools、checkpointing，但必须外接证据验证。
- Langfuse/Phoenix：trace、eval、annotation、regression debugging。

### 不建议只靠

- 单纯扩大上下文窗口：长上下文仍会分散注意力，成本和延迟升高。
- 单纯自动摘要：摘要会丢失未完成项、约束、失败细节。
- 单纯向量记忆：容易召回相似但不权威的内容，不能表示“当前任务到底做到哪”。
- 单纯多智能体讨论：多代理能放大能力，也能放大无证据结论。
- 单纯最终自检提示词：没有外部证据时，自检仍可能自圆其说。

## 本轮已落地的最小工业实现

已在 `candidate_skill/anti-slop-longrun` 中创建候选 skill：

- `SKILL.md`：触发条件和工作流。
- `scripts/longrun_guard.py`：无第三方依赖的运行账本 CLI。
- `references/state_schema.md`：状态结构。
- `references/architecture.md`：工业架构摘要。

它实现了：

- 初始化目标和验收标准。
- 添加/更新步骤。
- 记录证据。
- 记录风险和决策。
- 生成 checkpoint 和 resume packet。
- 最终 `verify` 闸门。

## 推荐后续路线

短期：把 `anti-slop-longrun` 安装到 Codex skills，所有长线任务强制使用。  
中期：把 `.longrun_guard` 与 OpenClaw 的 memory / wiki / hooks 对接，在 `PreCompact` 或等效生命周期里自动生成 resume packet。  
长期：如果要做真正的自动长线智能体服务，用 LangGraph 管理 agent state，用 Temporal 管理 durable execution，用 Cognee/Graphiti/Mem0 管理跨任务记忆，用 Langfuse/Phoenix 做 traces 和 evals。
