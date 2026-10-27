"""Quality gates for discovered people and events: separate checks, plain reasons.

The rubric score says how relevant a page looks. It does not say whether the
record is trustworthy or complete enough to be worth a person's time, and a
single number cannot. Measured on the demo database (2026-10-22): of 57 event
records analysed, 17 had a start date and 13 a place; the ARPA-E summit was
found nine times; 94 event runs cost $33.20 for 11 confident events.

So each discovered record gets separate, deterministic checks, and a decision
that names the check behind it:

    identity      - who or what it is is established by a credible source
    source        - the page is the institution's / organiser's own, not news,
                    a listing, a directory or social media
    relevance     - the page evidences a GHUS sector
    completeness  - the mandatory fields, then the priority fields
    freshness     - (events) upcoming, past, cancelled, or date unconfirmed
    conflicts     - (events) dates that contradict each other

    exclude  a mandatory identity, source, relevance or validity check fails;
             the evidence and the reason stay on the search candidate
    research promising (named, relevant) but an essential field is missing:
             a date or place for an event, an identity source or current
             affiliation for a person. The pipeline reads the official page
             once (bounded) and decides again; still missing, it is excluded
    review   legitimate and relevant, with something a person can resolve
    accept   every mandatory field is backed and enough priority fields are
             present

Three outcomes, as Review shows them: accept and review are "Qualified for
Review" (complete or incomplete), research is "Needs More Research", exclude is
"Excluded". Nothing is ever created or verified here: every qualified event and
person goes to GHUS Review (AGENTS rule 4).

A gate only ever lowers the rubric's band, never raises it. No model is called.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from urllib.parse import urlsplit

from agents.discovery.normalize import parse_date_to_iso
from agents.discovery.search.triage import (
    ACTOR_NEWS_AND_DIRECTORY_BLOCKLIST,
    ACTOR_NEWS_HOST_PREFIXES,
    PERSON_DIRECTORY_AND_PROFILE_BLOCKLIST,
)

SOCIAL = ("linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
          "youtube.com", "tiktok.com", "threads.net")
NEWS = tuple(sorted(set(ACTOR_NEWS_AND_DIRECTORY_BLOCKLIST) | {
    "phys.org", "eurekalert.org", "sciencedaily.com", "forbes.com", "medium.com",
    "reuters.com", "bloomberg.com", "cnbc.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "yahoo.com", "msn.com", "substack.com",
}))
# Pages that list many events, or copy one: never the event's own source.
LISTINGS = ("10times.com", "allevents.in", "conferenceindex.org", "conferencealerts.com",
            "eventseye.com", "waset.org", "conference-service.com", "tethys.pnnl.gov",
            "eventbrowse.com", "clocate.com", "worldconferencealerts.com")
DIRECTORIES = tuple(d for d in PERSON_DIRECTORY_AND_PROFILE_BLOCKLIST
                    if d not in SOCIAL and d not in NEWS)
_NEWS_PATH = re.compile(r"/(news|press|newsroom|press-releases?|blog|stories)/", re.I)

DEFAULTS = {
    "person_min_priority_fields": 2,
    "event_min_priority_fields": 2,
}


def _host(url: str) -> str:
    return (urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")


def _on(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def source_kind(url: str) -> str:
    """social | news | listing | directory | web - from the address alone."""
    host = _host(url)
    if not host:
        return "unknown"
    if _on(host, SOCIAL):
        return "social"
    if _on(host, DIRECTORIES):
        return "directory"
    if _on(host, LISTINGS):
        return "listing"
    if _on(host, NEWS) or host.startswith(ACTOR_NEWS_HOST_PREFIXES) \
            or _NEWS_PATH.search(urlsplit(url).path or ""):
        return "news"
    return "web"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool | None          # None: not applicable or unknown
    detail: str


@dataclass(frozen=True)
class GateResult:
    entity_type: str
    decision: str                 # accept | review | exclude
    completeness: str             # complete | incomplete | insufficient
    checks: tuple[Check, ...]
    missing_mandatory: tuple[str, ...] = ()
    missing_priority: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    identity_source: str | None = None
    freshness: str | None = None
    why_matched: str | None = None

    @property
    def outcome(self) -> str:
        """qualified | needs_research | excluded - the three outcomes Review shows."""
        return {"accept": "qualified", "review": "qualified",
                "research": "needs_research"}.get(self.decision, "excluded")

    def payload(self) -> dict:
        """Plain JSON: lists, never tuples. A tuple reached the staged record as
        its Python text ("('...',)") and the Review page could not read it."""
        data = {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}
        data["checks"] = [asdict(c) for c in self.checks]
        data["outcome"] = self.outcome
        return data

    @property
    def summary(self) -> str:
        return "; ".join(self.reasons) or self.decision


def cap_band(band: str, gate: GateResult) -> str:
    """The rubric band, lowered by the gate - never raised.

    Needs More Research counts as excluded until a follow-up resolves it.
    """
    if gate.decision in ("exclude", "research"):
        return "auto_low"
    if gate.decision == "review" and band == "auto_high":
        return "review"
    return band


# ------------------------------------------------------------------- text helpers

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").casefold())


_HONORIFICS = {"dr", "prof", "professor", "mr", "mrs", "ms", "phd", "md", "jr", "sr", "iii", "ii"}


def name_parts(name: str) -> list[str]:
    return [t for t in _tokens(name) if t not in _HONORIFICS and len(t) > 1]


def name_on_page(name: str, page_text: str) -> bool:
    """Every part of the person's name is on the page."""
    parts = name_parts(name)
    page = set(_tokens(page_text))
    return len(parts) >= 2 and all(p in page for p in parts)


