"""People Discovery: search only where a complete professional profile lives.

The first live people runs (2026-10-23/24) searched the open web and got news
articles, Wikipedia, conference speaker lists and LinkedIn pages: 39 results,
none of them a person's own profile. A complete profile - name, title,
organization, expertise, and a bio or a public LinkedIn - is on one kind of page:
the person's profile on their institution's own website. So the agent now goes
there directly:

    domains    the official websites of the institutions the map already holds
               in the requested area and sector (universities, research
               centres, national laboratories, government) - or, when the
               request names one, that institution's site only
    searches   one per topic per small group of those domains, restricted to
               them (the search tool's allowed_domains): "battery storage"
               professor profile on utexas.edu, tamu.edu, rice.edu ...
    pages      a result must look like one person's profile page; a people
               directory is opened (no model call) and the profile links of the
               people whose listing mentions the topic are followed instead;
               news, events, PDFs and everything else are dropped before triage
    LinkedIn   never opened. When the official page has no bio and links no
               LinkedIn, one LinkedIn-only search is run for that name and
               organization; a result counts only if its title carries the full
               name and the organization.

Nothing here calls a model. Actor and event discovery do not use it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import text

from agents.discovery.quality_gates import name_parts

# Where people with a public professional profile work.
PROFILE_CATEGORIES = ("university_academic", "research_center", "national_laboratory",
                      "government", "hospital_clinical")
DOMAINS_PER_SEARCH = 6
_DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")

_PEOPLE_WORDS = ("people", "faculty", "directory", "staff", "profile", "profiles", "experts",
                 "expert", "bio", "bios", "person", "persons", "team", "researchers",
                 "investigators", "leadership", "our-people", "members", "scholars",
                 "fellows", "display", "employees", "about-us", "who-we-are")
_NOT_PROFILE = re.compile(
    r"/(news|newsroom|press|events?|calendar|stories|blog|magazine|article|articles|"
    r"publications?|research-areas?|programs?|courses?|jobs|careers|apply|give|giving)"
    r"(/|$)|\.(pdf|docx?|pptx?|xlsx?)$", re.I)
_SLUG = re.compile(r"^(~[a-z0-9._-]+|(?:\d{1,6}[-_])?[a-z][a-z'.-]+(?:[-_.][a-z][a-z'.-]+){0,4}"
                   r"(?:[-_]\d{1,4})?(?:\.(?:html?|php|aspx?))?)$", re.I)
_NAV_WORDS = {"home", "about", "contact", "people", "faculty", "staff", "directory", "news",
              "events", "research", "apply", "login", "search", "more", "read", "view",
              "profile", "website", "email", "department", "menu", "back", "next", "all"}


def registrable(url_or_host: str) -> str:
    # Imported websites can carry text after the address ("arizona.edu College of ...").
    words = str(url_or_host or "").split()
    site = words[0] if words else ""
    host = (urlsplit(site).hostname if "//" in site else site) or ""
    host = host.lower().removeprefix("www.")
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in {"co", "ac", "gov", "edu", "org"} \
            and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def institution_domains(session, *, states: Sequence[str], sector_codes: Sequence[str],
                        institution: str | None = None, keywords: Sequence[str] = (),
                        academic_only: bool = False, limit: int = 8) -> list[dict]:
    """The official sites to search, best first: [{domain, institutions, score}].

    An institution named by the request is the only target when the map holds
    it. Otherwise: held institutions in the area, scored by how many of them
    work on the topic - linked to the sector, or naming the topic or sector in
    their name, description or focus (sector links are sparse) - and by being
    a university or a national laboratory.
    """
    words = {w for k in keywords for w in re.findall(r"[a-z]{4,}", str(k).lower())}
    if session is None:
        return []
    rows = session.execute(text(
        "SELECT a.name, COALESCE(NULLIF(a.website_domain, ''), a.website) AS site, "
        "a.actor_category AS category, concat_ws(' ', a.name, a.description, "
        # Through to_jsonb: the shared database no longer has these legacy columns.
        "to_jsonb(a)->>'primary_technical_focus', to_jsonb(a)->>'current_activities') AS about, "
        "COALESCE(a.state_code, (SELECT l.state_code FROM actor_location l "
        " WHERE l.actor_id = a.actor_id ORDER BY l.is_primary DESC NULLS LAST LIMIT 1)) "
        " AS state, "
        "EXISTS (SELECT 1 FROM actor_sector x JOIN sector s ON s.sector_id = x.sector_id "
        "        WHERE x.actor_id = a.actor_id AND upper(s.code) = ANY(:codes)) AS in_sector "
        "FROM actor a WHERE a.actor_category = ANY(:cats) "
        "AND COALESCE(NULLIF(a.website_domain, ''), a.website) IS NOT NULL "
        "AND COALESCE(a.status, to_jsonb(a)->>'record_status', '') NOT IN ('rejected', 'merged')"
    ), {"codes": [c.upper() for c in sector_codes] or [""],
        "cats": list(PROFILE_CATEGORIES)}).mappings().all()
    if institution:
        wanted = _org_tokens(institution)
        named = [r for r in rows if wanted and wanted <= _org_tokens(r["name"])]
        if named:
            rows = named
            states = ()
    scores: dict[str, dict] = {}
    for row in rows:
        if states and str(row["state"] or "").upper() not in {s.upper() for s in states}:
            continue
        domain = registrable(row["site"] if "//" in str(row["site"]) else f"//{row['site']}")
        # The search service refuses a whole search over one malformed domain.
        if not _DOMAIN.fullmatch(domain):
            continue
        entry = scores.setdefault(domain, {"domain": domain, "institutions": [],
                                           "in_sector": 0, "academic": False})
        entry["institutions"].append(row["name"])
        about = str(row["about"] or "").lower()
        topical = row["in_sector"] or (words and any(w in about for w in words))
        entry["in_sector"] += 1 if topical else 0
        entry["academic"] |= row["category"] in ("university_academic", "national_laboratory")
    entries = list(scores.values())
    if academic_only and any(e["academic"] for e in entries):
        # A professor or researcher is on a university's or a laboratory's site.
        entries = [e for e in entries if e["academic"]]
    # A site with nothing in the requested sector is searched only when no
    # site has anything in it (a medical school is not where battery experts are).
    if not institution and any(e["in_sector"] for e in entries):
        entries = [e for e in entries if e["in_sector"]]
    for e in entries:
        e["score"] = e["in_sector"] * 3 + (2 if e["academic"] else 0) + 0.1 * len(e["institutions"])
    ranked = sorted(entries, key=lambda e: (-e["score"], e["domain"]))
    return ranked[:limit]


def profile_queries(themes: Sequence[str], domains: Sequence[str], *, role: str | None,
                    max_queries: int = 8) -> tuple[list[str], dict[str, list[str]]]:
    """(queries, {query: allowed domains}): one per topic per group of domains."""
    groups = [list(domains[i:i + DOMAINS_PER_SEARCH])
              for i in range(0, len(domains), DOMAINS_PER_SEARCH)] or [[]]
    who = role or "professor"
    # Each group of sites gets its own wording, so every search is distinct.
    shapes = ("profile", "faculty profile", "researcher bio", "expert profile")
    queries: list[str] = []
    where: dict[str, list[str]] = {}
    for group_index, group in enumerate(groups):
        for theme in themes:
            if len(queries) >= max_queries:
                return queries, where
            query = f'"{theme}" {who} {shapes[group_index % len(shapes)]}'
            if query in where:
                continue
            queries.append(query)
            where[query] = group
    return queries, where


_STORY_HOSTS = re.compile(r"^(news|stories|magazine|today|events?|calendar|blogs?|"
                          r"newsroom|media|press)\.", re.I)


def profile_page_kind(url: str) -> str:
    """profile | directory | other - from the address alone."""
    parts = urlsplit(str(url or ""))
    path = parts.path.rstrip("/")
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not path or _NOT_PROFILE.search(parts.path) or _STORY_HOSTS.match(host):
        return "other"
    segments = [s for s in path.split("/") if s]
    lowered = [s.lower() for s in segments]
    if any(s.startswith("~") for s in segments):
        return "profile"
    for i, seg in enumerate(lowered):
        if any(word == seg or seg.startswith(word + "-") or seg.endswith("-" + word)
               for word in _PEOPLE_WORDS):
            rest = segments[i + 1:]
            if not rest:
                return "directory"
            if _SLUG.match(rest[-1]) and rest[-1].lower() not in _PEOPLE_WORDS:
                return "profile"
            if rest[-1].isdigit() or re.match(r"^n\d+$", rest[-1]):
                return "profile"            # ids: /people/1234, /display/n123
            return "directory"
    if parts.query and re.search(r"(^|&)(id|uid|person|user|profile)=", parts.query, re.I):
        return "profile"
    return "other"


def _looks_like_name(textvalue: str) -> bool:
    words = [w for w in re.split(r"\s+", textvalue.strip()) if w]
    if not 2 <= len(words) <= 5 or any(ch.isdigit() for ch in textvalue):
        return False
    if any(w.lower().strip(",.") in _NAV_WORDS for w in words):
        return False
    return sum(w[:1].isupper() for w in words) >= 2


_LINK_LABELS = re.compile(r"^(view |read |full |see )?(bio|biography|profile|more|details|"
                          r"faculty (page|profile)|homepage|home page)\b", re.I)
_TITLE_WORDS = re.compile(r"\b(professor|assistant|associate|director|lecturer|research|"
                          r"scientist|engineer|fellow|chair|dean|postdoc|manager|head)\b", re.I)


def _card_name(block, anchor_text: str) -> str | None:
    """The person a card is about: the link's own text, a heading, or the words before the title."""
    if _looks_like_name(anchor_text):
        return anchor_text
    for tag in block.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if _looks_like_name(text):
            return text
    text = " ".join(block.get_text(" ", strip=True).split())
    title = _TITLE_WORDS.search(text)
    head = text[: title.start()].strip(" ,|-") if title else ""
    return head if _looks_like_name(head) else None


