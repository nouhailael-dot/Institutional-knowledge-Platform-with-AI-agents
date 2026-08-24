"""Official UN General Assembly high-level meetings programme source."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp, read_fixture


class UngaProgrammeAdapter:
    name = "unga_programme"
    entity_types = ("event",)

    def __init__(self, config: dict[str, object], *, project_root: Path | None = None, offline: bool = False):
        self.config = config
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.offline = offline
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.meeting_url = str(config.get("meeting_url") or "").strip()
        self.seed_urls = [str(url) for url in config.get("seed_urls", [])]
        self.fixture_urls = [str(url) for url in config.get("fixture_urls", [])] if offline else []
        self.fixtures = {str(k): str(v) for k, v in dict(config.get("fixtures", {})).items()}
        self.http = RobotsAwareHttp(config, offline=offline)

    def discover(self) -> Iterator[str]:
        if self.fixture_urls:
            yield from self.http.dedupe_after_redirects(self.fixture_urls)
            return
        candidates = self.seed_urls or [self.meeting_url]
        if not all(candidates):
            raise RuntimeError("unga_programme meeting_url is not configured")
        yield from self.http.dedupe_after_redirects(candidates)

    def fetch(self, url: str) -> FetchedDoc:
        if url.startswith("fixture://"):
            content, path = read_fixture(self.project_root, self.fixtures, url)
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path), "source_name": self.name},
            )
        if url.startswith("file://"):
            path = Path(urlparse(url).path)
            content = path.read_text(encoding="utf-8")
            return FetchedDoc.from_content(
                url=url,
                content=content,
                content_type="text/html",
                meta={"fixture_path": str(path), "source_name": self.name},
            )

        response = self.http.get(url)
        return FetchedDoc.from_content(
            url=str(response.url),
            content=response.text,
            content_type=response.headers.get("content-type", "text/html"),
            meta={"status_code": response.status_code, "source_name": self.name},
        )