_ORG_STOP = {"the", "of", "and", "at", "for", "in", "university", "inc", "llc", "ltd", "co"}


def affiliation_on_page(affiliation: str, page_text: str) -> bool:
    """Most of the affiliation's distinctive words are on the page."""
    words = [t for t in _tokens(affiliation) if t not in _ORG_STOP and len(t) > 2]
    if not words:
        words = [t for t in _tokens(affiliation) if len(t) > 2]
    page = set(_tokens(page_text))
    return bool(words) and sum(w in page for w in words) / len(words) >= 0.6


_LINKEDIN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?", re.I)


def linkedin_profile(page_html: str, name: str) -> str | None:
    """A public LinkedIn profile the official page itself links to, for this person.

    Never fetched: LinkedIn is not read (authentication, terms). It counts
    only when the person's own official page links to it AND its address
    carries the person's family name and given name or initial - a page that
    links several people's profiles cannot attach the wrong one.
    """
    parts = name_parts(name)
    if len(parts) < 2:
        return None
    given, family = parts[0], parts[-1]
    found = None
    for slug in dict.fromkeys(m.group(1) for m in _LINKEDIN.finditer(page_html or "")):
        words = _tokens(slug.replace("%20", "-"))
        joined = "".join(words)
        if family in joined and (given in joined or (words and words[0][:1] == given[:1])):
            if found is not None:
                return None               # two candidates: not a reliable match
            found = f"https://www.linkedin.com/in/{slug.rstrip('/')}"
    return found


def _present(value) -> bool:
    return value not in (None, "", [], {})


def _rubric(rubric: dict | None, name: str) -> bool:
    item = (rubric or {}).get(name)
    return isinstance(item, dict) and item.get("present") is True


# ------------------------------------------------------------------------ people

