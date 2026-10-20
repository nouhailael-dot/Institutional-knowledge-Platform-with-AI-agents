from __future__ import annotations

import inspect

import anthropic
from anthropic.resources.messages import Messages

from agents.common.llm import (
    build_messages_create_kwargs,
    llm_usage_delta,
)


def test_anthropic_messages_payload_uses_only_pinned_sdk_params():
    kwargs = build_messages_create_kwargs(
        model="claude-haiku-4-5",
        system="Extract only explicit facts.",
        user="Source URL: fixture://example\n\n<html>Example</html>",
        tool_name="record_events",
        tool_description="Return events explicitly present in the source page.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        max_tokens=256,
    )

    assert anthropic.__version__ == "1.0.0"
    accepted = {
        name
        for name, param in inspect.signature(Messages.create).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY
    }

    assert set(kwargs) <= accepted
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_events"}


def test_cached_tool_payload_marks_only_the_stable_prefix_for_caching():
    kwargs = build_messages_create_kwargs(
        model="claude-sonnet-5",
        system="Stable system prompt",
        cached_user="Stable anchors, sectors, and hubs",
        user="Variable page content",
        tool_name="record_actor_rubric_and_record",
        tool_description="Stable tool description",
        input_schema={"type": "object", "properties": {}},
        max_tokens=256,
    )

    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["tools"][0]["cache_control"] == {"type": "ephemeral"}
    blocks = kwargs["messages"][0]["content"]
    assert blocks[0]["text"] == "Stable anchors, sectors, and hubs"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1] == {"type": "text", "text": "Variable page content"}


def test_llm_usage_delta_reports_token_weighted_cache_hit_rate():
    usage = llm_usage_delta(
        {
            "calls": 2,
            "input_tokens": 20,
            "output_tokens": 10,
            "cache_write_tokens": 100,
            "cache_read_tokens": 0,
        },
        {
            "calls": 5,
            "input_tokens": 50,
            "output_tokens": 25,
            "cache_write_tokens": 200,
            "cache_read_tokens": 300,
        },
    )

    assert usage["calls"] == 3
    assert usage["cache_write_tokens"] == 100
    assert usage["cache_read_tokens"] == 300
    assert usage["cache_hit_rate"] == 0.75
