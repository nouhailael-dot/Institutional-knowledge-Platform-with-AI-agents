"""When an organisation's own website refuses the agent: say so, remember it, read elsewhere.

Seen on 2026-10-21: University of Arizona Mining & Geological Engineering
(``mge.engineering.arizona.edu``) answers every automated request with 403
Forbidden, and the update stopped with nothing read. The site is not wrong to
refuse; the agent must not get around it. It reads, within the same bound of
three pages and the same cost cap, what IS open to it:

1. the organisation's parent's official site (same registrable domain, another
   host): its pages that name this organisation - "UA Mining Engineering" on
   ``engineering.arizona.edu``. Free: no search.
2. only if that finds nothing, ONE web search, for pages naming the
   organisation: its official parent first, then government (``.gov``), then
   credible third parties. Paid, bounded, and shown in the preview.

Every page read this way must name THIS organisation - a department, not only
its university - or it is not used. Robots.txt is always obeyed (the fetcher
checks it), nothing is retried while its cooldown runs, and a refusal is
recorded so the next update does not knock again.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from agents.discovery.search.actor_official import _HREF
from agents.discovery.search.actor_quality import registrable_domain

# Hosts that refused, kept beside the update checks (agents/runs, not in git).
BLOCKED_SITES = Path(__file__).resolve().parents[1] / "runs" / "blocked_sites.json"

# How long a host is left alone after it refused, by kind of refusal.
COOLDOWN = {
    "forbidden": timedelta(days=14),       # 401 / 403: it refuses automated readers
    "robots": timedelta(days=14),          # robots.txt asks automated tools not to read
    "rate_limited": timedelta(hours=24),   # 429: it asked us to slow down
    "timeout": timedelta(days=2),
    "unreachable": timedelta(days=2),      # DNS, connection, certificate
    "no_text": timedelta(days=14),         # shown only through scripts
    "error": timedelta(days=1),
}

PLAIN = {
    "forbidden": "Its website refuses automated access (it blocks tools like ours).",
    "robots": "Its website asks automated tools not to read these pages, and we respect that.",
    "rate_limited": "Its website asked us to slow down; it will be tried again later.",
    "timeout": "Its website took too long to answer.",
    "unreachable": "Its website could not be reached (the address may be wrong, the site "
                   "down, or its security certificate broken).",
    "no_text": "Its website shows its content only through scripts the agent cannot read.",
    "not_found": "That page no longer exists at its address.",
    "error": "Its website could not be read.",
}

SOURCE_TYPES = {
    "official": "its own website",
    "official_parent": "its parent organisation's official website",
    "government": "a government website",
    "third_party": "another credible website",
}

# Words that name a kind of organisation, not this one.
_GENERIC = frozenset({
    "university", "college", "school", "department", "dept", "center", "centre", "institute",
    "program", "programme", "lab", "laboratory", "office", "division", "the", "and", "for",
    "of", "at", "in", "inc", "llc", "ltd", "corp", "corporation", "company", "group",
    "engineering", "sciences", "science", "studies", "national", "state", "foundation",
    "association", "society", "council", "network",
})
# Sites never used as a source about an organisation.
_NOT_SOURCES = re.compile(
    r"(?:^|\.)(facebook|linkedin|twitter|x|instagram|youtube|tiktok|reddit|pinterest|glassdoor|"
    r"indeed|zoominfo|crunchbase|rocketreach|signalhire)\.", re.IGNORECASE)


def host_of(url: str) -> str:
    return (urlsplit(url if "//" in url else f"https://{url}").hostname or "").lower() \
        .removeprefix("www.")


def failure_of(exc: BaseException) -> dict:
    """What kind of refusal this is, in words a reader understands."""
    text = f"{type(exc).__name__}: {exc}"
    status = None
    match = re.search(r"\b([1-5]\d\d)\b", str(exc))
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        status = int(response.status_code)
    elif match and "HTTPStatusError" in text:
        status = int(match.group(1))
    lowered = text.casefold()
    if "robots" in lowered:
        kind = "robots"
    elif status in (401, 403):
        kind = "forbidden"
    elif status == 429:
        kind = "rate_limited"
    elif status in (404, 410):
        kind = "not_found"
    elif "timeout" in lowered or "timed out" in lowered:
        kind = "timeout"
    elif any(w in lowered for w in ("connecterror", "getaddrinfo", "name or service",
                                    "certificate", "ssl", "connection refused", "nodename")):
        kind = "unreachable"
    else:
        kind = "error"
    return {"kind": kind, "status": status, "plain": PLAIN[kind], "technical": text[:300]}


@dataclass
class BlockedSites:
    """Hosts that refused the agent, and until when they are left alone (a JSON file)."""

    path: Path
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def _load(self) -> dict:
        try:
            return json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")

    def blocked(self, url: str) -> dict | None:
        """The refusal still in its cooldown for this host, or None."""
        record = self._load().get(host_of(url))
        if not record:
            return None
        if datetime.fromisoformat(record["retry_after"]) <= self.now():
            return None
        return record

    def record(self, url: str, failure: dict) -> dict:
        data = self._load()
        host = host_of(url)
        now = self.now()
        cooldown = COOLDOWN.get(failure["kind"])
        if cooldown is None:                    # a missing page is not a refusal
            return {}
        entry = {"host": host, "kind": failure["kind"], "status": failure.get("status"),
                 "plain": failure["plain"], "last_seen": now.isoformat(),
                 "first_seen": (data.get(host) or {}).get("first_seen") or now.isoformat(),
                 "retry_after": (now + cooldown).isoformat()}
        data[host] = entry
        self._save(data)
        return entry

    def clear(self, url: str) -> None:
        data = self._load()
        if data.pop(host_of(url), None) is not None:
            self._save(data)


def distinct_terms(name: str, website: str = "") -> list[str]:
    """The words that name THIS organisation: not generic words, not its parent's domain."""
    parent_words = set(re.findall(r"[a-z]+", registrable_domain(website or "").casefold()))
    words = re.findall(r"[a-z][a-z'-]+", (name or "").casefold().replace("&", " "))
    out = []
    for word in words:
        if len(word) > 2 and word not in _GENERIC and word not in parent_words and word not in out:
            out.append(word)
    return out


