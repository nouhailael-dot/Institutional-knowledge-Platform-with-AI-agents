"""Where an organisation IS, not what its page is about.

6 Nov 2026: Discovery gave Seven Seas Water Group (Tampa, Florida) the state
Arizona, because it was read from a landing page written for Arizona customers
("Water & Wastewater Solutions for Arizona"). The model took the page's topic
for the organisation's location.

This module is the deterministic rule that decides a location. A place counts
as where the organisation is only when the page ties it to the organisation in
one of these forms:

  * ``address`` - a postal address: "Tampa, Florida 33626", or a street before
                  the city ("2959 W Calle Agua Nueva, Tucson, AZ");
  * ``based``   - "headquartered in", "based in", "offices in", "is located in",
                  "Pennsylvania-based", "an Arizona 501(c)(3)";
  * ``place``   - a "City, State" pair in the site's footer or a contact or
                  office line ("centralized at our Brockway, PA, office");
  * ``name``    - the state, or a city of that state, in the organisation's own
                  name ("WateReuse Arizona", "San Diego County Water Authority");
                  this only confirms;
  * ``parent``  - the institution that runs it carries the state ("led by the
                  University of Arizona"); this only confirms.

A state the reader left empty is filled, and a wrong one replaced, only from an
address or a based phrase. "Solutions for Arizona", "serving Arizona",
"Arizona's growth" and a story's "Pima County, Arizona" say where it works,
never where it is. On someone else's page only a sentence that names the
organisation counts, because that page's footer is its publisher's address.

No model is called; the same page always gives the same answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from agents.common.geography import STATE_NAMES, normalize_state

_NAMES = sorted(STATE_NAMES.values(), key=len, reverse=True)
_FULL = "|".join(re.escape(n) for n in _NAMES)
_CODES = "|".join(sorted(STATE_NAMES))
# A capitalised city of up to four words ("Tampa", "Salt Lake City", "St Paul").
_CITY = r"[A-Z][A-Za-z.'’-]+(?:[ ][A-Z][A-Za-z.'’-]+){0,3}"
_STATE = rf"(?P<state>{_FULL}|(?:{_CODES})(?![A-Za-z]))"
_PAIR = re.compile(rf"(?P<city>{_CITY}),[ ]?{_STATE}\.?(?:,?[ ](?P<zip>\d{{5}})(?:-\d{{4}})?)?")
_BASED = re.compile(
    r"(?:\bheadquartered|\bheadquarters|\bHQ|\bbased|(?:\b(?:is|are|we're|we are|remain)|^)"
    r"[ ]+located|^located|\boffices?|\bcampus)[ ]+(?:(?:is|are)[ ]+)?(?:in|at|:)[ ]+"
    r"(?:the[ ]+)?(?:(?:city|state)[ ]+of[ ]+)?(?P<tail>[^.;\n]{2,80})",
    re.IGNORECASE | re.MULTILINE)
# "The Water Council is a 501(c)(3) nonprofit in Milwaukee, Wisconsin": what it is,
# and where. Only after "is a" or ", a" - "we helped a company in Arizona" is
# another organisation.
_ORG_IN = re.compile(
    r"(?:\b(?:is|are|as)[ ]+(?:a|an|the)|,[ ]+(?:a|an))[ ]+(?:[\w()'.&-]+[ ]+){0,5}?"
    r"(?:non-?profit|not-for-profit|organi[sz]ation|company|firm|association|institute|"
    r"university|college|agency|start-?up|corporation|charity|foundation|cooperative|co-op|"
    r"utility|district|laboratory|lab|cent(?:er|re)|council|network|business|manufacturer|"
    r"provider|consultancy|authority|initiative|program(?:me)?)[ ]+"
    r"(?:located[ ]+|headquartered[ ]+|based[ ]+)?(?:in|from)[ ]+(?:the[ ]+)?"
    r"(?P<tail>[^.;\n]{2,80})",
    re.IGNORECASE)
# The same at the start of a quote cut before "is a" (Light Pull quotes).
_ORG_AT_START = re.compile(
    # Up to two describing words ("a 501(c)(3) nonprofit"), never a pronoun or a
    # verb ("We helped a company in Phoenix" is another organisation).
    r"^\W*(?:(?!(?:we|they|our|us|you|with|for|to|by|and|help\w*|serv\w*|support\w*|"
    r"partner\w*|work\w*|join\w*|\w+ed)\b)[\w()'.&-]+[ ]+){0,2}?"
    r"(?:non-?profit|not-for-profit|organi[sz]ation|company|"
    r"firm|association|institute|university|college|agency|start-?up|corporation|charity|"
    r"foundation|cooperative|utility|district|laboratory|lab|cent(?:er|re)|council|network|"
    r"business|manufacturer|provider|authority)[ ]+(?:located[ ]+|headquartered[ ]+|"
    r"based[ ]+)?(?:in|from)[ ]+(?:the[ ]+)?(?P<tail>[^.;\n]{2,80})",
    re.IGNORECASE)
_TAIL_STATE = re.compile(rf"(?:^|[ ,])(?P<state>{_FULL}|(?:{_CODES})(?![A-Za-z]))")
# "Pennsylvania-based", "an Arizona 501(c)(3)", "a Delaware corporation".
_STATE_ADJ = re.compile(
    rf"\b(?P<state>{_FULL})[- ](?:based\b|non-?profit\b|not-for-profit\b|501\(c\)\(3\)|"
    r"corporation\b|limited liability company\b|LLC\b|public benefit corporation\b)")
# "led by the University of Arizona": the institution that runs it.
_PARENT = re.compile(
    r"\b(?:led by|part of|a program(?:me)? of|an initiative of|housed (?:in|at|within)|"
    r"hosted by|based at|a unit of|a cent(?:er|re) (?:of|at)|operated by|run by)[ ]+(?:the[ ]+)?"
    r"(?P<parent>[A-Z][\w&.'’ -]{3,80})")
# A street address before the pair on the same line ("2959 W Calle Agua Nueva, Tucson").
_STREET_NUMBER = re.compile(r"\b\d{1,6}[ ]+(?:[NSEW]\.?[ ]+)?[A-Z0-9]")
# Street words before a city in an address line ("14400 Carlson Circle Tampa").
_STREET = re.compile(
    r"^.*\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|way|lane|ln|circle|"
    r"cir|court|ct|place|pl|parkway|pkwy|highway|hwy|suite|ste|floor|fl|box|plaza|"
    r"square|sq|center|centre|building|bldg|hall|mall|terrace|trail|loop|row)\.?[ ]+",
    re.IGNORECASE)
_NOT_A_CITY = re.compile(
    r"^(?:the|our|and|for|in|of|at|by|with|from|to|copyright|all|rights|reserved|"
    r"inc|llc|ltd|corp|co|university|college|institute|center|centre|department|"
    r"office|school|program|programme|project|solutions|services|county|counties|"
    r"region|valley|area|metro|parish|borough)$", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_ADDRESS_LINE = re.compile(
    r"\b(address|mailing|contact|visit us|p\.?\s?o\.?\s?box|suite|ste\.|phone|tel|fax|"
    r"office|headquarters)\b|\(\d{3}\)|\b\d{3}[-.]\d{3}[-.]\d{4}\b", re.IGNORECASE)
# Words that make a place its head office.
_HQ_WORDS = re.compile(r"\b(?:headquarter\w*|HQ|head office|main office|corporate office|"
                       r"home office)\b|-based\b", re.IGNORECASE)
# A state named in full ("Arizona"): where the page shows the organisation working.
_MENTION = re.compile(rf"\b(?:{_FULL})\b(?!\.? ?D\.?C\b)")
_FOOTER_LINE = re.compile(r"^\[?Footer\b", re.IGNORECASE)
STRENGTH = {"address": 3, "based": 2, "place": 1, "parent": 0}
# What can fill a state the reader left empty, or replace a wrong one.
SETS_A_STATE = ("address", "based")


@dataclass(frozen=True)
class PlaceStatement:
    state: str            # USPS code
    city: str | None
    kind: str             # address | based | place | parent
    text: str             # the words that state it
    headquarters: bool = False   # the words say it is the head office


@dataclass(frozen=True)
class LocationCheck:
    state: str | None     # USPS code to keep, None when the page does not tie one to it
    city: str | None
    basis: str            # name | parent | address | based | place | unconfirmed | none
    claimed_state: str | None
    changed: bool
    reason: str
    evidence: str = ""
    # Where its head office is, when the page says so ("headquartered in",
    # "Headquarters: ..."), and every other place the page shows it working:
    # an office address ("office") or a state its own page names ("mentioned").
    headquarters: dict | None = None
    operates_in: tuple = field(default_factory=tuple)

    def as_record(self) -> dict:
        return {"basis": self.basis, "claimed_state": self.claimed_state,
                "kept_state": self.state, "city": self.city, "changed": self.changed,
                "reason": self.reason, "evidence": self.evidence[:240],
                "headquarters": self.headquarters, "operates_in": list(self.operates_in)}


def _clean_city(raw: str) -> str | None:
    city = _STREET.sub("", raw or "").strip(" ,.")
    words = city.split()
    # A sentence's opening words are not a city: keep the last words only.
    while words and _NOT_A_CITY.match(words[0]):
        words = words[1:]
    words = words[-3:]
    if not words or any(_NOT_A_CITY.match(w) for w in words) or re.search(r"\d", " ".join(words)):
        return None
    if normalize_state(" ".join(words)):   # "Arizona, Nevada" is two states, not a city
        return None
    return " ".join(words)


def _names(name: str, sentence: str) -> bool:
    from agents.collection.light_pull_reader import quotes_name

    return quotes_name(name, [sentence])


def name_state(name: str) -> str | None:
    """The state a name carries, if any ("WateReuse Arizona", "University of Arizona")."""
    text = " ".join(str(name or "").split())
    for full in _NAMES:
        # "Kansas City" and "Washington University" are not the states.
        if re.search(rf"\b{re.escape(full)}\b(?![ ]+(?:City\b|University\b(?![ ]+of)))",
                     text, re.IGNORECASE):
            return normalize_state(full)
    return None


# Census place types that are cities (not villages or census-designated places,
# where "Energy, Illinois" or "Sutter, California" would match by chance).
_CITY_TYPES = frozenset({"25", "UG", "CG", "UC", "MG", "37", "53"})


def name_city_in(name: str, state: str | None) -> str | None:
    """A city of ``state`` that the organisation's name carries ("VA Phoenix Health
    Care System" -> Phoenix, Arizona), from the Census places list."""
    if not state:
        return None
    try:
        from agents.common.geography import default_gazetteer, normalize_city

        index = default_gazetteer()._index
    except Exception:  # noqa: BLE001 - without the list, nothing is confirmed this way
        return None
    from agents.collection.light_pull_reader import _COMMON_NAME_WORDS

    words = re.findall(r"[A-Z][A-Za-z.'\u2019-]+", str(name or ""))
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i:i + size])
            # "Center", "Energy", "Water": words of organisations' names, and
            # also the names of small cities (Center, North Dakota).
            if len(phrase) < 4 or all(w.casefold() in _COMMON_NAME_WORDS
                                      or _NOT_A_CITY.match(w) for w in words[i:i + size]):
                continue
            for place in index.get((state, normalize_city(phrase)), ()):
                if place.lsad in _CITY_TYPES:
                    return phrase
    return None


