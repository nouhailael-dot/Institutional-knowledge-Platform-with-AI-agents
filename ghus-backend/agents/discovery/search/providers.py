"""Search-provider adapters for open-web discovery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import parse, request

from agents.common.cost import CostMeter
from agents.discovery.search.models import SearchResult

WEB_SEARCH_TOOL_VERSION = "web_search_20250305"
WEB_SEARCH_USD_PER_REQUEST = 0.01


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, count: int = 10,
               allowed_domains: list[str] | None = None) -> list[SearchResult]:
        ...


@dataclass
class BraveSearchProvider:
    """Brave Search API client.

    API key values are read from the environment and never included in logs or
    exceptions. The client uses GET because Brave documents the web-search
    endpoint with query parameters and the x-subscription-token header.
    """

    api_key_env: str = "BRAVE_SEARCH_API_KEY"
    timeout_s: float = 20.0
    country: str = "US"
    search_lang: str = "en"
    endpoint: str = "https://api.search.brave.com/res/v1/web/search"
    name: str = "brave"

    def search(self, query: str, *, count: int = 10,
               allowed_domains: list[str] | None = None) -> list[SearchResult]:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"{self.api_key_env} is not set")
        clean_query = query.strip()
        if allowed_domains:
            # Brave has no domain parameter; its query language does.
            clean_query = f"{clean_query} ({' OR '.join(f'site:{d}' for d in allowed_domains)})"
        if not clean_query:
            raise ValueError("search query cannot be empty")
        params = parse.urlencode(
            {
                "q": clean_query,
                "count": max(1, min(int(count), 20)),
                "country": self.country,
                "search_lang": self.search_lang,
            }
        )
        req = request.Request(
            f"{self.endpoint}?{params}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            method="GET",
        )
        with request.urlopen(req, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))

        web_results = payload.get("web", {}).get("results", [])
        results: list[SearchResult] = []
        for item in web_results:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=str(item.get("title") or "").strip(),
                    snippet=str(item.get("description") or item.get("snippet") or "").strip(),
                    provider=self.name,
                    query=clean_query,
                )
            )
        return results


@dataclass
class ClaudeWebSearchProvider:
    """Anthropic server-side web search provider.

    Only structured web-search result blocks are converted to SearchResult
    objects. Assistant text/commentary is intentionally ignored because searched
    pages are untrusted input.
    """

    model: str
    cost_meter: CostMeter
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0
    web_search_usd_per_request: float = WEB_SEARCH_USD_PER_REQUEST
    max_uses: int = 1
    tool_version: str = WEB_SEARCH_TOOL_VERSION
    client: Any | None = None
    name: str = "claude"

    def search(self, query: str, *, count: int = 10,
               allowed_domains: list[str] | None = None) -> list[SearchResult]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("search query cannot be empty")
        tool = {
            "type": self.tool_version,
            "name": "web_search",
            "max_uses": max(1, int(self.max_uses)),
            "allowed_callers": ["direct"],
        }
        if allowed_domains:
            # Only these sites (and their subdomains) are searched.
            tool["allowed_domains"] = [str(d) for d in allowed_domains]
        response = self._client().messages.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Run one web search for this query and return the most relevant results. "
                        "Do not add commentary.\n\n"
                        f"Query: {clean_query}"
                    ),
                }
            ],
            tools=[tool],
        )
        self._record_usage(response)
        return self._extract_results(response, query=clean_query, count=count)

    def _client(self):
        if self.client is not None:
            return self.client
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        from anthropic import Anthropic

        self.client = Anthropic()
        return self.client

    def _record_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        token_cost = (
            input_tokens * self.input_usd_per_million
            + output_tokens * self.output_usd_per_million
        ) / 1_000_000
        requests_used = _web_search_request_count(usage)
        search_cost = requests_used * float(self.web_search_usd_per_request)
        self.cost_meter.add(token_cost, label=f"claude:{self.model}:tokens")
        self.cost_meter.add(search_cost, label=f"claude:{self.tool_version}")

    def _extract_results(self, response, *, query: str, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for block in getattr(response, "content", []) or []:
            block_data = _object_to_dict(block)
            if block_data.get("type") != "web_search_tool_result":
                continue
            content = block_data.get("content") or []
            if not isinstance(content, list):
                continue
            for item in content:
                item_data = _object_to_dict(item)
                if item_data.get("type") != "web_search_result":
                    continue
                url = str(item_data.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(
                    SearchResult(
                        url=url,
                        title=str(item_data.get("title") or "").strip(),
                        snippet=_web_result_snippet(item_data),
                        provider=self.name,
                        query=query,
                    )
                )
                if len(results) >= int(count):
                    return results
        return results


def build_search_provider(
    config: dict[str, object],
    *,
    cost_meter: CostMeter | None = None,
    client: Any | None = None,
) -> SearchProvider:
    provider_name = str(config.get("provider") or "").strip().lower()
    if provider_name == "claude":
        if cost_meter is None:
            raise RuntimeError("Claude search provider requires a cost meter")
        pricing = dict(config.get("search_llm_pricing") or config.get("llm_pricing", {}))
        return ClaudeWebSearchProvider(
            model=str(config.get("search_model") or config.get("claude_model", "claude-haiku-4-5")),
            cost_meter=cost_meter,
            input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
            output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
            web_search_usd_per_request=float(
                config.get("web_search_usd_per_request", WEB_SEARCH_USD_PER_REQUEST)
            ),
            max_uses=int(config.get("web_search_max_uses", 1)),
            tool_version=str(config.get("web_search_tool_version", WEB_SEARCH_TOOL_VERSION)),
            client=client,
        )
    if provider_name == "brave":
        return BraveSearchProvider(
            api_key_env=str(config.get("brave_api_key_env") or "BRAVE_SEARCH_API_KEY"),
            timeout_s=float(config.get("timeout_s", 20.0)),
            country=str(config.get("country") or "US"),
            search_lang=str(config.get("search_lang") or "en"),
        )
    raise ValueError(f"unsupported search provider {provider_name!r}")


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    data: dict[str, Any] = {}
    for attr in ("type", "content", "url", "title", "snippet", "description", "page_age"):
        if hasattr(value, attr):
            data[attr] = getattr(value, attr)
    return data


def _web_result_snippet(item: dict[str, Any]) -> str:
    for key in ("snippet", "description", "page_age"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def _web_search_request_count(usage: Any) -> int:
    server_tool_use = getattr(usage, "server_tool_use", None)
    if server_tool_use is None and isinstance(usage, dict):
        server_tool_use = usage.get("server_tool_use")
    if server_tool_use is None:
        return 0
    if isinstance(server_tool_use, dict):
        return int(server_tool_use.get("web_search_requests", 0) or 0)
    return int(getattr(server_tool_use, "web_search_requests", 0) or 0)


def _usage_int(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        return int(usage.get(key, 0) or 0)
    return int(getattr(usage, key, 0) or 0)
