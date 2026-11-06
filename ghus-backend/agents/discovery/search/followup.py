"""Needs More Research: one bounded read of an official page before deciding.

A discovered event that is official, single and relevant but whose page does
not state a date or a place, or a named, relevant person not yet identified by
an official profile, is "Needs More Research" (agents/discovery/quality_gates.py).
Before it is excluded, the pipeline reads ONE more page, chosen from what the
first page itself points to:

    event   the event's own website, if the page was its organiser's; else a
            page on the same site whose link says agenda, programme, dates,
            venue or location
    person  the public profile the page names, on an institution's own site -
            never LinkedIn or any social or directory page, which are not read

At most ``followup_max_per_run`` (default 5) follow-ups per run, each at most
two fetch attempts, through the same robots-aware fetcher. Whatever it finds is
checked by the same gates; still missing, the candidate is excluded and the
reason says what was tried. Nothing is invented: a fact taken from the second
page carries that page as its source.

Also here: what is already waiting in Review, so a run - automatic or
requested - does not stage the same event or person twice.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import text

from agents.discovery.quality_gates import name_parts, source_kind

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = 5
_DETAIL_LINK = re.compile(r"agenda|program|schedule|dates?\b|venue|location|travel|"
                          r"registration|register|about", re.I)


@dataclass
class FollowupBudget:
    remaining: int
    spent_usd: float = 0.0          # what the follow-ups cost, recorded per run

    @classmethod
    def from_config(cls, config: dict) -> FollowupBudget:
        return cls(max(0, int(config.get("followup_max_per_run", DEFAULT_MAX_PER_RUN))))

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _host(url: str) -> str:
    return (urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")


def _same_page(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        parts = urlsplit(str(u or ""))
        return f"{_host(u)}{parts.path.rstrip('/')}"
    return norm(a) == norm(b)


def event_followup_urls(record: dict, page_url: str, html: str, *, limit: int = 2) -> list[str]:
    """Where an event's missing date or place is most likely stated."""
    urls: list[str] = []
    website = str(record.get("website") or "").strip()
    if website.startswith("http") and source_kind(website) == "web" \
            and not _same_page(website, page_url):
        urls.append(website)
    host = _host(page_url)
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(page_url, str(anchor["href"]))
        if not href.startswith("http") or _host(href) != host or _same_page(href, page_url):
            continue
        if _DETAIL_LINK.search(label) or _DETAIL_LINK.search(urlsplit(href).path):
            urls.append(href.split("#")[0])
        if len(urls) >= limit + 2:
            break
    return list(dict.fromkeys(urls))[:limit]


_NEXT_LINK = re.compile(r"\b(next|upcoming|future|save the date|register|registration|"
                        r"call for (papers|abstracts|proposals))\b", re.I)
_YEAR_IN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def next_edition_urls(record: dict, page_url: str, html: str, *, run_year: int,
                      limit: int = 2) -> list[str]:
    """Where the next edition of a recurring event is announced (6 Nov 2026).

    A page about a past edition ("2025 Water Summit, recap") usually links the
    next one: a link naming a year from this year on, or saying next, upcoming,
    save the date or register. Its own website comes first when it is another page.
    """
    past_years = {int(y) for y in _YEAR_IN.findall(str(record.get("start_date") or ""))}
    # A link is about THIS event only if it shares a word of its name (seen on
    # awwa.org: "Water 2050" and another conference were not the next WIC).
    name_words = _series_words(record.get("title") or record.get("name"))
    scored: list[tuple[int, str]] = []
    website = str(record.get("website") or "").strip()
    if website.startswith("http") and source_kind(website) == "web" \
            and not _same_page(website, page_url):
        scored.append((5, website.split("#")[0]))
    host = _host(page_url)
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(page_url, str(anchor["href"])).split("#")[0]
        if not href.startswith("http") or _host(href) != host or _same_page(href, page_url):
            continue
        words = f"{label} {urlsplit(href).path}"
        shared = name_words & _series_words(words.replace("-", " ").replace("/", " "))
        if name_words and not (len(shared) >= 2 or shared - _GENERIC_EVENT_WORDS):
            continue
        years = {int(y) for y in _YEAR_IN.findall(words)}
        score = 0
        if years and run_year <= max(years) <= run_year + 2 and not (years <= past_years):
            score += 4
        if _NEXT_LINK.search(words):
            score += 2
        if score:
            scored.append((score, href))
    ordered = [url for _score, url in sorted(scored, key=lambda pair: -pair[0])]
    return list(dict.fromkeys(ordered))[:limit]