def person_gate(record: dict, *, facts: dict | None, page_url: str, page_text: str,
                rubric: dict | None, config: dict | None = None) -> GateResult:
    """Can this person be identified, placed in an organisation, and is it worth review?"""
    settings = {**DEFAULTS, **dict((config or {}).get("discovery_quality") or {})}
    facts = facts or {}
    name = str(record.get("name") or "").strip()
    affiliation = str(record.get("affiliation") or "").strip()
    role = str(record.get("role") or "").strip()
    kind = source_kind(page_url)
    checks, reasons = [], []

    linkedin = facts.get("linkedin_url")
    named = bool(name) and name_on_page(name, page_text)
    official_profile = kind == "web" and named and _rubric(rubric, "institution_or_self_published")
    if official_profile:
        identity_source = "official_profile"
        identity_detail = "An official institutional or professional profile names this person."
    elif linkedin:
        identity_source = "linkedin"
        identity_detail = "A public LinkedIn profile, linked from the person's official page."
    else:
        identity_source = None
        identity_detail = {
            "news": "Only a news or feature article names this person.",
            "listing": "Only a listing names this person.",
            "directory": "Only a directory or aggregator names this person.",
            "social": "Only a social-media page names this person.",
        }.get(kind, "No official profile or matched LinkedIn profile establishes who this is.")
    checks.append(Check("identity", identity_source is not None, identity_detail))
    checks.append(Check("source", kind == "web",
                        "The institution's or person's own page." if kind == "web"
                        else f"A {kind} page, not an official source."))
    placed = bool(affiliation) and affiliation_on_page(affiliation, page_text)
    checks.append(Check("affiliation", placed,
                        f"Current affiliation stated on the page: {affiliation}." if placed
                        else "The current affiliation could not be established from the page."))
    relevant = _rubric(rubric, "sector_intersection")
    checks.append(Check("relevance", relevant,
                        "The page evidences work in a GHUS sector." if relevant
                        else "No GHUS sector is evidenced on the page."))

    # A complete profile is the rule (GHUS, 2026-10-25): who, where, what they
    # do, and a professional bio from the official page or a matched public
    # LinkedIn. Anything less is not sent to Review.
    expertise = _present(record.get("research_area")) or _present(facts.get("expertise"))
    has_bio = _present(facts.get("bio"))
    mandatory = {"name": bool(name), "identity source": identity_source is not None,
                 "current affiliation": placed, "GHUS relevance": relevant,
                 "role or title": bool(role), "expertise": expertise,
                 "bio or LinkedIn": has_bio or _present(linkedin)}
    missing_mandatory = tuple(k for k, ok in mandatory.items() if not ok)
    checks.append(Check("profile", has_bio or _present(linkedin),
                        "A professional bio from the official page." if has_bio
                        else "A public LinkedIn profile, matched to this person." if linkedin
                        else "No bio on the page and no matched LinkedIn profile."))
    priority = {
        "department or unit": _present(facts.get("department")),
        "public profile link": _present(record.get("public_profile_url")),
        "relevant work": _present(facts.get("relevant_work")),
        "work location": _present(facts.get("work_location")),
    }
    missing_priority = tuple(k for k, ok in priority.items() if not ok)
    present_priority = len(priority) - len(missing_priority)
    checks.append(Check("completeness", not missing_mandatory,
                        f"{len(mandatory) - len(missing_mandatory)} of {len(mandatory)} "
                        f"required fields; {present_priority} of {len(priority)} more."))

    promising = bool(name) and relevant and kind != "social"
    if missing_mandatory and promising and set(missing_mandatory) <= {
            "identity source", "current affiliation", "role or title", "expertise",
            "bio or LinkedIn"}:
        # Named and relevant, not yet complete: the official profile is read
        # once, and a LinkedIn-only search is run for a missing bio.
        decision, completeness = "research", "insufficient"
        reasons.append("Needs more research: missing " + ", ".join(missing_mandatory) + ".")
        if identity_source is None:
            reasons.append(identity_detail)
    elif missing_mandatory:
        decision, completeness = "exclude", "insufficient"
        reasons.append("Not a complete profile: missing " + ", ".join(missing_mandatory) + ".")
        if identity_source is None:
            reasons.append(identity_detail)
    else:
        decision, completeness = "accept", "complete"
        reasons.append("Complete profile: identity, title, affiliation, expertise and "
                       + ("a bio" if has_bio else "a LinkedIn profile")
                       + ", backed by an official source.")
    return GateResult("person", decision, completeness, tuple(checks), missing_mandatory,
                      missing_priority, (), tuple(reasons), identity_source, None,
                      _why_matched(rubric, ("sector_intersection", "research_area_stated")))