def _stem(word: str) -> str:
    return word[:5]


def names_this_organisation(text: str, terms: list[str]) -> bool:
    """The page names this organisation: every one of its distinct words is on it."""
    if not terms:
        return False
    page = {_stem(w) for w in re.findall(r"[a-z]+", (text or "").casefold())}
    return all(_stem(t) in page for t in terms)


def identity(html: str, text: str, terms: list[str]) -> str | None:
    """How a page names this organisation: "full", "partial", or not at all (None).

    Partial: at least half its distinct words are on the page AND its title
    names it. Seen on 2026-10-21: the department's own degree page on the
    college's site is titled "UA Mining Engineering Degree" and never writes
    "Geological" (the department now runs as the School of Mining Engineering).
    Only a parent's official page may count on a partial name.
    """
    if names_this_organisation(text, terms):
        return "full"
    if not terms:
        return None
    page = {_stem(w) for w in re.findall(r"[a-z]+", (text or "").casefold())}
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    title = {_stem(w) for w in re.findall(r"[a-z]+", (match.group(1) if match else "").casefold())}
    present = [t for t in terms if _stem(t) in page]
    if 2 * len(present) >= len(terms) and any(_stem(t) in title for t in terms):
        return "partial"
    return None


def source_type(url: str, website: str) -> str:
    host, own = host_of(url), host_of(website)
    if host == own:
        return "official"
    if registrable_domain(url) == registrable_domain(website):
        return "official_parent"
    if host.endswith(".gov") or host.endswith(".mil"):
        return "government"
    return "third_party"


class FetchLimitReached(RuntimeError):
    """The per-read page request allowance has been used."""


@dataclass
class BoundedFetch:
    fetch: Callable
    limit: int = 3
    calls: int = 0

    @property
    def remaining(self):
        return max(0, self.limit - self.calls)

    def __call__(self, url):
        if not self.remaining:
            raise FetchLimitReached("The three-page request limit was reached.")
        self.calls += 1
        return self.fetch(url)


