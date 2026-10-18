"""Is this organisation still a going concern? Deterministic, and free.

The October 14 run sent "Central Vermont Public Service" to Review from a 2009
SEC filing. CVPS merged into Green Mountain Power in 2012; nothing on the page
said so, and the model scored it like any operating utility. Three signals catch
that kind of record without another model call:

1. **The official site moved.** An organisation's own domain that now redirects
   to a different organisation's domain (cvps.com -> greenmountainpower.com) has
   been merged, acquired or renamed.
2. **The page says so.** "merged with", "was acquired by", "is now part of",
   "ceased operations" ... stated about the organisation itself.
3. **The evidence is old.** The newest year anywhere on the source page is four
   or more years ago. On someone else's page (a filing, an article) that is not
   evidence of a current organisation; on the organisation's own site it means
   the site is stale and a person should look.

Every finding carries the words a reviewer needs: what was seen, and where.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from agents.discovery.search.actor_quality import registrable_domain

MERGED = "merged_or_renamed"
DEFUNCT = "defunct"
OUTDATED_SOURCE = "outdated_source"
STALE_OWN_SITE = "stale_own_site"

# Phrases that state the organisation itself stopped or became something else.
# Deliberately narrow: "acquired funding" or "merged datasets" must not match.
_DEFUNCT = re.compile(
    r"\b(?:has|have|had|was|were)\s+(?:merged|consolidated)\s+(?:with|into)\b"
    # "X merged with Y" - only counts when the sentence names this organisation.
    r"|\b(?:merged|consolidated)\s+(?:with|into)\b"
    r"|\bwas\s+(?:acquired|purchased|bought)\s+by\b"
    r"|\b(?:is|are)\s+now\s+(?:part\s+of|a\s+(?:division|subsidiary)\s+of|known\s+as)\b"
    r"|\bformerly\s+known\s+as\b"
    r"|\b(?:has|have)\s+(?:ceased|discontinued)\s+(?:operations|trading|business)\b"
    r"|\bceased\s+operations\b"
    r"|\b(?:has|have)\s+(?:closed|shut)\s+(?:its|their)\s+doors\b"
    r"|\bno\s+longer\s+(?:in\s+operation|operating|in\s+business)\b"
    r"|\bwas\s+dissolved\b",
    re.IGNORECASE,
)
# A year, not part of a longer number or a decimal ("2011." ends a sentence).
_YEAR = re.compile(r"(?<![\d.])(19[5-9]\d|20[0-4]\d)(?!\d)(?!\.\d)")


@dataclass(frozen=True)
class CurrencyFinding:
    code: str           # one of the constants above
    reason: str         # the sentence a reviewer reads
    rejects: bool       # True -> never added; False -> held for a person


def newest_year(content: str, *, today: date) -> int | None:
    """The latest plausible year mentioned on the page (never a future one)."""
    years = [int(y) for y in _YEAR.findall(content or "") if int(y) <= today.year]
    return max(years) if years else None


_GENERIC = {
    "the", "and", "for", "of", "inc", "llc", "corp", "company", "co", "group", "energy",
    "power", "center", "centre", "institute", "university", "college", "association",
    "foundation", "council", "network", "services", "service", "solutions", "systems",
    "technologies", "technology", "public", "national", "american", "new", "england",
    "lab", "laboratory", "program", "agency", "department", "office",
}


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").casefold())
            if len(t) >= 3 and t not in _GENERIC}


def defunct_statement(text: str, name: str = "") -> str | None:
    """The sentence in which the page says THIS organisation stopped, if any.

    The sentence must name the organisation (a distinctive word of its name, or
    its acronym), so "our client was acquired by ..." does not count against it.
    """
    text = text or ""
    tokens = _name_tokens(name)
    acronym = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name or "") if w[0].isupper())
    for match in _DEFUNCT.finditer(text):
        start = max(0, text.rfind(".", 0, match.start()) + 1)
        end = text.find(".", match.end())
        sentence = " ".join(text[start:end if end != -1 else match.end() + 120].split())
        words = set(re.findall(r"[a-z0-9]+", sentence.casefold()))
        if (tokens and tokens & words) or (len(acronym) >= 3 and acronym in sentence):
            return sentence[:240]
    return None


def site_moved(stated_website: str | None, final_url: str | None) -> str | None:
    """'cvps.com now redirects to greenmountainpower.com', or None."""
    stated = registrable_domain(stated_website)
    landed = registrable_domain(final_url)
    if stated and landed and stated != landed:
        return f"{stated} now redirects to {landed}"
    return None


def assess_currency(
    *,
    name: str,
    page_text: str,
    page_url: str,
    stated_website: str | None,
    official_final_url: str | None,
    on_own_site: bool,
    today: date,
    stale_after_years: int = 4,
    year_text: str | None = None,
) -> CurrencyFinding | None:
    """The strongest currency problem found, or None if the record looks current.

    ``year_text`` is the raw page (HTML): a site's latest year is usually in
    its footer, which the visible text omits - reading years from visible text
    called an active association "nothing newer than 1974".
    """

    moved = site_moved(stated_website, official_final_url)
    if moved:
        return CurrencyFinding(
            MERGED,
            f"'{name}' appears merged, acquired or renamed: its official site {moved}.",
            rejects=True,
        )
    statement = defunct_statement(page_text, name)
    if statement:
        return CurrencyFinding(
            DEFUNCT,
            f"The page states that '{name}' is no longer operating as it was: \"{statement}\"",
            rejects=True,
        )
    latest = newest_year(year_text if year_text is not None else page_text, today=today)
    if latest is not None and today.year - latest >= stale_after_years:
        where = registrable_domain(page_url) or page_url
        if not on_own_site:
            return CurrencyFinding(
                OUTDATED_SOURCE,
                f"The only evidence is a page on {where} whose newest date is {latest}; "
                "that does not show a current organisation.",
                rejects=True,
            )
        return CurrencyFinding(
            STALE_OWN_SITE,
            f"'{name}''s own site shows nothing newer than {latest}; check it is still active.",
            rejects=False,
        )
    return None
