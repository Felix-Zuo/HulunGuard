# 调研项目矩阵

GitHub 数据来自 2026-06-08 本地 GitHub API 快照，可能随时间变化。

| 项目 | 定位 | 对防糊弄的关键价值 | 风险/限制 | 快照 |
| --- | --- | --- | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 状态化 agent/workflow 框架 | checkpoint、thread、store、replay、human-in-loop，是工程化长线 agent 的核心候选 | 需要自己设计状态 schema 和验证策略 | 34,088 stars, MIT, updated 2026-06-07 |
| [Temporal](https://github.com/temporalio/temporal) | 持久执行平台 | 多日/月级工作流、活动重试、信号、定时器、崩溃恢复 | 对简单 Codex 本地任务偏重，适合服务化后采用 | 20,805 stars, MIT, updated 2026-06-07 |
| [Letta](https://github.com/letta-ai/letta) | Stateful agents / MemGPT 演进 | 上下文层级、自编辑记忆、持久消息和状态，适合长期个人/服务 agent | 平台化较强，直接替换现有 Codex 工作流成本较高 | 23,191 stars, Apache-2.0, updated 2026-06-07 |
| [Mem0](https://github.com/mem0ai/mem0) | 通用 agent memory layer | User/Session/Agent 多级记忆，SDK、自托管和云选项 | 记忆层不能替代当前任务状态账本 | 57,954 stars, Apache-2.0, updated 2026-06-07 |
| [Graphiti](https://github.com/getzep/graphiti) / [Zep](https://www.getzep.com/platform/graphiti/) | Temporal knowledge graph memory | 事实有时间有效性，支持 vector/full-text/graph 混合检索，适合业务记忆 | 图数据库和 schema 维护成本高 | 27,135 stars, Apache-2.0, updated 2026-06-07 |
| [Cognee](https://github.com/topoteretes/cognee) | Agent memory control plane | 文档/数据到图谱记忆，支持 session memory、工具调用捕获、OpenClaw/Claude Code 集成方向 | 依赖 LLM/embedding 配置；生产需权限隔离 | 17,713 stars, Apache-2.0, updated 2026-06-07 |
| [OpenHands](https://github.com/OpenHands/OpenHands) | 开源软件开发 agent 平台 | sandbox、CLI/SDK/local GUI、可运行命令和浏览网页，适合端到端开发任务 | 完整平台较大，不是轻量 skill | 76,108 stars, license noassertion/API, updated 2026-06-07 |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | 软件工程 agent / ACI | trajectory 日志可检查每步 action/observation，是证据账本设计样板 | 官方文档提示 SWE-agent 已被 mini-swe-agent 继任，原项目维护模式变化 | 19,448 stars, MIT, updated 2026-06-07 |
| [CrewAI](https://github.com/crewAIInc/crewAI) | 多智能体编排 | planning、memory、tools、checkpointing、flows，适合团队式任务拆分 | 多代理不等于正确，必须外接验证闸门 | 52,978 stars, MIT, updated 2026-06-07 |
| [AutoGen](https://github.com/microsoft/autogen) | 多智能体编程框架 | event-driven agents、AgentChat、Magentic-One、AutoGen Bench | GitHub README 指向 Microsoft Agent Framework 作为新项目长期支持方向 | 58,748 stars, CC-BY-4.0 repo license field, updated 2026-06-07 |
| [Guardrails AI](https://github.com/guardrails-ai/guardrails) | LLM 输入/输出校验 | 结构化输出和风险 validator，可做响应闸门 | 不能证明任务完成，只能校验某类输出风险 | 6,975 stars, Apache-2.0, updated 2026-06-07 |
| [Langfuse](https://github.com/langfuse/langfuse) | LLM observability/evals | trace、metrics、evals、prompt management、datasets | 需要部署或云服务；与本地 Codex 需集成 | 28,624 stars, license noassertion/API, updated 2026-06-07 |
| [Phoenix](https://github.com/Arize-ai/phoenix) | AI observability/evaluation | OpenTelemetry/OpenInference tracing、eval、实验 | 更偏观测平台，不直接管理任务状态 | 10,009 stars, license noassertion/API, updated 2026-06-07 |

## 工业组合推荐

本地 Codex 长线任务：

1. `anti-slop-longrun` skill + `.longrun_guard`。
2. 可选 Cognee 或 Mem0 作为项目长期记忆。
3. 有重复失败时接 Langfuse/Phoenix trace。

服务化 agent：

1. LangGraph 管理 agent state 和分支。
2. Temporal 管理 durable workflow 和 human approval。
3. Graphiti/Zep 或 Cognee 管理跨会话知识图谱。
4. Langfuse/Phoenix 记录 trace/eval。
5. Guardrails/Pydantic/JSON schema 做输出和工具调用边界校验。