@dataclass
class Fallback:
    """Other sources for an organisation whose own website cannot be read."""

    blocked: BlockedSites
    search: Callable[[str], list] | None = None     # one paid web search, if allowed
    max_searches: int = 1
    attempts: list[dict] = field(default_factory=list)

    def start(self) -> None:
        """A new organisation: its own attempts, its own search allowance."""
        self.attempts = []

    def note(self, url: str, outcome: str, plain: str, **extra) -> None:
        self.attempts.append({"url": url, "outcome": outcome, "plain": plain, **extra})

    def try_fetch(self, fetch, url: str):
        held = self.blocked.blocked(url)
        if held:
            self.note(url, "skipped", f"{held['plain']} Not tried again until "
                                      f"{held['retry_after'][:10]}.")
            return None
        try:
            doc = fetch(url)
        except FetchLimitReached:
            self.note(url, "limit_reached", "The three-page request limit was reached.")
            return None
        except Exception as exc:  # noqa: BLE001 - one refusal is recorded, not fatal
            failure = failure_of(exc)
            self.blocked.record(url, failure)
            self.note(url, "refused", failure["plain"], status=failure.get("status"))
            return None
        return doc

    def pages(self, fetch, *, name: str, website: str, room: int, text_of) -> list[tuple]:
        """Up to ``room`` pages about this organisation from sources open to the agent.

        Returns (doc, source_type, identity) triples; every page names the
        organisation - fully, or (on its parent's official site only) partly.
        """
        terms = distinct_terms(name, website)
        found: list[tuple] = []
        seen: set[str] = set()

        def take(doc, kind: str) -> bool:
            key = str(doc.url).rstrip("/")
            if key in seen:
                return False
            seen.add(key)
            named = identity(doc.content or "", text_of(doc), terms)
            if named is None or (named == "partial" and kind != "official_parent"):
                self.note(doc.url, "not_about_it",
                          "This page does not name the organisation itself (only its parent "
                          "or another unit), so it was not used.")
                return False
            found.append((doc, kind, named))
            note = f"Read from {SOURCE_TYPES[kind]}."
            if named == "partial":
                note += (" The page names it only in part, so what it states is marked "
                         "medium confidence.")
            self.note(doc.url, "used", note, source_type=kind, identity=named)
            return True

        # 1. The parent's official site: hosts between this one and its domain.
        own = host_of(website)
        domain = registrable_domain(website)
        labels = own.split(".")
        parents = [".".join(labels[i:]) for i in range(1, len(labels))
                   if ".".join(labels[i:]).endswith(domain) and len(labels[i:]) >= 2]
        parents = [h for h in dict.fromkeys(parents + [f"www.{domain}"]) if h != own]
        # Reserve an attempt for a search-result page when paid fallback is enabled.
        if self.search is not None and self.max_searches > 0:
            parents = parents[:1]
        for host in parents:
            if len(found) >= room or getattr(fetch, "remaining", 1) <= 0:
                break
            home = self.try_fetch(fetch, f"https://{host}/")
            if home is None:
                continue
            candidates = []
            for href, label in _HREF.findall(home.content or ""):
                target = urljoin(home.url, href.strip())
                if registrable_domain(target) != domain or host_of(target) == own:
                    continue
                if re.search(r"\.(pdf|jpg|png|zip|docx?)$|^mailto:", target, re.I):
                    continue
                words = f"{urlsplit(target).path} {re.sub(r'<[^>]+>', ' ', label)}".casefold()
                score = sum(_stem(t) in words for t in terms)
                if score:
                    candidates.append((score, target))
            for _score, target in sorted(candidates, key=lambda c: -c[0])[:4]:
                if len(found) >= room:
                    break
                doc = self.try_fetch(fetch, target)
                if doc is not None:
                    take(doc, source_type(doc.url, website))
        # 2. One web search, only if the parent's site gave nothing.
        if (not found and self.search is not None and self.max_searches > 0
                and getattr(fetch, "remaining", 1) > 0):
            query = " ".join(filter(None, [f'"{name}"', domain.split(".")[0] if domain else ""]))
            try:
                results = self.search(query) or []
            except Exception as exc:  # noqa: BLE001
                self.note(query, "search_failed", "The web search could not be made: "
                                                  + failure_of(exc)["plain"])
                results = []
            ranked = sorted(
                (r for r in results if r.url and not _NOT_SOURCES.search(host_of(r.url) + ".")
                 and host_of(r.url) != own),
                key=lambda r: {"official_parent": 0, "government": 1,
                               "third_party": 2}.get(source_type(r.url, website), 3))
            self.note(query, "searched", f"One web search found {len(results)} result(s).")
            for result in ranked:
                if len(found) >= room:
                    break
                doc = self.try_fetch(fetch, result.url)
                if doc is not None:
                    take(doc, source_type(doc.url, website))
        return found
