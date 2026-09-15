"""Bounded Claude search and page reads. No redirects or automatic retries.

Claude web search is $10/1000 searches plus model tokens (checked 2026-09-13).
Every request hard-caps `max_uses` at one. Ambiguous responses retain their
whole budget reservation and are never retried automatically.
"""
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import anthropic
from dotenv import load_dotenv

from src.map_agent.costs import paid_message

MAX_BYTES = 1_000_000
MAX_PAGE_CHARS = 24_000
load_dotenv()


def operation_key(kind, value):
    return kind + ":" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def availability():
    if os.environ.get("MAP_RESEARCH_ENABLED") != "1":
        return False, "Live research is disabled until a controlled test is approved."
    if os.environ.get("MAP_SEARCH_PROVIDER", "claude").lower() != "claude":
        return False, "This build is configured to use Claude web search only."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "The Claude API key is not configured."
    return True, ""


def canonical_url(url):
    parts = urlsplit(url)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.port not in (None, 80, 443)):
        raise ValueError("Only public HTTP(S) pages on standard ports are supported")
    if any(ord(c) < 33 for c in url):
        raise ValueError("Invalid URL")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    netloc = "[" + host + "]" if ":" in host else host
    if parts.port:
        netloc += ":" + str(parts.port)
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def plain_text(value):
    parser = PageText()
    parser.feed(value)
    return "\n".join(parser.parts)


def fetch_page(url):
    """Pin a validated public IP to prevent DNS rebinding; TLS still checks hostname.

    No environment proxies, cookies, authorization, redirects, JS, or downloads.
    Redirects/unsupported pages are reported as gaps, not bypassed.
    """
    url = canonical_url(url)
    parts = urlsplit(url)
    host, port = parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Non-public destination blocked")
    family, socktype, proto, _, address = addresses[0]
    conn = http.client.HTTPConnection(host, port, timeout=12)
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(12)
    try:
        sock.connect(address)  # Uses the validated address; never resolves again.
        if parts.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        conn.sock = sock
        conn.request("GET", urlunsplit(("", "", parts.path or "/", parts.query, "")),
                     headers={"User-Agent": "UM6P-MapResearch/1.0", "Accept": "text/html,text/plain",
                              "Accept-Encoding": "identity"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Page returned HTTP " + str(response.status) + "; not followed")
        mime = response.getheader("Content-Type", "").lower()
        if not any(t in mime for t in ("text/html", "text/plain", "application/xhtml+xml")):
            raise ValueError("Unsupported page type")
        if response.getheader("Content-Encoding", "identity") not in ("", "identity"):
            raise ValueError("Compressed page skipped")
        # Both byte and elapsed-time limits; never execute page content.
        data, deadline = bytearray(), time.monotonic() + 20
        while len(data) <= MAX_BYTES:
            if time.monotonic() > deadline:
                raise TimeoutError("Page read deadline reached")
            chunk = response.read1(min(16384, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        text = bytes(data[:MAX_BYTES]).decode("utf-8", errors="replace")
        text = plain_text(text) if "html" in mime else text
        return {"url": url, "text": text[:MAX_PAGE_CHARS], "kind": "page",
                "truncated": len(data) > MAX_BYTES or len(text) > MAX_PAGE_CHARS}
    finally:
        conn.close()
        sock.close()


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


class ClaudeSearch:
    tracked = True

    def __init__(self, run, client=None):
        self.run = run
        self.client = client or anthropic.Anthropic()

    def search(self, query):
        key = operation_key("claude-search-v1", query.casefold())
        response = paid_message(self.client, self.run, "Web search", operation_key=key,
            model="claude-sonnet-5", max_tokens=1200,
            system=("Run exactly one web search using the user's query. Return a concise, "
                    "source-cited overview of the strongest relevant results. Do not broaden "
                    "the query and do not attempt another search if the first is insufficient."),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1,
                    "allowed_callers": ["direct"]}],
            messages=[{"role": "user", "content": "SEARCH QUERY:\n" + query}])
        by_url = {}

        def add(item, text=""):
            try:
                url = canonical_url(_field(item, "url", ""))
            except (ValueError, TypeError):
                return
            row = by_url.setdefault(url, {"url": url, "title": str(_field(item, "title", ""))[:300],
                                          "text": "", "kind": "search_snippet"})
            snippet = plain_text(str(text or ""))[:5000]
            if snippet and snippet not in row["text"]:
                row["text"] = (row["text"] + "\n" + snippet).strip()[:5000]

        for block in response.content:
            if _field(block, "type") == "web_search_tool_result":
                content = _field(block, "content", [])
                if isinstance(content, list):
                    for item in content[:10]:
                        add(item, _field(item, "cited_text", ""))
            if _field(block, "type") == "text":
                for citation in _field(block, "citations", []) or []:
                    if _field(citation, "type") == "web_search_result_location":
                        add(citation, _field(citation, "cited_text", ""))
        return list(by_url.values())[:10]


class ResearchSources:
    """Per-map persistent cache; no cross-user or stale cross-map evidence reuse."""
    def __init__(self, run, provider=None, fetcher=None):
        self.run = run
        self.provider = provider or ClaudeSearch(run)
        self.fetcher = fetcher or fetch_page

    def search(self, query):
        self.run.check()
        query = re.sub(r"\s+", " ", query).strip()[:400]
        if getattr(self.provider, "tracked", False) is True:
            return self.provider.search(query)
        key = operation_key("search-v1", query.casefold())
        saved = self.run.store.operation(self.run.id, key)
        if saved is not None:
            return saved["results"]
        # Test/local adapters still use a fixed simulated search price so the
        # budget/caching behavior can be exercised without any network calls.
        call = self.run.store.reserve(self.run.id, "Web search", "test-search",
                5_000, {"per_request_usd": .005, "date": "simulated"},
                operation_key=key, attempt=self.run.attempt)
        try:
            self.run.check()
        except Exception:
            self.run.store.settle(call, 0, {}, None, "Cancelled before dispatch")
            raise
        try:
            results = self.provider.search(query)
        except Exception as exc:
            self.run.store.settle(call, None, None, None, type(exc).__name__)
            raise
        self.run.store.settle(call, 5_000, {"search_requests": 1}, {"results": results})
        return results

    def page(self, url):
        self.run.check()
        try:
            url = canonical_url(url)
        except ValueError:
            return {"url": url, "text": "", "error": "Unsupported URL"}
        key = operation_key("page-v1", url)
        saved = self.run.store.cached(self.run.id, key)
        if saved is not None:
            return saved
        try:
            result = self.fetcher(url)
        except Exception as exc:
            result = {"url": url, "text": "", "error": type(exc).__name__ + ": page unavailable"}
        # Failed reads are cached too: no repeat attempts during this map.
        self.run.store.cache(self.run.id, key, result)
        return result


def excerpt(page, query, limit=3500):
    """Retain an introduction and relevant paragraphs, within a fixed input size."""
    text = page.get("text", "")
    words = set(re.findall(r"[a-z]{4,}", query.lower()))
    chunks = [text[i:i+700] for i in range(0, len(text), 700)]
    if not chunks:
        return {**page, "text": ""}
    ranked = sorted(range(1, len(chunks)), key=lambda i: -sum(w in chunks[i].lower() for w in words))
    indices = sorted([0] + ranked[:max(0, limit // 700 - 1)])
    return {**page, "text": "\n[…]\n".join(chunks[i] for i in indices)[:limit]}
