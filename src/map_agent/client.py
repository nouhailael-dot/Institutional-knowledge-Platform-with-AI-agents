"""Lazy Claude client for map extraction. Creating a client makes no API request."""
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()
_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic()
    return _client