def footer_text(html: str, limit: int = 1200) -> str:
    """The text of a page's footer, where most sites print their address."""
    if not html or "<" not in html:
        return ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    parts = soup.find_all("footer") + soup.find_all(attrs={"role": "contentinfo"})
    seen, lines = set(), []
    for part in parts:
        for element in part.find_all(["script", "style", "noscript", "template"]):
            element.decompose()
        for line in part.stripped_strings:
            line = " ".join(line.split())
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return "\n".join(lines)[:limit]


def place_statements(text: str, *, name: str = "", footer: str = "",
                     own_site: bool = True) -> list[PlaceStatement]:
    """Every place the text ties to the organisation, strongest forms first.

    On its own site an address, a based phrase or a footer or contact-line
    pair anywhere counts; on someone else's page only a sentence that names
    the organisation counts."""
    found: list[PlaceStatement] = []

    context = ""

    def add(state_word: str, city: str | None, kind: str, words: str) -> None:
        code = normalize_state(state_word)
        if code:
            hq = bool(_HQ_WORDS.search(words) or _HQ_WORDS.search(context))
            found.append(PlaceStatement(code, city, kind, " ".join(words.split())[:240], hq))

    for block, in_footer in ((text or "", False), (footer or "", True)):
        for line in block.splitlines():
            if _FOOTER_LINE.match(line.strip()):
                in_footer = True            # the rest of a "Footer:" part of a page text
            for sentence in _SENTENCE.findall(line):
                context = sentence
                names = bool(name) and _names(name, sentence)
                if not own_site and not names:
                    continue
                for m in _STATE_ADJ.finditer(sentence):
                    add(m.group("state"), None, "based", m.group(0))
                for m in _PARENT.finditer(sentence):
                    parent = name_state(m.group("parent"))
                    if parent:
                        add(parent, None, "parent", m.group(0))
                for m in [*_BASED.finditer(sentence.strip()), *_ORG_IN.finditer(sentence)]:
                    tail = m.group("tail")
                    pair = _PAIR.search(tail)
                    if pair and _clean_city(pair.group("city")):
                        add(pair.group("state"), _clean_city(pair.group("city")), "based",
                            m.group(0))
                        continue
                    state = _TAIL_STATE.search(tail)
                    if state and state.start() < 40:
                        add(state.group("state"), None, "based", m.group(0))
                for m in _PAIR.finditer(sentence):
                    city = _clean_city(m.group("city"))
                    if city is None:
                        continue
                    before = sentence[:m.start("city")]
                    if m.group("zip") or _STREET_NUMBER.search(before[-40:] + m.group("city")):
                        add(m.group("state"), city, "address", m.group(0))
                    elif in_footer or _ADDRESS_LINE.search(sentence):
                        add(m.group("state"), city, "place", m.group(0))
    found.sort(key=lambda s: -STRENGTH[s.kind])
    return found


