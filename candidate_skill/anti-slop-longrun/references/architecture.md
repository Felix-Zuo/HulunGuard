# Industrial Architecture For Long-Running Agents

## Problem

Long tasks fail after context compaction when the model loses the goal, forgets constraints, cannot distinguish completed work from intended work, or makes final claims without evidence.

## Recommended Layers

1. Durable state: Store objective, criteria, plan, constraints, and current status outside chat history.
2. Evidence ledger: Attach every completion claim to command output, source link, file hash, artifact path, screenshot, or user approval.
3. Checkpoints: Generate compact handoff packets at phase boundaries and before likely compaction.
4. Verification gate: Block final completion unless criteria are marked done and supported by evidence.
5. Observability: Preserve traces or trajectories for debugging repeated failure modes.
6. Memory service: Use a graph/vector memory layer for cross-session knowledge, but keep run state separate from general memory.
7. Human control: Keep approvals, destructive actions, and unresolved blockers explicit.

## Tooling Lessons From Current Ecosystem

- LangGraph is strong for stateful graph execution, checkpointing, replay, human-in-the-loop, and production stores.
- Temporal is strong for durable execution when tasks must survive process crashes, retries, waits, signals, and multi-day workflows.
- Letta/MemGPT-style agents show that memory should be actively managed through context hierarchy and persisted message/state stores.
- Mem0, Graphiti/Zep, and Cognee are practical memory layers for recalling facts, episodes, and graph relationships across sessions.
- OpenHands and SWE-agent show the value of trajectory logs: every thought/action/observation or command step can be inspected later.
- CrewAI and AutoGen are useful orchestration frameworks, but orchestration alone does not prove correctness; they still need evidence and verification gates.
- Langfuse and Phoenix provide tracing/eval surfaces for production debugging and regression monitoring.
- Guardrails-style validators help with structured outputs and policy checks, but they do not replace task-level evidence.

## Recommended Build Order

1. Start with local `.hulun/` state and verification for Codex-style work.
2. Add tracing if repeated long-run failures need diagnosis.
3. Add memory retrieval for reusable project facts, preferences, and prior lessons.
4. Move orchestration to LangGraph or Temporal only when the agent becomes a service or must resume automatically after process failure.
