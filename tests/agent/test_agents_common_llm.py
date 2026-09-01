from __future__ import annotations

import inspect

import anthropic
from anthropic.resources.messages import Messages

from agents.common.llm import build_messages_create_kwargs


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