# ------------------------------------------------------------------------ events

_CANCELLED = re.compile(r"\b(cancell?ed|has been cancell?ed|will not take place)\b", re.I)
_POSTPONED = re.compile(r"\b(postponed|rescheduled|new dates? to be announced)\b", re.I)


def event_gate(record: dict, *, facts: dict | None, page_url: str, page_text: str,
               rubric: dict | None, run_date: date, config: dict | None = None) -> GateResult:
    """Is this a real, relevant, dated, placed event, from its own or its organiser's page?"""
    settings = {**DEFAULTS, **dict((config or {}).get("discovery_quality") or {})}
    facts = facts or {}
    title = str(record.get("title") or record.get("name") or "").strip()
    kind = source_kind(page_url)
    page_kind = str(facts.get("page_kind") or "")
    checks, reasons, conflicts = [], [], []

    official = kind == "web" and page_kind not in {"news", "listing"}
    checks.append(Check("source", official,
                        "The event's own website or its organiser's page." if official
                        else ("A news article about the event, not its official page."
                              if "news" in (kind, page_kind)
                              else "A listing of events, not the event's official page."
                              if "listing" in (kind, page_kind)
                              else f"A {kind} page, not an official source.")))
    discrete = bool(title) and _rubric(rubric, "single_discrete_event")
    checks.append(Check("identity", discrete,
                        f"One named event: {title}." if discrete
                        else "The page does not describe one named event."))

    status = str(facts.get("event_status") or "").casefold()
    if not status and _CANCELLED.search(page_text or ""):
        status = "cancelled"
    elif not status and _POSTPONED.search(page_text or ""):
        status = "postponed"

    start = _iso(record.get("start_date") or record.get("next_date"))
    end = _iso(record.get("end_date"))
    if start and end and end < start:
        conflicts.append(f"The end date ({end}) is before the start date ({start}).")
    if status == "cancelled":
        freshness = "cancelled"
    elif not start:
        freshness = "date_unconfirmed"
    elif date.fromisoformat(start) < run_date:
        freshness = "past"
    else:
        freshness = "upcoming"
    checks.append(Check("freshness", freshness in {"upcoming", "past"},
                        {"cancelled": "The page says the event is cancelled.",
                         "date_unconfirmed": "No confirmed date on the page.",
                         "past": f"Took place on {start}.",
                         "upcoming": f"Upcoming, from {start}."}[freshness]))

    fmt = str(facts.get("format") or "").casefold()
    placed = any(_present(record.get(k)) for k in ("city", "country", "location")) \
        or fmt in {"online", "hybrid", "virtual"}
    checks.append(Check("location", placed,
                        "Place or online format confirmed." if placed
                        else "No place and no online format on the page."))
    relevant = bool(list(record.get("sector_codes") or [])) and (
        _rubric(rubric, "specific_ghus_topic") or _rubric(rubric, "sector_coverage"))
    checks.append(Check("relevance", relevant,
                        "The event covers a GHUS sector." if relevant
                        else "No GHUS sector or topic is evidenced."))

    priority = {
        "organizer": _present(facts.get("organizer")) or _present(record.get("sponsoring_orgs")),
        "registration": _present(facts.get("registration_url"))
        or _present(record.get("access_type")),
        "event type": _present(record.get("event_type")),
        "description": _present(record.get("description")),
        "themes or agenda": _present(facts.get("themes")),
        "speakers or participating organizations": _present(facts.get("speakers"))
        or _present(facts.get("participating_organizations")),
    }
    missing_priority = tuple(k for k, ok in priority.items() if not ok)
    present_priority = len(priority) - len(missing_priority)
    mandatory = {"official source": official, "event identity": discrete,
                 "confirmed date": bool(start), "place or online format": placed,
                 "GHUS relevance": relevant}
    missing_mandatory = tuple(k for k, ok in mandatory.items() if not ok)
    checks.append(Check("completeness", not missing_mandatory,
                        f"{present_priority} of {len(priority)} priority fields present."))

    # Fails validity: excluded, with the reason kept on the candidate.
    fatal = [k for k in ("official source", "event identity", "GHUS relevance")
             if k in missing_mandatory]
    if status == "cancelled":
        decision, completeness = "exclude", "insufficient"
        reasons.append("The event is cancelled.")
    elif fatal:
        decision, completeness = "exclude", "insufficient"
        reasons.append("Not a usable event record: missing " + ", ".join(fatal) + ".")
    elif missing_mandatory:
        # Official, one event, relevant - but no date or no place: the official
        # pages are read once more before deciding; a low-information event is
        # not admitted.
        decision, completeness = "research", "insufficient"
        reasons.append("Needs more research: no " + ", ".join(missing_mandatory)
                       + " on the page.")
    elif conflicts or status == "postponed":
        # Legitimate and relevant, with an uncertainty a person can resolve.
        decision, completeness = "review", "incomplete"
        reasons += conflicts
        if status == "postponed":
            reasons.append("The page says the event is postponed or rescheduled.")
    elif present_priority >= int(settings["event_min_priority_fields"]):
        decision, completeness = "accept", "complete"
        reasons.append("Official, dated, placed and relevant.")
    else:
        decision, completeness = "review", "incomplete"
        reasons.append("Official, dated and relevant, but missing: " + ", ".join(missing_priority)
                       + ".")
    return GateResult("event", decision, completeness, tuple(checks), missing_mandatory,
                      missing_priority, tuple(conflicts), tuple(reasons), None, freshness,
                      _why_matched(rubric, ("specific_ghus_topic", "sector_coverage")))