# Topic words many events share: one alone does not make a link this event's.
_GENERIC_EVENT_WORDS = {"water", "energy", "innovation", "technology", "national",
                        "international", "global", "american", "world", "research", "climate",
                        "clean", "green", "future", "health", "agriculture", "mining", "power",
                        "infrastructure", "sustainability", "association", "society"}

_SERIES_STOP = {"the", "and", "annual", "edition", "conference", "summit", "symposium",
                "forum", "expo", "exposition", "event", "events", "meeting", "workshop"}


def _series_words(value) -> set[str]:
    """The distinctive words of an event name: no years, no "conference"."""
    return {w for w in re.findall(r"[a-z0-9]+", str(value or "").casefold())
            if len(w) > 2 and not w.isdigit() and w not in _SERIES_STOP}


def same_series(title: str, other: str) -> bool:
    """Two editions of one event: most of the same name, years aside."""
    def words(value):
        return {w for w in re.findall(r"[a-z0-9]+", str(value or "").casefold())
                if len(w) > 2 and not w.isdigit()
                and w not in {"the", "and", "annual", "edition", "th", "nd", "rd"}}
    a, b = words(title), words(other)
    return bool(a and b) and len(a & b) >= 0.6 * min(len(a), len(b))


_OWN_SITE = re.compile(r"^(personal |lab |group |research )?(web ?site|home ?page|web page|"
                       r"lab(oratory)?|research group|group (web)?site|personal page)$", re.I)


def person_followup_urls(record: dict, page_url: str, html: str = "") -> list[str]:
    """Where the rest of this person's profile is - never a social or directory page.

    The official profile the page names, if it is another page; then the
    person's own website that their profile links ("Website", "Lab", "Research
    group"), which usually holds the bio a structured faculty page lacks.
    """
    urls: list[str] = []
    profile = str(record.get("public_profile_url") or "").strip()
    if profile.startswith("http") and source_kind(profile) == "web" \
            and not _same_page(profile, page_url):
        urls.append(profile)
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(page_url, str(anchor["href"])).split("#")[0]
        if href.startswith("http") and _OWN_SITE.match(label) and source_kind(href) == "web" \
                and not _same_page(href, page_url) and href not in urls:
            urls.append(href)
            break
    return urls[:2]


def person_key(name: object) -> str:
    """"name:" plus the name's parts, sorted - "Dr. Donald J. Siegel" and "Donald Siegel" differ
    only by an initial, so initials are left out."""
    parts = sorted(p for p in name_parts(str(name or "")) if len(p) > 1)
    return "name:" + " ".join(parts) if len(parts) >= 2 else ""


def same_person(name: str, other: str) -> bool:
    """The second page is about the same person: every name part matches."""
    a, b = set(name_parts(name)), set(name_parts(other))
    return len(a) >= 2 and a <= b | {p[:1] for p in b}


def merge_event_reads(record: dict, extra: dict, extra_url: str) -> dict:
    """The first page's record, with only what it lacked filled from the second.

    The first page wins wherever it states something; facts from the second
    keep their own evidence (its address and date read).
    """
    merged = dict(record)
    filled: list[str] = []
    for key, value in (extra or {}).items():
        if key in ("facts", "quality"):
            continue
        if merged.get(key) in (None, "", []) and value not in (None, "", []):
            merged[key] = value
            filled.append(key)
    facts = dict(record.get("facts") or {})
    extra_facts = dict((extra or {}).get("facts") or {})
    evidence = dict(facts.get("evidence") or {})
    for key, value in extra_facts.items():
        if key in ("evidence", "dropped", "page_kind"):
            continue
        if facts.get(key) in (None, "", []) and value not in (None, "", []):
            facts[key] = value
            if key in (extra_facts.get("evidence") or {}):
                evidence[key] = extra_facts["evidence"][key]
            filled.append(key)
    for key, proof in (extra_facts.get("evidence") or {}).items():
        evidence.setdefault(key, proof)
    if evidence:
        facts["evidence"] = evidence
    if facts:
        merged["facts"] = facts
    if filled:
        merged["followup"] = {"url": extra_url, "filled": sorted(set(filled))}
    return merged