def state_mentions(text: str, *, name: str = "", footer: str = "",
                   own_site: bool = True) -> dict[str, str]:
    """Each state the page names in full, with the words around it. On someone
    else's page only sentences naming the organisation count."""
    found: dict[str, str] = {}
    for block in (text or "", footer or ""):
        for line in block.splitlines():
            for sentence in _SENTENCE.findall(line):
                if not own_site and not (name and _names(name, sentence)):
                    continue
                for m in _MENTION.finditer(sentence):
                    code = normalize_state(m.group(0))
                    if code and code not in found:
                        start = max(0, m.start() - 60)
                        found[code] = " ".join(sentence[start:m.end() + 60].split())
    return found


def check_location(*, name: str, claimed_state: object, claimed_city: object = None,
                   text: str, footer: str = "", own_site: bool = True) -> LocationCheck:
    """Keep, correct or withhold the state a reader gave an organisation, and
    say where its head office is and where else the page shows it working.

    7 Nov 2026: a head office elsewhere is not a reason to reject an
    organisation that works in the requested state; the quality gate holds it
    for a person when ``operates_in`` names that state."""
    kept, statements = _kept_location(name=name, claimed_state=claimed_state,
                                      claimed_city=claimed_city, text=text, footer=footer,
                                      own_site=own_site)
    flagged = [s for s in statements if s.headquarters and s.kind != "parent"]
    hq = flagged[0] if flagged else None
    headquarters = {"state": hq.state, "city": hq.city, "text": hq.text} if hq else None
    elsewhere: dict[str, dict] = {}
    for s in statements:
        if s.kind == "parent" or (hq and s.state == hq.state) or s.state in elsewhere:
            continue
        elsewhere[s.state] = {"state": s.state, "kind": "office", "city": s.city,
                              "text": s.text}
    for code, words in state_mentions(text, name=name, footer=footer,
                                      own_site=own_site).items():
        if code not in elsewhere and not (hq and code == hq.state):
            elsewhere[code] = {"state": code, "kind": "mentioned", "city": None, "text": words}
    operates = tuple(v for k, v in elsewhere.items() if k != kept.state)
    return replace(kept, headquarters=headquarters, operates_in=operates)


