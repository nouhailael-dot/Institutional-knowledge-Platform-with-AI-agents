"""Shared HTTP helpers for discovery source adapters."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx


class RobotsAwareHttp:
    def __init__(self, config: dict[str, object], *, offline: bool = False):
        self.config = config
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.timeout_s = float(config.get("timeout_s", 20.0))
        self.max_retries = int(config.get("max_retries", 3))
        self._last_request_at = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.Client(timeout=self.timeout_s, follow_redirects=True)

    def dedupe_after_redirects(self, urls: Iterable[str]) -> Iterator[str]:
        seen: set[str] = set()
        for url in urls:
            final_url = self.resolve_url(url)
            key = _canonical_url_key(final_url)
            if key in seen:
                continue
            seen.add(key)
            yield final_url

    def resolve_url(self, url: str) -> str:
        if url.startswith("fixture://") or url.startswith("file://"):
            return url
        if self.offline:
            raise RuntimeError("offline source adapter cannot resolve network URLs")
        if not self.robots_allowed(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        response = self._request("HEAD", url)
        if response.status_code in {405, 501}:
            response = self._request("GET", url)
        if 400 <= response.status_code < 500:
            response.raise_for_status()
        response.raise_for_status()
        return str(response.url)

    def get(self, url: str) -> httpx.Response:
        if self.offline:
            raise RuntimeError("offline source adapter cannot fetch network URLs")
        if not self.robots_allowed(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        response = self._request("GET", url)
        if 400 <= response.status_code < 500:
            response.raise_for_status()
        response.raise_for_status()
        return response

    def robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
            response = self._request("GET", robots_url)
            parser = RobotFileParser()
            if response.status_code == 404:
                parser.parse([])
            elif 400 <= response.status_code < 500:
                response.raise_for_status()
            else:
                response.raise_for_status()
                parser.parse(response.text.splitlines())
            self._robots[base] = parser
        return self._robots[base].can_fetch(self.user_agent(), url)

    def user_agent(self) -> str:
        product = str(self.config.get("user_agent_product", "GHUS-AgentDiscovery/0.1"))
        env_name = str(self.config.get("contact_email_env", "GHUS_AGENT_CONTACT_EMAIL"))
        contact = os.environ.get(env_name) or str(self.config.get("contact_email", "")).strip()
        if not contact and not self.offline:
            raise RuntimeError(f"set {env_name} before network discovery")
        contact_part = contact or "offline-fixture-run"
        if bool(self.config.get("browser_like_user_agent", False)):
            return (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/126.0 Safari/537.36 {product} ({contact_part})"
            )
        return f"{product} ({contact_part})"

    def _request(self, method: str, url: str) -> httpx.Response:
        headers = {"User-Agent": self.user_agent()}
        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._client.request(method, url, headers=headers)
            except httpx.TimeoutException:
                if attempt >= self.max_retries:
                    raise
                time.sleep(2 ** attempt)
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            return response
        raise RuntimeError("unreachable retry state")

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        self._last_request_at = time.monotonic()


def read_fixture(project_root: Path, fixtures: dict[str, str], url: str) -> tuple[str, Path]:
    path_value = fixtures.get(url)
    if not path_value:
        raise RuntimeError(f"no fixture path configured for {url}")
    path = Path(path_value)
    if not path.is_absolute():
        path = project_root / path
    return path.read_text(encoding="utf-8"), path


def _canonical_url_key(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))
