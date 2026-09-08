"""Shared HTTP helpers for discovery source adapters."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx


class RobotsAwareHttp:
    def __init__(self, config: dict[str, object], *, offline: bool = False):
        self.config = config
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.timeout_s = float(config.get("timeout_s", 20.0))
        self.max_retries = int(config.get("max_retries", 3))
        self.max_redirects = int(config.get("max_redirects", 5))
        self.strict_redirect_robots = bool(config.get("strict_redirect_robots", False))
        self._last_request_at = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.Client(
            timeout=self.timeout_s,
            follow_redirects=not self.strict_redirect_robots,
        )

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
        if url.startswith(("fixture://", "file://")):
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
        if self.strict_redirect_robots:
            return self._get_with_strict_redirect_robots(url)
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
            response = self._robots_response(robots_url)
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

    def _get_with_strict_redirect_robots(self, url: str) -> httpx.Response:
        current_url = url
        for _hop in range(self.max_redirects + 1):
            if not self.robots_allowed(current_url):
                raise RuntimeError(f"robots.txt disallows fetching {current_url}")
            response = self._request("GET", current_url)
            if response.status_code not in {301, 302, 303, 307, 308}:
                if 400 <= response.status_code < 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            location = response.headers.get("location")
            if not location:
                raise RuntimeError(f"redirect response for {current_url} has no Location header")
            current_url = urljoin(current_url, location)
        raise RuntimeError(f"redirect limit exceeded while fetching {url}")

    def _robots_response(self, robots_url: str) -> httpx.Response:
        current_url = robots_url
        for _hop in range(self.max_redirects + 1):
            response = self._request("GET", current_url)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                raise RuntimeError(f"redirect response for {current_url} has no Location header")
            current_url = urljoin(current_url, location)
        raise RuntimeError(f"redirect limit exceeded while fetching {robots_url}")

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
