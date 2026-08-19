"""Claude tool-use loop for the reporting agent."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from agents.reporting.db import readonly_session
from agents.reporting.logging import QueryLogToolLogger, ToolLogEntry
from agents.reporting.tools import ReportingTools, tool_schemas
from src.ai.client import HAIKU, PRICING, get_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the GHUS reporting agent.

Use only the provided tools for ecosystem facts, counts, RAG retrieval, artifacts,
and email drafts. Do not invent figures. Every numeric claim in a generated
artifact must be backed by cited entity ids in the artifact spec. Prefer counts
for aggregate questions, curated entity queries for lists, get_entity for
details/provenance, and rag_search for narrative or semantic retrieval.
"""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw_assistant_content: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ReportingResult:
    request_id: str
    status: str
    answer: str
    iterations: int
    cost_usd: float
    tool_calls: list[dict[str, Any]]


class ToolLoopLLM(Protocol):
    def next_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMTurn:
        ...


class ClaudeToolLoopClient:
    def __init__(self, *, model: str = HAIKU, max_tokens: int = 1600):
        self.model = model
        self.max_tokens = max_tokens

    def next_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMTurn:
        response = get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
        cost_usd = _cost_estimate(self.model, input_tokens, output_tokens)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        assistant_content: list[dict[str, Any]] = []
        for block in response.content:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text = str(getattr(block, "text", ""))
                text_parts.append(text)
                assistant_content.append({"type": "text", "text": text})
            elif block_type == "tool_use":
                tool_id = str(getattr(block, "id", ""))
                name = str(getattr(block, "name", ""))
                arguments = dict(getattr(block, "input", {}) or {})
                tool_calls.append(ToolCall(tool_id, name, arguments))
                assistant_content.append(
                    {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}
                )
        return LLMTurn(
            text="\n".join(part for part in text_parts if part).strip(),
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            raw_assistant_content=assistant_content,
        )


def run_reporting_agent(
    question: str,
    *,
    session=None,
    llm: Optional[ToolLoopLLM] = None,
    tools: Optional[ReportingTools] = None,
    tool_logger=None,
    request_id: Optional[str] = None,
    max_iterations: int = 10,
    usd_budget: float = 0.50,
) -> ReportingResult:
    request_id = request_id or str(uuid.uuid4())
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    if usd_budget < 0:
        raise ValueError("usd_budget cannot be negative")

    if session is None:
        with readonly_session() as owned_session:
            return run_reporting_agent(
                question,
                session=owned_session,
                llm=llm,
                tools=tools,
                tool_logger=tool_logger,
                request_id=request_id,
                max_iterations=max_iterations,
                usd_budget=usd_budget,
            )

    llm = llm or ClaudeToolLoopClient()
    reporting_tools = tools or ReportingTools(session)
    registry = reporting_tools.registry()
    logger_for_tools = tool_logger or QueryLogToolLogger(session)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    spent = 0.0
    call_trace: list[dict[str, Any]] = []

    for iteration in range(1, max_iterations + 1):
        turn = llm.next_turn(system=SYSTEM_PROMPT, messages=messages, tools=tool_schemas(registry))
        spent += float(turn.cost_usd)
        if spent > usd_budget:
            return ReportingResult(
                request_id=request_id,
                status="budget_exceeded",
                answer=(
                    f"Reporting agent stopped because the request cost ${spent:.4f} "
                    f"exceeded the ${usd_budget:.4f} budget."
                ),
                iterations=iteration,
                cost_usd=spent,
                tool_calls=call_trace,
            )

        if turn.raw_assistant_content:
            messages.append({"role": "assistant", "content": turn.raw_assistant_content})
        elif turn.text:
            messages.append({"role": "assistant", "content": turn.text})

        if not turn.tool_calls:
            return ReportingResult(
                request_id=request_id,
                status="succeeded",
                answer=turn.text,
                iterations=iteration,
                cost_usd=spent,
                tool_calls=call_trace,
            )

        tool_results = []
        for call in turn.tool_calls:
            call_trace.append({"iteration": iteration, "tool_name": call.name, "arguments": call.arguments})
            _log_tool(
                logger_for_tools,
                request_id=request_id,
                question=question,
                call=call,
                phase="call",
                iteration=iteration,
                payload={"arguments": call.arguments},
            )
            try:
                result = reporting_tools.call(call.name, call.arguments)
                payload = {"ok": True, "result": result}
                _log_tool(
                    logger_for_tools,
                    request_id=request_id,
                    question=question,
                    call=call,
                    phase="result",
                    iteration=iteration,
                    payload=payload,
                )
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
                _log_tool(
                    logger_for_tools,
                    request_id=request_id,
                    question=question,
                    call=call,
                    phase="error",
                    iteration=iteration,
                    payload=payload,
                )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload, sort_keys=True, default=str)[:12000],
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return ReportingResult(
        request_id=request_id,
        status="iteration_cap_exceeded",
        answer=f"Reporting agent stopped after max_iterations={max_iterations}.",
        iterations=max_iterations,
        cost_usd=spent,
        tool_calls=call_trace,
    )


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description="Run the GHUS reporting agent once.")
    parser.add_argument("question")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--usd-budget", type=float, default=0.50)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    args = parse_args(argv)
    result = run_reporting_agent(
        args.question,
        max_iterations=args.max_iterations,
        usd_budget=args.usd_budget,
    )
    print(result.answer)
    return 0 if result.status == "succeeded" else 2


def _log_tool(logger_for_tools, *, request_id: str, question: str, call: ToolCall, phase: str, iteration: int, payload: dict[str, Any]) -> None:
    logger_for_tools.log(
        ToolLogEntry(
            request_id=request_id,
            question=question,
            tool_name=call.name,
            phase=phase,
            iteration=iteration,
            payload=payload,
        )
    )


def _cost_estimate(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING.get(model)
    if not pricing:
        return 0.0
    return (
        input_tokens * float(pricing["input"]) + output_tokens * float(pricing["output"])
    ) / 1_000_000


if __name__ == "__main__":
    sys.exit(main())
