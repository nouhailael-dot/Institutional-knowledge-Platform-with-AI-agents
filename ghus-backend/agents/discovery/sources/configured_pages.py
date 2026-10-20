"""Configured single-page source adapter for discovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.http_utils import RobotsAwareHttp, read_fixture


class ConfiguredPagesAdapter:
    """Fetch explicit URLs listed in sources.yaml.

    This adapter is intentionally small: it owns URL discovery and raw fetches
    only. Entity extraction still belongs to the entity-specific extractor.
    """

    def __init__(
        self, config: dict[str, object], *, project_root: Path | None = None, offline: bool = False
    ):
        self.config = config
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.offline = offline
        self.name = str(config.get("source_name") or "configured_pages")
        self.entity_types = tuple(str(value) for value in config.get("entity_types", []))
        if not self.entity_types:
            raise RuntimeError(f"{self.name} must configure at least one entity type")
        self.rate_limit_s = float(config.get("rate_limit_s", 1.0))
        self.seed_urls = [str(url) for url in config.get("seed_urls", [])]
        self.fixture_urls = [str(url) for url in config.get("fixture_urls", [])] if offline else []
        self.fixtures = {str(k): str(v) for k, v in dict(config.get("fixtures", {})).items()}
        self.http = RobotsAwareHttp(config, offline=offline)

    def discover(self) -> Iterator[str]:
        candidates = self.fixture_urls if self.fixture_urls else self.seed_urls
        if not candidates:
            raise RuntimeError(f"{self.name} has no seed_urls configured")
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
            path = Path(url2pathname(urlparse(url).path))
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
