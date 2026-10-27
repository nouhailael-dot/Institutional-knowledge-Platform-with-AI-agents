"""United States only: events and people abroad are never searched for or paid for.

GHUS maps United States hubs; an event outside the US was already excluded -
but only after it had been searched, triaged and read. Measured 2026-10-23 on
the automatic event run: the model-written searches asked for "World Food Forum
Rome 2026", "Hand-in-Hand Investment Forum Rome", "mining investment conference
Southeast Asia" and "Global Framework on Chemicals conference Geneva"; $0.92 of
searches, much of it for places GHUS does not map.

Three deterministic checks, before any money is spent:

    queries   a search naming a foreign country, region or city (and no US
              place) is not run
    places    the map's own event locations feed the searches only when they
              are in the US
    results   a search result on a foreign country domain, or whose title and
              snippet name a foreign place and no US place, is excluded before
              triage and reading - with that reason, kept in the run history

A US place anywhere in the text wins: "Africa Energy Forum in Houston" and
"Paris, Texas" stay. Online events have no place and are never dropped here.
No model is called. Actor Discovery does not use this module.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from agents.common.geography import STATE_NAMES

# Country-code domains of other countries. Generic and US domains (.com, .org,
# .gov, .edu, .us, .io, .ai, .co ...) say nothing about where an event is.
FOREIGN_TLDS = frozenset("""
uk eu de fr es it nl be ch at se no dk fi ie pt pl cz gr hu ro bg hr si sk lt lv ee
ru ua tr il ae sa qa kw bh om jo lb eg ma dz tn ng ke za gh et tz ug rw sn ci cm
in pk bd lk np cn hk tw jp kr sg my th vn ph id au nz ca mx br ar cl pe uy ve ec bo py
asia africa london berlin paris tokyo
""".split())

_COUNTRIES = (
    "united kingdom", "england", "scotland", "wales", "ireland", "germany", "france",
    "spain", "italy", "netherlands", "belgium", "switzerland", "austria", "sweden",
    "norway", "denmark", "finland", "portugal", "poland", "greece", "turkey", "israel",
    "united arab emirates", "uae", "saudi arabia", "qatar", "kuwait", "bahrain", "oman",
    "egypt", "morocco", "algeria", "tunisia", "nigeria", "kenya", "south africa", "ghana",
    "ethiopia", "rwanda", "senegal", "india", "pakistan", "bangladesh", "sri lanka",
    "china", "hong kong", "taiwan", "japan", "south korea", "korea", "singapore",
    "malaysia", "thailand", "vietnam", "philippines", "indonesia", "australia",
    "new zealand", "canada", "mexico", "brazil", "argentina", "chile", "colombia", "peru",
    "ukraine", "russia",
)
_REGIONS = ("europe", "european union", "southeast asia", "asia pacific", "apac",
            "middle east", "mena", "latin america", "latin american", "european", "sub-saharan africa", "africa",
            "east africa", "west africa", "gulf region", "nordic")
# Unambiguous foreign cities (not Paris: "Paris Agreement"; not Georgia, Jordan).
_CITIES = (
    "london", "manchester", "edinburgh", "dublin", "berlin", "munich", "frankfurt",
    "hamburg", "madrid", "barcelona", "rome", "milan", "amsterdam", "rotterdam",
    "brussels", "geneva", "zurich", "vienna", "stockholm", "copenhagen", "oslo",
    "helsinki", "lisbon", "warsaw", "athens", "istanbul", "dubai", "abu dhabi",
    "riyadh", "doha", "cairo", "casablanca", "rabat", "marrakech", "benguerir",
    "nairobi", "lagos", "johannesburg", "cape town", "mumbai", "delhi", "new delhi",
    "bangalore", "bengaluru", "beijing", "shanghai", "shenzhen", "tokyo", "osaka",
    "seoul", "kuala lumpur", "bangkok", "jakarta", "manila", "hanoi",
    "ho chi minh", "sydney", "melbourne", "toronto", "vancouver", "montreal",
    "mexico city", "bogota", "sao paulo", "rio de janeiro", "buenos aires", "santiago",
)
_FOREIGN = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(p) for p in (*_COUNTRIES, *_REGIONS, *_CITIES))
    + r")(?![a-z])", re.I)

_US_CITIES = (
    "new york", "nyc", "boston", "chicago", "houston", "dallas", "austin", "san antonio",
    "denver", "phoenix", "seattle", "portland", "san francisco", "los angeles",
    "san diego", "san jose", "sacramento", "atlanta", "miami", "orlando", "tampa",
    "philadelphia", "pittsburgh", "baltimore", "detroit", "cleveland", "columbus",
    "minneapolis", "milwaukee", "st. louis", "saint louis", "kansas city", "nashville",
    "new orleans", "las vegas", "salt lake city", "albuquerque", "raleigh", "charlotte",
    "washington, dc", "washington dc", "washington d.c.", "honolulu", "anchorage",
    "ann arbor", "madison", "boulder", "tucson", "oklahoma city", "indianapolis",
    "cincinnati", "louisville", "memphis", "richmond", "norfolk", "providence",
)
_US = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(p) for p in (
        "united states", "usa", "u.s.", "u.s.a.", "us-based",
        *(name.lower() for name in STATE_NAMES.values()), *_US_CITIES))
    + r")(?![a-z])", re.I)
_ONLINE = re.compile(r"(?<![a-z])(online|virtual|webinar|livestream)(?![a-z])", re.I)


def foreign_place(text: str) -> str | None:
    """The foreign place a text names - None when it also names a US place, or none."""
    text = str(text or "")
    found = _FOREIGN.search(text)
    if found is None or _US.search(text) or _ONLINE.search(text):
        return None
    return found.group(1)


def foreign_domain(url: str) -> str | None:
    host = (urlsplit(str(url or "")).hostname or "").lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    return tld if tld in FOREIGN_TLDS else None


def result_outside_us(url: str, title: str, snippet: str) -> str | None:
    """Why a search result is about somewhere outside the US, or None."""
    text = f"{title} {snippet}"
    tld = foreign_domain(url)
    if tld and not _US.search(text) and not _ONLINE.search(text):
        return f"Outside the United States: a .{tld} site. GHUS maps United States hubs."
    place = foreign_place(text)
    if place:
        return (f"Outside the United States: the result names {place.title()} and no US "
                "place. GHUS maps United States hubs.")
    return None


def us_queries(queries) -> tuple[list[str], list[str]]:
    """(searches to run, searches dropped because they name a foreign place)."""
    kept, dropped = [], []
    for query in queries:
        (dropped if foreign_place(query) else kept).append(query)
    return kept, dropped


def us_places(places) -> list[str]:
    return [p for p in places if not foreign_place(p)]
