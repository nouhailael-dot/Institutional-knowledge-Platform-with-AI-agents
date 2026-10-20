"""Climate Week public event-search source adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp, read_fixture


class ClimateWeekAdapter:
    name = "climate_week"
    entity_types = ("event",)

    def __init__(self, config: dict[str, object], *, project_root: Path | None = None, offline: bool = False):
        self.config = config
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.listing_url = str(config.get("listing_url") or config.get("calendar_url") or "").strip()
        self.fixture_urls = [str(url) for url in config.get("fixture_urls", [])] if offline else []
        self.fixtures = {str(k): str(v) for k, v in dict(config.get("fixtures", {})).items()}
        self.pagination_urls = [str(url) for url in config.get("pagination_urls", [])]
        self.http = RobotsAwareHttp(config, offline=offline)

    def discover(self) -> Iterator[str]:
        if self.fixture_urls:
            yield from self._dedupe_resolved(self.fixture_urls)
            return
        if not self.listing_url:
            raise RuntimeError("climate_week listing_url is not configured")
        candidates = [self.listing_url, *self.pagination_urls]
        for url in self._dedupe_resolved(candidates):
            _assert_event_search_url(url)
            yield url

    def fetch(self, url: str) -> FetchedDoc:
        if url.startswith("fixture://"):
            content, path = read_fixture(self.project_root, self.fixtures, url)
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={
                    "fixture_path": str(path),
                    "source_name": self.name,
                    "extractor_mode": "hubdb_listing",
                },
            )
        if url.startswith("file://"):
            path = Path(urlparse(url).path)
            content = path.read_text(encoding="utf-8")
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={
                    "fixture_path": str(path),
                    "source_name": self.name,
                    "extractor_mode": "hubdb_listing",
                },
            )

        response = self.http.get(url)
        return FetchedDoc.from_content(
            url=str(response.url),
            content=response.text,
            content_type=response.headers.get("content-type", "text/html"),
            meta={
                "status_code": response.status_code,
                "source_name": self.name,
                "extractor_mode": "hubdb_listing",
            },
        )

    def _dedupe_resolved(self, urls: list[str]) -> Iterator[str]:
        yield from self.http.dedupe_after_redirects(urls)


def _assert_event_search_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.path.rstrip("/") != "/event-search":
        raise RuntimeError(f"climate_week discovery must stay on /event-search, got {url}")
