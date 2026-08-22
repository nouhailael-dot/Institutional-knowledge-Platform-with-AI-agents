"""Fetch discovery source pages and report their real HTML shape.

This CLI is diagnostic-only: no database writes, no staging, and no LLM calls.
"""

from __future__ import annotations

import argparse
import html
import html.parser
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from agents.discovery.run import build_source, load_config, project_root

logger = logging.getLogger(__name__)

DEFAULT_SELECTORS = {
    "climate_week": {
        "listing_container_selector": ".hubdb-listing",
        "item_selector": "article.event-card",
    },
    "unga_guide": {
        "listing_container_selector": "main",
        "item_selector": "article",
    },
    "unga_programme": {
        "listing_container_selector": "main",
        "item_selector": "li",
    },
}


@dataclass(frozen=True)
class SelectorSpec:
    raw: str
    tag: Optional[str] = None
    class_name: Optional[str] = None
    element_id: Optional[str] = None
    attr_name: Optional[str] = None
    attr_value: Optional[str] = None

    @classmethod
    def parse(cls, value: str) -> "SelectorSpec":
        raw = value.strip()
        if not raw:
            raise ValueError("selector cannot be empty")
        attr_name = None
        attr_value = None
        tag_part = raw
        attr_match = re.search(r"\[([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:=['\"]?([^'\"]+)['\"]?)?\]$", raw)
        if attr_match:
            attr_name = attr_match.group(1).lower()
            attr_value = attr_match.group(2)
            tag_part = raw[: attr_match.start()]
        element_id = None
        if "#" in tag_part:
            tag_part, element_id = tag_part.split("#", 1)
        class_name = None
        if "." in tag_part:
            tag_part, class_name = tag_part.split(".", 1)
        tag = tag_part.lower() or None
        return cls(
            raw=raw,
            tag=tag,
            class_name=class_name,
            element_id=element_id,
            attr_name=attr_name,
            attr_value=attr_value,
        )

    def matches(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        tag_lower = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}
        if self.tag and self.tag != tag_lower:
            return False
        if self.class_name and self.class_name not in set(attr_map.get("class", "").split()):
            return False
        if self.element_id and attr_map.get("id") != self.element_id:
            return False
        if self.attr_name:
            if self.attr_name not in attr_map:
                return False
            if self.attr_value is not None and attr_map.get(self.attr_name) != self.attr_value:
                return False
        return True


