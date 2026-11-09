"""Did THIS organisation receive the money? Decided by the quote's own words.

6 Nov 2026: the Light Pull asks the model for each grant's role (received,
distributed, administered, announced, offered) and keeps "received" only. The
model's label is still a claim. This module checks the quote itself: a grant is
kept as received only when the quote that gives it (the one with its amount,
or its funder's name) shows the organisation getting it -

  * the organisation receiving: "<organisation> received", "we were awarded",
    "Base Power ... Raises $1 Billion", "CEG and Partners Selected for ... Award";
  * a source phrase: "funded by", "with funding from", "made possible by a grant";
  * a funder acting on it: "<funder> awarded <organisation> a $500,000 grant",
    "a grant to <organisation>", "invested in us", "DOE Selects CEG";
  * its own agreement or equipment: "the DOE-EERC cooperative agreement,
    providing $25 million", "a $5 million DOE investment that expands the EERC's";

and no words show it giving, running or advertising the money: "we award",
"grants to 13 organizations", "apply by", "now accepting applications",
"administers ... on behalf of". A receipt verb needs the organisation as its
subject ("Congratulations to two students on winning the CWEA scholarship" is
theirs, not CWEA's). On someone else's page the quote must name the organisation.

No model is called; the same quote always gives the same answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

# The organisation receiving; the subject is checked separately ({subject}).
_RECEIVES = (
    r"\b(?:received|receives|receiving|recipient of|won|wins|winning|secured|secures|securing|"
    r"raised|raises|raising|lands|landing|landed|earned|obtained|"
    r"closed (?:a|an|its|our)\b[^.]{0,40}\bround|"
    r"(?:was|were|has been|have been|had been|is|are|been|being)\s+(?:\w+\s+)?"
    r"(?:awarded|granted|funded|selected|chosen)\b|"
    r"(?:selected|chosen|awarded|granted)\s+(?:for|to receive|a|an|\$))")
# What may stand before a receipt verb as its subject.
_SUBJECT = (
    r"(?:{name}|\bwe\b|\bour\b|\bus\b|\bit\b|\bthe\s+(?:center|centre|institute|lab|laboratory|"
    r"program|programme|project|organi[sz]ation|company|association|council|district|"
    r"foundation|network|team|initiative|university|college|school|agency|utility))")
# Words that say where the money came from, whoever is speaking.
_SOURCE = re.compile(
    r"\b(?:(?:funded|supported|sponsored|financed|backed|underwritten|made possible)"
    r"(?:\s+in\s+part)?(?:\s+\w+)?\s+(?:by|through)\b|"
    r"with\s+(?:\w+\s+){0,2}(?:funding|support|grants?|financial support|an award|investment)"
    r"\s+(?:from|by)\b|thanks to\s+(?:a|an|the)\s+[^.]{0,60}\b(?:grant|award|gift|investment)\b)",
    re.IGNORECASE)
# Its own agreement, equipment or a grant addressed to it.
_ITS_OWN = (
    r"(?:grant|award|funding|investment|gift|donation)s?\s+(?:to|for)\s+(?:the\s+)?{name}|"
    r"{name}\b[^.]{0,20}?(?:cooperative agreement|grant agreement|contract)\b[^.]{0,40}?"
    r"\b(?:providing|provides|worth|valued at|totall?ing)\b|"
    r"(?:investment|grant|award|funding)\b[^.]{0,80}?\b{name}(?:'s|’s)\s")
# A funder acting on it: "The Fund awarded The Water Council a grant", "DOE Selects CEG".
_FUNDER_ACTS = (
    r"\b(?:awarded|granted|gave|provided|invested|committed|contributed|donated|allocated|"
    r"selects|selected|chose)\b[^.]{0,80}?\b(?:to\s+|in\s+)?(?:{name}|us\b|our\s+(?:team|"
    r"organi[sz]ation|company|centre|center|lab|program(?:me)?|project|work|research))")
# The organisation giving, running or advertising the money.
_GIVES = (
    r"\b(?:we|our\s+(?:\w+\s+){0,2}(?:program(?:me)?s?|fund|foundation|committee)|{name}|"
    r"the\s+committee)\s+(?:also\s+|annually\s+|now\s+|will\s+|plans?\s+to\s+)?"
    r"(?:award|awards|awarded|grant|grants|granted|provide|provides|provided|offer|offers|"
    r"offered|distribute|distributes|distributed|administer|administers|administered|manage|"
    r"manages|fund|funds|give|gives|gave|disburse|disburses|invest|invests|"
    r"makes?\s+(?:grants|awards|investments))\b")
_OFFERED = re.compile(
    r"\b(?:apply(?:\s+now|\s+by|\s+today|\s+online)?|applications?\s+(?:are|is|now|open|due|"
    r"close)|application deadline|request for (?:proposals|applications)|RFPs?|call for "
    r"(?:proposals|applications)|now accepting|accepting applications|eligible (?:applicants|"
    r"entities|organizations|organisations)|eligibility|funding opportunit(?:y|ies)|grant "
    r"opportunit(?:y|ies)|is open to|are open to)\b",
    re.IGNORECASE)
_TO_OTHERS = re.compile(
    r"\b(?:to|for)\s+(?:\d+\s+|local\s+|eligible\s+|qualifying\s+|selected\s+|our\s+|its\s+)?"
    r"(?:applicants|recipients|grantees|awardees|members|communities|startups|researchers|"
    r"students|scholars|municipalities|utilities|nonprofits|non-profits|small businesses|"
    r"schools|projects|organizations|organisations)\b",
    re.IGNORECASE)
_ADMINISTERED = re.compile(r"\b(?:on behalf of|administers?|administered|manages? the|"
                           r"program(?:me)? administrator)\b", re.IGNORECASE)
# Money it raised and passed on: "raised more than $6M, which funded 34 projects".
_PASSED_ON = re.compile(
    r"\b(?:fund(?:ed|s|ing)?|support(?:ed|s|ing)?|award(?:ed|s|ing)?)\s+(?:more than\s+|over\s+)?"
    r"(?:\d+|several|many|dozens of|hundreds of)\s+(?:\w+\s+)?(?:projects|grants|studies|"
    r"researchers|organizations|organisations|communities|startups|scholarships|students)\b",
    re.IGNORECASE)
# Another legal entity trading under the organisation's name (8 Nov 2026: "selected
# The Empire District Electric Company d/b/a Liberty to receive up to $47.5 million",
# a Missouri electric sibling, read for Liberty's Arizona water utility).
_TRADES_AS = (r"\b((?:[A-Z][\w&'.,-]*\s+){1,8}?)(?:d/b/a|dba|doing business as|trading as|"
              r"operating as)\s+{name}\b")
_GENERIC_WORDS = frozenset({"grant", "grants", "fund", "funding", "foundation", "program",
                            "programme", "award", "department", "national", "series",
                            "round", "seed"})


def _name_pattern(name: str) -> str:
    """The organisation's name, or its acronym, as a regex alternative."""
    words = [w for w in re.findall(r"[A-Za-z0-9&]+", name or "") if w]
    if not words:
        return r"(?!x)x"
    alts = [r"\s+".join(re.escape(w) for w in words)]
    initials = "".join(w[0] for w in words if w[0].isupper())
    if len(initials) >= 3:
        alts.append(r"\b" + re.escape(initials) + r"\b")
    if words[0].casefold() == "the" and len(words) > 1:
        alts.append(r"\s+".join(re.escape(w) for w in words[1:]))
    return "(?:" + "|".join(alts) + ")"


