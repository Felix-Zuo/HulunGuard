from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from . import __version__
from .sdk import HulunGuardClient, HulunGuardError

PROTOCOL_VERSION = "2025-11-25"


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _string_array(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _number(description: str) -> dict[str, str]:
    return {"type": "number", "description": description}


def _integer(description: str) -> dict[str, str]:
    return {"type": "integer", "description": description}


def _boolean(description: str) -> dict[str, str]:
    return {"type": "boolean", "description": description}


def _json_value(description: str) -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "object"},
            {"type": "array"},
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "null"},
        ],
        "description": description,
    }


class HulunMCPServer:
    def __init__(self, *, root: str = ".", include_sensitive: bool = False, retention_days: int = 30) -> None:
        self.client = HulunGuardClient(root, include_sensitive=include_sensitive, retention_days=retention_days)

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "hulun_project_init",
                "title": "Initialize HulunGuard Project",
                "description": "Initialize a project ledger for HulunGuard runtime monitoring.",
                "inputSchema": _schema(
                    {
                        "objective": _string("Project objective."),
                        "criteria": _string_array("Evidence-backed success criteria."),
                        "constraints": _string_array("Task constraints."),
                        "assumptions": _string_array("Known assumptions."),
                        "threshold": _integer("Blocking threshold."),
                        "force": _boolean("Replace existing HulunGuard state."),
                    },
                    ["objective"],
                ),
            },
            {
                "name": "hulun_observe",
                "title": "Record HulunGuard Observation",
                "description": "Record a project runtime observation and optionally rescan the HulunIndex.",
                "inputSchema": _schema(
                    {
                        "type": _string("Event type, such as tool_result, llm_call, final_attempt, evidence, or summary."),
                        "summary": _string("Short observation summary. Sensitive text is redacted unless the server was started with --include-sensitive."),
                        "result": _string("pass, fail, or unknown."),
                        "phase": _string("explore, plan, implement, verify, recover, summarize, final, or orchestrate."),
                        "claims": _string_array("Completion or verification claims made by the agent."),
                        "evidence": _string_array("Evidence ids that support this observation."),
                        "refs": _string_array("Paths, URLs, trace ids, or command references."),
                        "resolved": _boolean("Whether this event resolves a previous failure or pending action."),
                        "source_platform": _string("Adapter source, such as codex, langgraph, openhands, swe-agent, or mcp."),
                        "action_key": _string("Stable action fingerprint for retry-loop detection."),
                        "prompt_tokens": _integer("Prompt token count."),
                        "completion_tokens": _integer("Completion token count."),
                        "cost": _number("Model cost in the caller's currency unit."),
                        "latency_ms": _integer("Latency in milliseconds."),
                        "model": _string("Model name."),
                        "scan": _boolean("Recalculate project HulunIndex after recording."),
                    },
                    ["type", "summary"],
                ),
            },
            {
                "name": "hulun_scan",
                "title": "Scan HulunGuard Project",
                "description": "Recalculate project HulunIndex for the configured root.",
                "inputSchema": _schema(
                    {
                        "threshold": _integer("Optional blocking threshold."),
                        "final_attempt": _boolean("Whether the scan is gating a final answer."),
                        "checkpoint_stale_minutes": _integer("Minutes before checkpoint evidence is considered stale."),
                    }
                ),
            },
            {
                "name": "hulun_batch_enqueue",
                "title": "Queue HulunGuard Observation",
                "description": "Append one runtime observation to the durable batch queue without opening the project ledger.",
                "inputSchema": _schema(
                    {
                        "type": _string("Event type, such as tool_result, llm_call, final_attempt, evidence, or summary."),
                        "summary": _string("Short observation summary. Sensitive text is redacted unless the server was started with --include-sensitive."),
                        "result": _string("pass, fail, or unknown."),
                        "phase": _string("explore, plan, implement, verify, recover, summarize, final, or orchestrate."),
                        "claims": _string_array("Completion or verification claims made by the agent."),
                        "evidence": _string_array("Evidence ids that support this observation."),
                        "refs": _string_array("Paths, URLs, trace ids, or command references."),
                        "resolved": _boolean("Whether this event resolves a previous failure or pending action."),
                        "source_platform": _string("Adapter source, such as codex, langgraph, openhands, swe-agent, or mcp."),
                        "action_key": _string("Stable action fingerprint for retry-loop detection."),
                        "prompt_tokens": _integer("Prompt token count."),
                        "completion_tokens": _integer("Completion token count."),
                        "cost": _number("Model cost in the caller's currency unit."),
                        "latency_ms": _integer("Latency in milliseconds."),
                        "model": _string("Model name."),
                    },
                    ["type", "summary"],
                ),
            },
            {
                "name": "hulun_batch_status",
                "title": "Inspect HulunGuard Batch Queue",
                "description": "Report pending queue records, queue bytes, parse errors, and dead letters.",
                "inputSchema": _schema({}),
            },
            {
                "name": "hulun_batch_ingest_payload",
                "title": "Queue HulunGuard Runtime Payload",
                "description": "Normalize an in-memory trace payload and append its observations to the durable batch queue.",
                "inputSchema": _schema(
                    {
                        "payload": _json_value("Trace payload object or array from a supported runtime adapter."),
                        "format": _string("auto, generic, opentelemetry, openinference, openhands, swe-agent, langgraph, langsmith, langfuse, phoenix, or openai-agents."),
                        "source_name": _string("Logical source name recorded as redacted queue metadata."),
                        "source_platform": _string("Override source platform on queued observations."),
                        "max_payload_bytes": _integer("Maximum JSON-serialized payload size in bytes."),
                    },
                    ["payload"],
                ),
            },
            {
                "name": "hulun_batch_flush",
                "title": "Flush HulunGuard Batch Queue",
                "description": "Move queued observations into the project ledger in a bounded batch and optionally rescan the HulunIndex.",
                "inputSchema": _schema(
                    {
                        "limit": _integer("Maximum queued observations to flush."),
                        "scan": _boolean("Recalculate project HulunIndex after flushing."),
                        "threshold": _integer("Optional blocking threshold."),
                        "final_attempt": _boolean("Whether the scan is gating a final answer."),
                        "checkpoint_stale_minutes": _integer("Minutes before checkpoint evidence is considered stale."),
                        "init_if_missing": _boolean("Create a minimal project ledger before flushing if no state exists."),
                        "init_objective": _string("Objective used with init_if_missing."),
                        "init_criterion": _string("Criterion used with init_if_missing."),
                        "init_threshold": _integer("Risk threshold used with init_if_missing."),
                    }
                ),
            },
            {
                "name": "hulun_conversation_start",
                "title": "Start HulunGuard Conversation",
                "description": "Start a live conversation runtime monitor.",
                "inputSchema": _schema(
                    {
                        "name": _string("Conversation name."),
                        "group": _string("Project or workspace group."),
                        "objective": _string("Optional conversation objective."),
                        "monitor": _boolean("Create a monitor board entry."),
                    },
                    ["name"],
                ),
            },
            {
                "name": "hulun_conversation_event",
                "title": "Record HulunGuard Conversation Event",
                "description": "Record a live conversation runtime event and return the conversation HulunIndex.",
                "inputSchema": _schema(
                    {
                        "conversation_id": _string("Conversation id returned by hulun_conversation_start."),
                        "type": _string("Event type, such as user_message, assistant_plan, tool_call, tool_result, evidence, or final_attempt."),
                        "summary": _string("Short event summary."),
                        "result": _string("pass, fail, or unknown."),
                        "phase": _string("explore, plan, implement, verify, recover, summarize, final, or orchestrate."),
                        "claims": _string_array("Completion or verification claims."),
                        "evidence": _string_array("Evidence ids."),
                        "refs": _string_array("Paths, URLs, trace ids, or command references."),
                        "resolved": _boolean("Whether this event resolves a previous failure or pending action."),
                        "action_key": _string("Stable action key used to match tool calls and results."),
                        "prompt_tokens": _integer("Prompt token count."),
                        "completion_tokens": _integer("Completion token count."),
                        "cost": _number("Model cost in the caller's currency unit."),
                        "latency_ms": _integer("Latency in milliseconds."),
                        "model": _string("Model name."),
                    },
                    ["conversation_id", "type", "summary"],
                ),
            },
            {
                "name": "hulun_conversation_scan",
                "title": "Scan HulunGuard Conversation",
                "description": "Recalculate HulunIndex for a live conversation.",
                "inputSchema": _schema(
                    {
                        "conversation_id": _string("Conversation id."),
                        "checkpoint_stale_minutes": _integer("Minutes before checkpoint evidence is considered stale."),
                    },
                    ["conversation_id"],
                ),
            },
        ]

    def handle_message(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(message, list):
            responses = [response for item in message if (response := self.handle_message(item)) is not None]
            return responses or None
        if not isinstance(message, dict):
            return self._error(None, -32600, "Invalid JSON-RPC message.")

        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if request_id is None and method and str(method).startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                return self._result(
                    request_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "hulunguard", "version": __version__},
                    },
                )
            if method == "tools/list":
                return self._result(request_id, {"tools": self.tools()})
            if method == "tools/call":
                return self._result(request_id, self._call_tool(params))
            return self._error(request_id, -32601, f"Unknown method: {method}")
        except (HulunGuardError, ValueError, TypeError, KeyError) as exc:
            return self._error(request_id, -32602, str(exc))

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise HulunGuardError("tools/call arguments must be an object.")

        if name == "hulun_project_init":
            payload = self.client.init(
                objective=str(arguments["objective"]),
                criteria=arguments.get("criteria"),
                constraints=arguments.get("constraints"),
                assumptions=arguments.get("assumptions"),
                threshold=int(arguments.get("threshold") or 66),
                force=bool(arguments.get("force")),
            )
            return self._tool_result(payload)
        if name == "hulun_observe":
            payload = self.client.observe(
                event_type=str(arguments["type"]),
                summary=str(arguments["summary"]),
                result=str(arguments.get("result") or "pass"),
                phase=arguments.get("phase"),
                claims=arguments.get("claims"),
                evidence=arguments.get("evidence"),
                refs=arguments.get("refs"),
                resolved=arguments.get("resolved"),
                source_platform=arguments.get("source_platform") or "mcp",
                action_key=arguments.get("action_key"),
                prompt_tokens=arguments.get("prompt_tokens"),
                completion_tokens=arguments.get("completion_tokens"),
                cost=arguments.get("cost"),
                latency_ms=arguments.get("latency_ms"),
                model=arguments.get("model"),
                scan=bool(arguments.get("scan")),
            )
            return self._tool_result(payload)
        if name == "hulun_scan":
            payload = self.client.scan(
                threshold=arguments.get("threshold"),
                final_attempt=bool(arguments.get("final_attempt")),
                checkpoint_stale_minutes=int(arguments.get("checkpoint_stale_minutes") or 45),
            )
            return self._tool_result(payload)
        if name == "hulun_batch_enqueue":
            payload = self.client.enqueue(
                event_type=str(arguments["type"]),
                summary=str(arguments["summary"]),
                result=str(arguments.get("result") or "pass"),
                phase=arguments.get("phase"),
                claims=arguments.get("claims"),
                evidence=arguments.get("evidence"),
                refs=arguments.get("refs"),
                resolved=arguments.get("resolved"),
                source_platform=arguments.get("source_platform") or "mcp",
                action_key=arguments.get("action_key"),
                prompt_tokens=arguments.get("prompt_tokens"),
                completion_tokens=arguments.get("completion_tokens"),
                cost=arguments.get("cost"),
                latency_ms=arguments.get("latency_ms"),
                model=arguments.get("model"),
            )
            return self._tool_result(payload)
        if name == "hulun_batch_status":
            payload = self.client.queue_status()
            return self._tool_result(payload)
        if name == "hulun_batch_ingest_payload":
            payload = self.client.enqueue_payload(
                arguments["payload"],
                source_format=str(arguments.get("format") or "auto"),
                source_name=arguments.get("source_name") or "mcp-payload",
                source_platform=arguments.get("source_platform") or "mcp",
                max_payload_bytes=arguments.get("max_payload_bytes"),
            )
            return self._tool_result(payload)
        if name == "hulun_batch_flush":
            payload = self.client.flush_queue(
                limit=int(arguments.get("limit") or 500),
                scan=bool(arguments.get("scan")),
                threshold=arguments.get("threshold"),
                final_attempt=bool(arguments.get("final_attempt")),
                checkpoint_stale_minutes=int(arguments.get("checkpoint_stale_minutes") or 45),
                init_if_missing=bool(arguments.get("init_if_missing")),
                init_objective=arguments.get("init_objective"),
                init_criterion=arguments.get("init_criterion"),
                init_threshold=int(arguments.get("init_threshold") or 66),
            )
            return self._tool_result(payload)
        if name == "hulun_conversation_start":
            payload = self.client.start_conversation(
                name=str(arguments["name"]),
                group=str(arguments.get("group") or "default"),
                objective=arguments.get("objective"),
                monitor=bool(arguments.get("monitor")),
            )
            return self._tool_result(payload)
        if name == "hulun_conversation_event":
            payload = self.client.conversation_event(
                conversation_id=str(arguments["conversation_id"]),
                event_type=str(arguments["type"]),
                summary=str(arguments["summary"]),
                result=str(arguments.get("result") or "pass"),
                phase=arguments.get("phase"),
                claims=arguments.get("claims"),
                evidence=arguments.get("evidence"),
                refs=arguments.get("refs"),
                resolved=arguments.get("resolved"),
                action_key=arguments.get("action_key"),
                prompt_tokens=arguments.get("prompt_tokens"),
                completion_tokens=arguments.get("completion_tokens"),
                cost=arguments.get("cost"),
                latency_ms=arguments.get("latency_ms"),
                model=arguments.get("model"),
            )
            return self._tool_result(payload)
        if name == "hulun_conversation_scan":
            payload = self.client.conversation_scan(
                conversation_id=str(arguments["conversation_id"]),
                checkpoint_stale_minutes=int(arguments.get("checkpoint_stale_minutes") or 45),
            )
            return self._tool_result(payload)
        raise HulunGuardError(f"Unknown tool: {name}")

    @staticmethod
    def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": payload,
            "isError": False,
        }

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(server: HulunMCPServer, *, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = server.handle_message(message)
        except json.JSONDecodeError as exc:
            response = server._error(None, -32700, f"Parse error: {exc.msg}")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hulun-mcp", description="HulunGuard MCP stdio server.")
    parser.add_argument("--root", default=".", help="Project root for project-level HulunGuard tools.")
    parser.add_argument("--include-sensitive", action="store_true", help="Persist sensitive text instead of default redacted summaries.")
    parser.add_argument("--retention-days", type=int, default=30, help="Retention hint for recorded events.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve_stdio(HulunMCPServer(root=args.root, include_sensitive=args.include_sensitive, retention_days=args.retention_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
