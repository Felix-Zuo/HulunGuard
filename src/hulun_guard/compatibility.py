from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .schemas import AGENT_COMPATIBILITY_SCHEMA
from .util import utc_now

AGENT_COMPATIBILITY: tuple[dict[str, Any], ...] = (
    {
        "id": "openhands",
        "name": "OpenHands",
        "category": "direct-adapter",
        "tier": "integration-tested",
        "ingest_format": "openhands",
        "command": "python -m hulun_guard ingest --format openhands --file trace.json --scan",
        "source_uri": "https://docs.openhands.dev/sdk/arch/events",
        "guarantee": "OpenHands-like action and observation event logs are fixture-tested through the ingest adapter.",
    },
    {
        "id": "swe-agent",
        "name": "SWE-agent",
        "category": "direct-adapter",
        "tier": "integration-tested",
        "ingest_format": "swe-agent",
        "command": "python -m hulun_guard ingest --format swe-agent --file trajectory.json --scan",
        "source_uri": "https://swe-agent.com/latest/usage/trajectories/",
        "guarantee": "SWE-agent-like trajectory steps are fixture-tested through the ingest adapter.",
    },
    {
        "id": "langgraph",
        "name": "LangGraph",
        "category": "direct-adapter",
        "tier": "hosted-fixture-tested",
        "ingest_format": "langgraph",
        "command": "python -m hulun_guard ingest --format langgraph --file stream.json --scan",
        "source_uri": "https://docs.langchain.com/oss/python/langgraph/streaming",
        "guarantee": "LangGraph stream parts are fixture-tested for hosted-platform event shape coverage.",
    },
    {
        "id": "langsmith",
        "name": "LangSmith",
        "category": "direct-adapter",
        "tier": "hosted-fixture-tested",
        "ingest_format": "langsmith",
        "command": "python -m hulun_guard ingest --format langsmith --file runs.json --scan",
        "source_uri": "https://docs.langchain.com/langsmith/export-traces",
        "guarantee": "LangSmith run exports are fixture-tested for hosted-platform run and span metadata coverage.",
    },
    {
        "id": "langfuse",
        "name": "Langfuse",
        "category": "direct-adapter",
        "tier": "roundtrip-tested",
        "ingest_format": "langfuse",
        "command": "python -m hulun_guard ingest --format langfuse --file otel.json --scan",
        "source_uri": "https://langfuse.com/integrations/native/opentelemetry",
        "guarantee": "Langfuse OTEL traces are imported through the OpenTelemetry path and covered by round-trip checks.",
    },
    {
        "id": "phoenix",
        "name": "Phoenix",
        "category": "direct-adapter",
        "tier": "roundtrip-tested",
        "ingest_format": "phoenix",
        "command": "python -m hulun_guard ingest --format phoenix --file openinference.json --scan",
        "source_uri": "https://arize-ai.github.io/openinference/spec/semantic_conventions.html",
        "guarantee": "Phoenix/OpenInference spans are imported through the OpenInference path and covered by round-trip checks.",
    },
    {
        "id": "opentelemetry-genai",
        "name": "OpenTelemetry GenAI apps",
        "category": "standard",
        "tier": "roundtrip-tested",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file otlp.json --scan",
        "source_uri": "https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/",
        "guarantee": "OTLP JSON with GenAI attributes is round-trip tested through import, persistence, export, and re-import.",
    },
    {
        "id": "openinference",
        "name": "OpenInference-compatible apps",
        "category": "standard",
        "tier": "roundtrip-tested",
        "ingest_format": "openinference",
        "command": "python -m hulun_guard ingest --format openinference --file spans.json --scan",
        "source_uri": "https://arize-ai.github.io/openinference/spec/",
        "guarantee": "OpenInference span dictionaries are round-trip tested through import, persistence, export, and re-import.",
    },
    {
        "id": "autogen",
        "name": "AutoGen",
        "category": "standard",
        "tier": "standards-path",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file autogen-otel.json --scan",
        "source_uri": "https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tracing.html",
        "guarantee": "AutoGen runs can use HulunGuard through the OpenTelemetry export path when OTLP JSON is available.",
    },
    {
        "id": "crewai",
        "name": "CrewAI",
        "category": "standard",
        "tier": "standards-path",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file crewai-otel.json --scan",
        "source_uri": "https://docs.crewai.com/en/observability/openlit",
        "guarantee": "CrewAI projects can use HulunGuard through OpenTelemetry-native observability integrations that emit OTLP JSON.",
    },
    {
        "id": "llamaindex",
        "name": "LlamaIndex",
        "category": "standard",
        "tier": "standards-path",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file llamaindex-otel.json --scan",
        "source_uri": "https://developers.llamaindex.ai/python/framework/module_guides/observability/",
        "guarantee": "LlamaIndex runs can use HulunGuard through OpenTelemetry exports or OpenInference-compatible Phoenix traces.",
    },
    {
        "id": "haystack",
        "name": "Haystack",
        "category": "standard",
        "tier": "standards-path",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file haystack-otel.json --scan",
        "source_uri": "https://docs.haystack.deepset.ai/docs/tracing",
        "guarantee": "Haystack pipelines can use HulunGuard through the OpenTelemetry tracing backend path.",
    },
    {
        "id": "semantic-kernel",
        "name": "Semantic Kernel",
        "category": "standard",
        "tier": "standards-path",
        "ingest_format": "opentelemetry",
        "command": "python -m hulun_guard ingest --format opentelemetry --file semantic-kernel-otel.json --scan",
        "source_uri": "https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/observability/telemetry-advanced",
        "guarantee": "Semantic Kernel applications can use HulunGuard through OpenTelemetry spans exported from its telemetry setup.",
    },
    {
        "id": "openai-agents-sdk",
        "name": "OpenAI Agents SDK",
        "category": "bridge",
        "tier": "generic-bridge",
        "ingest_format": "generic",
        "command": "python -m hulun_guard ingest --format generic --file openai-agents-events.jsonl --scan",
        "source_uri": "https://openai.github.io/openai-agents-python/tracing/",
        "guarantee": "OpenAI Agents SDK traces can be bridged through generic JSON/JSONL events or through a tracing processor that emits OTLP JSON.",
    },
    {
        "id": "custom-agent",
        "name": "Custom or in-house agents",
        "category": "bridge",
        "tier": "generic-bridge",
        "ingest_format": "generic",
        "command": "python -m hulun_guard ingest --format generic --file events.jsonl --scan",
        "source_uri": "internal://hulunguard/adapter-contract/generic-json",
        "guarantee": "Any agent that can emit JSON or JSONL with HulunGuard event fields can use the generic ingest bridge.",
    },
)


def compatibility_report() -> dict[str, Any]:
    category_counts = Counter(item["category"] for item in AGENT_COMPATIBILITY)
    tier_counts = Counter(item["tier"] for item in AGENT_COMPATIBILITY)
    direct_or_standard = sum(1 for item in AGENT_COMPATIBILITY if item["category"] in {"direct-adapter", "standard"})
    return {
        "schema": AGENT_COMPATIBILITY_SCHEMA,
        "generated_at": utc_now(),
        "coverage_statement": (
            "Most mainstream agents can use HulunGuard through a direct adapter, OpenTelemetry/OpenInference, "
            "or the generic JSON/JSONL bridge; native exporter guarantees remain limited to tested formats."
        ),
        "entry_count": len(AGENT_COMPATIBILITY),
        "direct_or_standard_count": direct_or_standard,
        "category_counts": dict(sorted(category_counts.items())),
        "tier_counts": dict(sorted(tier_counts.items())),
        "agents": [dict(item) for item in AGENT_COMPATIBILITY],
    }


def agent_compatibility_json(result: dict[str, Any] | None = None) -> str:
    return json.dumps(result or compatibility_report(), ensure_ascii=False, indent=2) + "\n"