def _kept_location(*, name: str, claimed_state: object, claimed_city: object, text: str,
                   footer: str, own_site: bool) -> tuple[LocationCheck, list[PlaceStatement]]:
    claimed = normalize_state(claimed_state) if claimed_state else None
    city = str(claimed_city or "").strip() or None
    statements = place_statements(text, name=name, footer=footer, own_site=own_site)
    if claimed and name_state(name) == claimed:
        return LocationCheck(claimed, city, "name", claimed, False,
                             f"Its name carries {STATE_NAMES[claimed]}.", name), statements
    if claimed:
        for s in statements:
            if s.state == claimed:
                return LocationCheck(claimed, city or s.city, s.kind, claimed, False,
                                     f"The page states it: \"{s.text}\".", s.text), statements
    in_name = name_city_in(name, claimed)
    if in_name and not any(s.kind in SETS_A_STATE for s in statements):
        return LocationCheck(claimed, city or in_name, "name", claimed, False,
                             f"Its name carries {in_name}, a city of {STATE_NAMES[claimed]}.",
                             name), statements
    # A parent's name or a footer pair can confirm a state the reader gave (above),
    # but only an address or a based phrase sets one.
    setting = [s for s in statements if s.kind in SETS_A_STATE]
    if setting:
        best = STRENGTH[setting[0].kind]
        strongest = [s for s in setting if STRENGTH[s.kind] == best]
        states = list(dict.fromkeys(s.state for s in strongest))
        if len(states) == 1:
            s = strongest[0]
            where = f"{s.city + ', ' if s.city else ''}{STATE_NAMES[s.state]}"
            reason = (f"The page is about {STATE_NAMES.get(claimed, claimed)}, but its own "
                      f"{'address' if s.kind == 'address' else 'words'} place it in {where}: "
                      f"\"{s.text}\"." if claimed else f"The page states it: \"{s.text}\".")
            return LocationCheck(s.state, s.city, s.kind, claimed, s.state != claimed,
                                 reason, s.text), statements
        lead = (f"The page names {STATE_NAMES.get(claimed, claimed)} but places the "
                "organisation in " if claimed else "The page gives addresses in ")
        return LocationCheck(None, None, "unconfirmed", claimed, bool(claimed),
                             f"{lead}{', '.join(states)}; a person decides."), statements
    if claimed:
        return LocationCheck(None, None, "unconfirmed", claimed, True,
                             f"The page talks about {STATE_NAMES.get(claimed, claimed)} but never "
                             "says the organisation is based or has an office there."), statements
    return LocationCheck(None, city, "none", None, False,
                         "The page states no location."), statements


