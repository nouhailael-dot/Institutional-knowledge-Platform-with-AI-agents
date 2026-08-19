"""Climate Week public-events source adapter."""

from __future__ import annotations

import html.parser
import os
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from agents.discovery.sources.base import FetchedDoc


class _EventLinkParser(html.parser.HTMLParser):
    def __init__(self, base_url: str, patterns: list[str]):
        super().__init__()
        self.base_url = base_url
        self.patterns = [pattern.lower() for pattern in patterns]
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        lowered = absolute.lower()
        if any(pattern in lowered for pattern in self.patterns) and absolute not in self.links:
            self.links.append(absolute)


class ClimateWeekAdapter:
    name = "climate_week"
    entity_types = ("event",)

    def __init__(self, config: dict[str, object], *, project_root: Path | None = None, offline: bool = False):
        self.config = config
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.timeout_s = float(config.get("timeout_s", 20.0))
        self.max_retries = int(config.get("max_retries", 3))
        self.calendar_url = str(config.get("calendar_url", ""))
        self.fixture_urls = [str(url) for url in config.get("fixture_urls", [])] if offline else []
        self.fixtures = {str(k): str(v) for k, v in dict(config.get("fixtures", {})).items()}
        self.link_patterns = [str(item) for item in config.get("event_link_patterns", ["event"])]
        self._last_request_at = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        self._client = httpx.Client(timeout=self.timeout_s, follow_redirects=True)

    def discover(self) -> Iterator[str]:
        if self.fixture_urls:
            yield from self.fixture_urls
            return
        if not self.calendar_url:
            raise RuntimeError("climate_week calendar_url is not configured")
        calendar_doc = self.fetch(self.calendar_url)
        parser = _EventLinkParser(self.calendar_url, self.link_patterns)
        parser.feed(calendar_doc.content)
        if parser.links:
            yield from parser.links
        else:
            yield self.calendar_url

    def fetch(self, url: str) -> FetchedDoc:
        if url.startswith("fixture://"):
            path_value = self.fixtures.get(url)
            if not path_value:
                raise RuntimeError(f"no fixture path configured for {url}")
            path = self._resolve_path(path_value)
            content = path.read_text(encoding="utf-8")
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path)},
            )

        if url.startswith("file://"):
            path = Path(urlparse(url).path)
            content = path.read_text(encoding="utf-8")
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path)},
            )

        if self.offline:
            raise RuntimeError("offline source adapter cannot fetch network URLs")
        if not self._robots_allowed(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        response = self._request(url)
        if 400 <= response.status_code < 500:
            response.raise_for_status()
        response.raise_for_status()
        return FetchedDoc.from_content(
            url=str(response.url),
            content=response.text,
            content_type=response.headers.get("content-type", "text/html"),
            meta={"status_code": response.status_code},
        )

    def _request(self, url: str) -> httpx.Response:
        headers = {"User-Agent": self._user_agent()}
        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._client.get(url, headers=headers)
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

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
            response = self._request(robots_url)
            parser = RobotFileParser()
            if response.status_code == 404:
                parser.parse([])
            elif 400 <= response.status_code < 500:
                response.raise_for_status()
            else:
                response.raise_for_status()
                parser.parse(response.text.splitlines())
            self._robots[base] = parser
        return self._robots[base].can_fetch(self._user_agent(), url)

    def _user_agent(self) -> str:
        product = str(self.config.get("user_agent_product", "GHUS-AgentDiscovery/0.1"))
        env_name = str(self.config.get("contact_email_env", "GHUS_AGENT_CONTACT_EMAIL"))
        contact = os.environ.get(env_name) or str(self.config.get("contact_email", "")).strip()
        if not contact and not self.fixture_urls:
            raise RuntimeError(f"set {env_name} before network discovery")
        return f"{product} ({contact or 'offline-fixture-run'})"

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        return path