class DiagnosticHtmlParser(html.parser.HTMLParser):
    def __init__(self, *, listing_selector: str, item_selector: str):
        super().__init__(convert_charrefs=False)
        self.listing_spec = SelectorSpec.parse(listing_selector)
        self.item_spec = SelectorSpec.parse(item_selector)
        self.class_values: Counter[str] = Counter()
        self.listing_count = 0
        self.item_count = 0
        self.listing_outer_html: list[str] = []
        self.item_outer_html: list[str] = []
        self._captures: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count_class_values(attrs)
        start_text = self.get_starttag_text() or _start_tag(tag, attrs)
        self._append_to_captures(start_text)
        if self.listing_spec.matches(tag, attrs):
            self.listing_count += 1
            self._start_capture("listing", start_text)
        if self.item_spec.matches(tag, attrs):
            self.item_count += 1
            self._start_capture("item", start_text)
        self._increase_capture_depths()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count_class_values(attrs)
        text = self.get_starttag_text() or _start_tag(tag, attrs, closed=True)
        self._append_to_captures(text)
        if self.listing_spec.matches(tag, attrs):
            self.listing_count += 1
            self._store_capture("listing", text)
        if self.item_spec.matches(tag, attrs):
            self.item_count += 1
            self._store_capture("item", text)

    def handle_endtag(self, tag: str) -> None:
        text = f"</{tag.lower()}>"
        self._append_to_captures(text)
        remaining = []
        for capture in self._captures:
            capture["depth"] = int(capture["depth"]) - 1
            if int(capture["depth"]) <= 0:
                self._store_capture(str(capture["kind"]), str(capture["text"]))
            else:
                remaining.append(capture)
        self._captures = remaining

    def handle_data(self, data: str) -> None:
        self._append_to_captures(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        self._append_to_captures(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_to_captures(f"&#{name};")

    def _count_class_values(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() == "class" and value:
                self.class_values[value.strip()] += 1

    def _start_capture(self, kind: str, text: str) -> None:
        if kind == "listing" and len(self.listing_outer_html) >= 2:
            return
        if kind == "item" and len(self.item_outer_html) >= 2:
            return
        self._captures.append({"kind": kind, "depth": 0, "text": text})

    def _increase_capture_depths(self) -> None:
        for capture in self._captures:
            capture["depth"] = int(capture["depth"]) + 1

    def _append_to_captures(self, text: str) -> None:
        for capture in self._captures:
            current = str(capture["text"])
            if len(current) < 2000:
                capture["text"] = current + text

    def _store_capture(self, kind: str, text: str) -> None:
        target = self.listing_outer_html if kind == "listing" else self.item_outer_html
        if len(target) < 2:
            target.append(_truncate(text, 500))


def diagnose_source(source_name: str, *, root: Path, limit: Optional[int] = None) -> list[dict[str, object]]:
    config = load_config(root)
    source, source_config = build_source(source_name, config, root, offline=False)
    diagnostic_config = {
        **DEFAULT_SELECTORS.get(source_name, {}),
        **dict(source_config.get("diagnostics", {}) or {}),
    }
    listing_selector = str(diagnostic_config.get("listing_container_selector") or "body")
    item_selector = str(diagnostic_config.get("item_selector") or listing_selector)
    output_dir = root / "agents" / "diagnostics" / source_name
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    urls = list(source.discover())
    if limit is not None:
        urls = urls[:limit]
    if not urls:
        return [
            {
                "source": source_name,
                "error": getattr(source, "last_discovery_reason", "") or "source discovered zero URLs",
                "listing_selector": listing_selector,
                "item_selector": item_selector,
            }
        ]

    for index, url in enumerate(urls, start=1):
        try:
            doc = source.fetch(url)
            page_path = output_dir / f"{index:02d}_{_safe_filename(doc.url)}.html"
            page_path.write_text(doc.content, encoding="utf-8", newline="")
            parser = DiagnosticHtmlParser(listing_selector=listing_selector, item_selector=item_selector)
            parser.feed(doc.content)
            rows.append(
                {
                    "source": source_name,
                    "requested_url": url,
                    "final_url": doc.url,
                    "status": doc.meta.get("status_code", ""),
                    "byte_count": len(doc.content.encode("utf-8")),
                    "content_type": doc.content_type,
                    "listing_selector": listing_selector,
                    "listing_count": parser.listing_count,
                    "item_selector": item_selector,
                    "item_count": parser.item_count,
                    "listing_outer_html": parser.listing_outer_html,
                    "item_outer_html": parser.item_outer_html,
                    "body_preview": _body_preview(doc.content),
                    "top_class_values": parser.class_values.most_common(10),
                    "storage_path": str(page_path.relative_to(root)),
                }
            )
        except Exception as exc:
            logger.exception("diagnostic fetch failed for source=%s url=%s", source_name, url)
            rows.append(
                {
                    "source": source_name,
                    "requested_url": url,
                    "error": str(exc),
                    "listing_selector": listing_selector,
                    "item_selector": item_selector,
                }
            )
    return rows


def build_report(rows: Iterable[dict[str, object]]) -> str:
    lines = ["# Source Diagnostics", ""]
    for row in rows:
        lines.append(f"## {row['source']}")
        if row.get("error"):
            lines.extend(
                [
                    f"- Error: {row['error']}",
                    f"- Listing selector tested: `{row.get('listing_selector', '')}`",
                    f"- Item selector tested: `{row.get('item_selector', '')}`",
                    "",
                ]
            )
            continue
        lines.extend(
            [
                f"- Requested URL: `{row['requested_url']}`",
                f"- Final URL: `{row['final_url']}`",
                f"- HTTP status: `{row['status']}`",
                f"- Byte count: `{row['byte_count']}`",
                f"- Content type: `{row['content_type']}`",
                f"- Saved page: `{row['storage_path']}`",
                f"- Listing selector: `{row['listing_selector']}`",
                f"- Listing selector matches: `{row['listing_count']}`",
                f"- Item selector: `{row['item_selector']}`",
                f"- Item selector matches: `{row['item_count']}`",
                "",
            ]
        )
        listing_outer_html = list(row.get("listing_outer_html", []) or [])
        item_outer_html = list(row.get("item_outer_html", []) or [])
        if listing_outer_html:
            lines.append("First listing element snippets:")
            lines.extend(f"```html\n{snippet}\n```" for snippet in listing_outer_html)
        if item_outer_html:
            lines.append("First item element snippets:")
            lines.extend(f"```html\n{snippet}\n```" for snippet in item_outer_html)
        if not listing_outer_html:
            lines.append("First 1500 body characters:")
            lines.append(f"```html\n{row.get('body_preview', '')}\n```")
            lines.append("Top class attribute values:")
            for value, count in row.get("top_class_values", []) or []:
                lines.append(f"- `{value}`: {count}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(root: Path, rows: list[dict[str, object]]) -> Path:
    path = root / "agents" / "diagnostics" / "FINDINGS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(rows), encoding="utf-8", newline="\n")
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True, default=str), encoding="utf-8", newline="\n")
    return path


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["all", "climate_week", "unga_programme", "unga_guide"], default="all")
    parser.add_argument("--limit", type=int)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    root = project_root()
    sources = ["climate_week", "unga_programme", "unga_guide"] if args.source == "all" else [args.source]
    rows: list[dict[str, object]] = []
    for source_name in sources:
        logger.info("diagnosing %s", source_name)
        rows.extend(diagnose_source(source_name, root=root, limit=args.limit))
    report_path = write_report(root, rows)
    print(report_path)
    return 0


def _safe_filename(url: str) -> str:
    parsed = urlparse(url)
    stem = f"{parsed.netloc}{parsed.path}".strip("/") or parsed.netloc or "page"
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem)
    return stem[:120] or "page"


def _body_preview(content: str) -> str:
    match = re.search(r"<body[^>]*>(.*)", content, flags=re.IGNORECASE | re.DOTALL)
    text = match.group(1) if match else content
    return _truncate(text.lstrip(), 1500)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "... [truncated]"


def _start_tag(tag: str, attrs: list[tuple[str, str | None]], *, closed: bool = False) -> str:
    attr_text = "".join(
        f' {name}="{html.escape(value, quote=True)}"' if value is not None else f" {name}"
        for name, value in attrs
    )
    suffix = " /" if closed else ""
    return f"<{tag}{attr_text}{suffix}>"


if __name__ == "__main__":
    sys.exit(main())