def _supporting(entry: Mapping, quotes: Sequence[str], name: str = "") -> list[str]:
    """The quotes that give this entry: its amount when it has one, otherwise its
    funder's or programme's own words (never a word of the organisation's own
    name, which every quote may carry)."""
    digits = re.sub(r"[^\d]", "", str(entry.get("amount") or ""))
    if len(digits) >= 2:
        return [q for q in quotes if digits in re.sub(r"[^\d]", "", q)]
    own = {w.casefold() for w in re.findall(r"[A-Za-z0-9]+", name or "")}
    marks = []
    for key in ("funder", "program", "programme"):
        words = [w for w in re.findall(r"[A-Za-z0-9]{4,}", str(entry.get(key) or ""))
                 if w.casefold() not in own and w.casefold() not in _GENERIC_WORDS]
        if words:
            marks.append(words[0].casefold())
    return [q for q in quotes if any(mark in q.casefold() for mark in marks)]


def receipt_finding(entry: Mapping, quotes: Sequence[str], *, name: str,
                    own_site: bool = True) -> str | None:
    """None when the quote giving this entry shows the organisation received the
    money; otherwise the plain reason it is not kept as funding it received."""
    pattern = _name_pattern(name)

    def compiled(text: str) -> re.Pattern:
        return re.compile(text.replace("{name}", pattern), re.IGNORECASE)

    receives = compiled(_SUBJECT.replace("{name}", pattern) + r"[^.]{0,60}?" + _RECEIVES)
    # On its own site a quote cut at the verb ("received a $2 million grant from
    # ...") is the organisation speaking; the sentence's subject was trimmed.
    opens_with = compiled(r"^\W*" + _RECEIVES)
    its_own = compiled(_ITS_OWN)
    acts = compiled(_FUNDER_ACTS)
    gives = compiled(_GIVES)
    named = compiled(pattern)

    def received(quote: str) -> bool:
        return bool(receives.search(quote) or _SOURCE.search(quote) or its_own.search(quote)
                    or acts.search(quote) or (own_site and opens_with.search(quote)))

    supporting = _supporting(entry, quotes, name) or list(quotes)
    # The money went to a company that trades under this name: the same brand,
    # not shown to be the same organisation. Left for a person, not kept.
    trades_as = re.compile(_TRADES_AS.replace("{name}", pattern))
    for quote in supporting:
        match = trades_as.search(quote)
        if match and not named.search(match.group(1)):
            return (f"the money went to {match.group(1).strip()}, which trades as {name}; "
                    "not shown to be this organisation")
    for quote in supporting:
        if (gives.search(quote) or _PASSED_ON.search(quote)
                or (_TO_OTHERS.search(quote) and not received(quote))):
            return "the quote shows it giving this money to others, not receiving it"
        if _OFFERED.search(quote) and not received(quote):
            return "the quote advertises an opportunity to apply, not money it received"
        if _ADMINISTERED.search(quote) and not received(quote):
            return "the quote shows it running a programme for a funder, not receiving the money"
    # Its own quote must show it: another grant's receipt does not carry this one
    # (6 Nov 2026: "Department of Energy Selects CEG" must not keep "CEG helps
    # communities access $3.6 million").
    if any(received(q) and (own_site or named.search(q)) for q in supporting):
        return None
    if not own_site:
        return ("the quote, on another organisation's page, does not say that this "
                "organisation received the money")
    return ("the quote names the money but does not say it received it "
            "(received, awarded to it, funded by)")
