"""UNGA Guide source adapter.

Selectors here are intentionally minimal. Revisit them once the public guide's
event listing markup stabilizes for the active UNGA edition.
"""

from __future__ import annotations

import html.parser
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp, read_fixture


class _LinkParser(html.parser.HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        if absolute not in self.links:
            self.links.append(absolute)


class UngaGuideAdapter:
    name = "unga_guide"
    entity_types = ("event",)

    def __init__(self, config: dict[str, object], *, project_root: Path | None = None, offline: bool = False):
        self.config = config
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.listing_url = str(config.get("listing_url") or "").strip()
        self.seed_urls = [str(url) for url in config.get("seed_urls", [])]
        self.fixture_urls = [str(url) for url in config.get("fixture_urls", [])] if offline else []
        self.fixtures = {str(k): str(v) for k, v in dict(config.get("fixtures", {})).items()}
        self.coming_soon_markers = [str(value).lower() for value in config.get("coming_soon_markers", ["coming soon"])]
        self.http = RobotsAwareHttp(config, offline=offline)
        self.last_discovery_reason = ""
        self._doc_cache: dict[str, FetchedDoc] = {}

    def discover(self) -> Iterator[str]:
        self.last_discovery_reason = ""
        if self.fixture_urls:
            yield from self.http.dedupe_after_redirects(self.fixture_urls)
            return
        candidates = self.seed_urls or [self.listing_url]
        if not all(candidates):
            raise RuntimeError("unga_guide listing_url is not configured")

        discovered: list[str] = []
        for url in self.http.dedupe_after_redirects(candidates):
            doc = self.fetch(url)
            if _is_coming_soon(doc.content, self.coming_soon_markers):
                self.last_discovery_reason = "UNGA Guide page is published as coming soon; no event URLs discovered"
                continue
            discovered.append(url)
            discovered.extend(_pagination_links(url, doc.content))
        if not discovered and not self.last_discovery_reason:
            self.last_discovery_reason = "UNGA Guide discovery found no listing URLs"
        yield from self.http.dedupe_after_redirects(discovered)

    def fetch(self, url: str) -> FetchedDoc:
        cached = self._doc_cache.get(url)
        if cached is not None:
            return cached
        if url.startswith("fixture://"):
            content, path = read_fixture(self.project_root, self.fixtures, url)
            doc = FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path), "source_name": self.name},
            )
            self._doc_cache[url] = doc
            return doc
        if url.startswith("file://"):
            path = Path(urlparse(url).path)
            content = path.read_text(encoding="utf-8")
            doc = FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path), "source_name": self.name},
            )
            self._doc_cache[url] = doc
            return doc

        response = self.http.get(url)
        doc = FetchedDoc.from_content(
            url=str(response.url),
            content=response.text,
            content_type=response.headers.get("content-type", "text/html"),
            meta={"status_code": response.status_code, "source_name": self.name},
        )
        self._doc_cache[str(response.url)] = doc
        return doc


def _is_coming_soon(content: str, markers: list[str]) -> bool:
    lowered = content.lower()
    return any(marker in lowered for marker in markers) and "search through" not in lowered


def _pagination_links(base_url: str, content: str) -> list[str]:
    parser = _LinkParser(base_url)
    parser.feed(content)
    base = urlparse(base_url)
    explicit_links: list[str] = []
    page_numbers: set[int] = set()
    for link in parser.links:
        parsed = urlparse(link)
        if parsed.netloc != base.netloc:
            continue
        page_match = re.search(r"/page/(\d+)/?$", parsed.path)
        if page_match:
            page_numbers.add(int(page_match.group(1)))
            continue
        if "page" in parsed.query.lower():
            explicit_links.append(link)
    if page_numbers:
        max_page = max(page_numbers)
        return [f"{base.scheme}://{base.netloc}/page/{page}/" for page in range(2, max_page + 1)]
    return explicit_links