# ------------------------------------------------------- already waiting in Review

def pending_review_events(session) -> list[dict]:
    """Events staged and waiting for a person, by title, date and source page."""
    if session is None:
        return []
    try:
        # A savepoint: on a database without the queue only this read is undone.
        with session.begin_nested():
            rows = session.execute(text(
                "SELECT q.staged_title AS name, q.shared_start_date AS next_date, "
                "s.source_url AS source_url "
                "FROM event_review_queue q LEFT JOIN staged_record s "
                "ON s.staged_record_id = q.staged_record_id "
                "WHERE q.status = 'pending' AND q.staged_title IS NOT NULL"
            )).mappings().all()
        return [{"name": r["name"], "next_date": r["next_date"], "event_id": None,
                 "source_url": r["source_url"]} for r in rows]
    except Exception:  # noqa: BLE001 - an older database: nothing known to be pending
        logger.warning("could not read pending event reviews", exc_info=True)
        return []


def pending_review_actors(session, *, exclude_run_id: str | None = None) -> list[dict]:
    """Organisations found by an earlier run and still waiting for a person.

    6 Nov 2026: a recurring request found and paid for the same organisation run
    after run while the first find was still in Review.
    """
    if session is None:
        return []
    try:
        with session.begin_nested():
            rows = session.execute(text(
                "SELECT url, record_preview->>'website' AS website, "
                "COALESCE(record_preview->>'name', title) AS name FROM search_candidate "
                "WHERE entity_type = 'actor' AND review_status::text = 'pending' "
                "AND score_band IN ('auto_high', 'review') "
                "AND (CAST(:run AS text) IS NULL OR run_id::text <> CAST(:run AS text))"
            ), {"run": exclude_run_id}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001 - an older database: nothing known to be pending
        logger.warning("could not read pending actor reviews", exc_info=True)
        return []


def actor_key(name: object) -> str:
    words = re.findall(r"[a-z0-9]+", str(name or "").casefold())
    return " ".join(w for w in words if w not in {"the", "inc", "llc", "ltd", "corp", "co"})


_UNIT_SEGMENT = re.compile(r"(^|/)(centers?|centres?|institutes?|labs?|departments?|schools?|"
                           r"programs?|initiatives?)(/|$)", re.I)


def waiting_actor(url: str, name: str | None, pending: list[dict]) -> dict | None:
    """The waiting find this page or name is, if any.

    The same site counts only at the same place on it: a pending university
    (its home page) does not hold back one of its centres (/centers/water).
    """
    parts = urlsplit(url or "")
    host = (parts.hostname or "").casefold().removeprefix("www.")
    path = (parts.path or "").strip("/").casefold()
    key = actor_key(name) if name else ""
    for row in pending:
        if key and key == actor_key(row.get("name")):
            return row
        site = urlsplit(str(row.get("website") or row.get("url") or ""))
        if (site.hostname or "").casefold().removeprefix("www.") != host or not host:
            continue
        held = (site.path or "").strip("/").casefold()
        if (held and (path == held or path.startswith(held + "/"))) or (
                not held and not _UNIT_SEGMENT.search(path)):
            return row
    return None


def pending_review_people(session) -> set[str]:
    """Profile and source addresses of people waiting for a person's decision."""
    if session is None:
        return set()
    try:
        with session.begin_nested():
            rows = session.execute(text(
                "SELECT lower(coalesce(public_profile_url, '')) AS a, "
                "lower(coalesce(source_url, '')) AS b, staged_name AS name "
                "FROM person_review_queue WHERE status = 'pending'"
            )).mappings().all()
        # By address, and by name: the same person found on another page of
        # theirs is still the same review profile.
        return ({u.rstrip("/") for r in rows for u in (r["a"], r["b"]) if u}
                | {person_key(r["name"]) for r in rows if person_key(r["name"])})
    except Exception:  # noqa: BLE001
        logger.warning("could not read pending person reviews", exc_info=True)
        return set()