def _why_matched(rubric: dict | None, items: tuple[str, ...]) -> str | None:
    """Why it matched: the rubric's own evidence for the relevance items, as read."""
    for name in items:
        item = (rubric or {}).get(name)
        if isinstance(item, dict) and item.get("present") is True and item.get("evidence"):
            return str(item["evidence"])[:300]
    return None


def _iso(value) -> str | None:
    try:
        return parse_date_to_iso(value)
    except ValueError:
        return None


# ------------------------------------------------------------------ held events

_EVENT_STOP = {"the", "of", "and", "for", "in", "on", "at", "a", "an", "annual", "edition",
               "conference", "summit", "forum", "event", "events", "home", "register",
               "registration", "agenda", "speakers"}
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def held_event_match(title: str, held_events) -> dict | None:
    """A search result that names an event already on the map - same edition.

    Measured 2026-10-22: the 2027 ARPA-E Energy Innovation Summit was found and
    analysed nine times, from its own pages, its agenda and listings. A result
    whose title holds every distinctive word of a held event's name (at least
    three), in the same year, is not fetched or analysed again. A different
    year is a new edition and is read.
    """
    words = set(_tokens(title))
    title_years = set(_YEAR.findall(str(title or "")))
    for event in held_events or ():
        name = str(event.get("name") or "")
        distinctive = {t for t in _tokens(name) if t not in _EVENT_STOP and not t.isdigit()}
        if len(distinctive) < 3 or not distinctive <= words:
            continue
        held_years = set(_YEAR.findall(name)) | set(_YEAR.findall(str(event.get("next_date") or "")))
        if held_years and title_years and not (held_years & title_years):
            continue            # another edition
        if bool(held_years) != bool(title_years) and title_years:
            continue            # a dated edition of an undated series: read it
        return dict(event)
    return None