def quote_places_it(name: str, quotes: Sequence[str], *, state: object = None,
                    city: object = None) -> bool:
    """Whether a quote states the organisation is at this place (Light Pull's
    location box), rather than that it works there."""
    code = normalize_state(state) if state else None
    if code and name_state(name) == code:
        return True
    city_word = " ".join(str(city or "").split()).casefold()
    state_word = " ".join(str(state or "").split()).casefold()

    def tails(q: str) -> list[str]:
        # A quote is often cut before "is a": "nonprofit in Milwaukee, Wisconsin".
        found = [m.group("tail") for m in [*_BASED.finditer(q), *_ORG_IN.finditer(q)]]
        start = _ORG_AT_START.match(q)
        return found + ([start.group("tail")] if start else [])

    if state and not code:
        # Outside the US (Toronto, Ontario): the states above do not apply; the
        # quote must name the place in an address line or a based phrase.
        place = city_word or state_word
        for quote in quotes:
            q = " ".join(str(quote).split())
            if place and place in q.casefold() and (
                    _ADDRESS_LINE.search(q) or _STREET_NUMBER.search(q)
                    or any(place in t.casefold() for t in tails(q))):
                return True
        return False
    for quote in quotes:
        q = " ".join(str(quote).split())
        for s in place_statements(q, name=name, own_site=True):
            if code and s.state == code:
                return True
            if not code and city_word and city_word in (s.city or s.text).casefold():
                return True
        for t in tails(q):
            t = t.casefold()
            if (code and (state_word in t or STATE_NAMES[code].casefold() in t
                          or re.search(rf"\b{code.casefold()}\b", t))) \
                    or (not code and city_word and city_word in t):
                return True
    return False