_OWN_SITE_LABEL = re.compile(r"(research group|lab(oratory)?|group|web ?site|home ?page|"
                             r"personal page)", re.I)


def _own_site(block, page_url: str, profile_url: str) -> str | None:
    """The person's own lab or group site linked from their card ("View Research Group")."""
    from agents.discovery.quality_gates import source_kind

    for anchor in block.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(page_url, str(anchor["href"]).strip()).split("#")[0]
        if href != profile_url and href.startswith("http") and _OWN_SITE_LABEL.search(label) \
                and source_kind(href) == "web":
            return href
    return None


def directory_leads(html: str, page_url: str, themes: Sequence[str], *,
                    limit: int = 6) -> list[dict]:
    """People on a directory page whose listing mentions the topic: [{url, name, context}].

    Profile links on the same institution's sites (any subdomain), whether the
    link is the person's name or a "View Bio" next to it; the name then comes
    from the person's card. Ranked by how many topic words that card holds;
    people whose card says nothing about the topic are left out.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    site = registrable(page_url)
    words = {w for t in themes for w in re.findall(r"[a-z]{4,}", t.lower())}
    seen: set[str] = set()
    leads: list[tuple[int, int, dict]] = []
    for order, anchor in enumerate(soup.find_all("a", href=True)):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(page_url, str(anchor["href"])).split("#")[0]
        if href in seen or registrable(href) != site:
            continue
        if not (_looks_like_name(label) or _LINK_LABELS.match(label)):
            continue
        if profile_page_kind(href) != "profile":
            continue
        block = anchor
        for _ in range(5):           # the person's own card or row - never a neighbour's
            parent = block.parent
            if parent is None or len(parent.get_text(" ", strip=True)) > 700:
                break
            # Another person on the same institution's sites - not this person's
            # own Google Scholar or lab link.
            neighbours = {link for link in (urljoin(page_url, str(a["href"])).split("#")[0]
                                            for a in parent.find_all("a", href=True))
                          if registrable(link) == site and profile_page_kind(link) == "profile"}
            if neighbours - {href}:
                break
            block = parent
        name = _card_name(block, label)
        if not name:
            continue
        context = " ".join(block.get_text(" ", strip=True).split())[:400]
        hits = sum(w in context.lower() for w in words)
        if words and not hits:
            continue
        seen.add(href)
        leads.append((hits, order, {"url": href, "name": name, "context": context,
                                    "own_site": _own_site(block, page_url, href)}))
    leads.sort(key=lambda item: (-item[0], item[1]))
    return [lead for _, _, lead in leads[:limit]]


_ORG_STOP = {"the", "of", "and", "at", "for", "in", "inc", "llc", "ltd", "co", "university"}


def _org_tokens(value: object) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9&]+", str(value or "").lower())
            if w not in _ORG_STOP and len(w) > 2}


def linkedin_match(results: Iterable, name: str, affiliation: str) -> dict | None:
    """The one LinkedIn profile a search result shows for this person, or None.

    Title must carry every part of the name and at least half of the
    organization's distinctive words ("Jane Doe - Professor - The University of
    Texas at Austin | LinkedIn"). Two different matching profiles: none is kept.
    """
    parts = name_parts(name)
    org = _org_tokens(institution_of(affiliation))
    if len(parts) < 2:
        return None
    found: dict | None = None
    for result in results:
        url = str(getattr(result, "url", "") or "")
        if not re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+", url, re.I):
            continue
        title = str(getattr(result, "title", "") or "")
        said = set(re.findall(r"[a-z0-9]+", f"{title} {getattr(result, 'snippet', '')}".lower()))
        if not all(p in said for p in parts):
            continue
        if org and len(org & said) / len(org) < 0.5:
            continue
        clean = url.split("?")[0].rstrip("/")
        if found and found["url"] != clean:
            return None                 # two people of that name: not reliable
        found = {"url": clean, "title": title}
    return found


_INSTITUTION = re.compile(r"universit|institut|laborator|college|school of mines|center|"
                          r"centre|agency|department of energy|corporation|company|inc\b", re.I)


def institution_of(affiliation: str) -> str:
    """The institution in an affiliation: "University of Houston" from
    "University of Houston Department of Electrical and Computer Engineering"."""
    text = " ".join(str(affiliation or "").split())
    head = re.split(r"\s+(?:Department|Dept\.?|School|College|Division|Program)\s+of\s+", text,
                    maxsplit=1)[0]
    if head != text and _INSTITUTION.search(head):   # "University of X Department of Y"
        text = head
    parts = [p.strip() for p in re.split(r",|\s[-|]\s", text) if p.strip()]
    for part in parts:
        if _INSTITUTION.search(part) and not re.match(r"^(Department|Dept)\b", part, re.I):
            return part
    return parts[-1] if parts else text


def search_linkedin(search: Callable, name: str, affiliation: str) -> dict | None:
    """One LinkedIn-only search for this person; the profile URL from the result, never fetched."""
    results = search(f'"{name}" {institution_of(affiliation)}', count=10,
                     allowed_domains=["linkedin.com"])
    return linkedin_match(results, name, affiliation)


_ACADEMIC_ROLE = re.compile(r"professor|faculty|lecturer|postdoc|researcher|scientist|"
                            r"investigator|scholar|fellow", re.I)


def academic_role(role: str | None) -> bool:
    return bool(role and _ACADEMIC_ROLE.search(role))


def themes_for(request, sectors: Sequence[Mapping[str, str]]) -> list[str]:
    return list(request.themes(sectors))[:3]
