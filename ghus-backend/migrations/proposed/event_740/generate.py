"""Build the optional fill for migration 740 from a copy of the database.

    .venv/bin/python ghus-backend/migrations/proposed/event_740/generate.py "<database url>"

Reads every event's free-text `location` and writes `fill_locations.sql` next to this
file: one UPDATE per event whose place is clear. 740 itself only adds the columns (GHUS,
24 Nov 2026: structure first, data later). Each UPDATE applies only while the event's
location is still the text it was read from, so the file can be used on production later.

Never guessed (AGENTS.md rule 7): a vague place ("Various locations", "TBD", "Online"),
a venue with no city, and "New York" / "New York, USA" (city or state?) stay empty.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg

OUT = Path(__file__).resolve().parent / "fill_locations.sql"
US_WORDS = {"usa", "us", "u.s.", "u.s.a.", "united states", "united states of america"}
# Countries the events name today; another country leaves the place empty.
COUNTRIES = {
    "switzerland": "Switzerland", "italy": "Italy", "ethiopia": "Ethiopia", "rwanda": "Rwanda",
    "kenya": "Kenya", "france": "France", "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "canada": "Canada", "brazil": "Brazil", "india": "India", "germany": "Germany",
    "spain": "Spain", "egypt": "Egypt", "morocco": "Morocco", "mauritania": "Mauritania",
    "saudi arabia": "Saudi Arabia", "indonesia": "Indonesia", "south africa": "South Africa",
    "nigeria": "Nigeria", "senegal": "Senegal", "ghana": "Ghana", "japan": "Japan",
    "china": "China", "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
    "qatar": "Qatar", "mexico": "Mexico", "belgium": "Belgium", "netherlands": "Netherlands",
    "austria": "Austria", "azerbaijan": "Azerbaijan", "colombia": "Colombia", "chile": "Chile",
}
VAGUE = re.compile(r"^(various|rotating|location tbd|tbd|tba|online|virtual|locations throughout|"
                   r"multiple)", re.I)
NYC = re.compile(r"^(new york city|nyc)$", re.I)
ZIP = re.compile(r"^\d{5}(-\d{4})?$")
# New York City and its boroughs, which the census city list names only as "New York".
NYC_NAMES = {"new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx", "the bronx",
             "staten island"}


def place(location: str, aliases: dict[str, str],
          cities: set[tuple[str, str]]) -> dict[str, str] | None:
    """{venue, city, state_code, country} when the text states them clearly, else None.
    A US city counts only if the census city list has it in that state."""
    text = " ".join(str(location or "").split())
    if not text or VAGUE.match(text):
        return None
    # "New York City — venue not confirmed": the note after the dash is not a place.
    text = re.split(r"\s+—\s+", text)[0]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    parts = [re.sub(r"\s+\d{5}(-\d{4})?$", "", p) for p in parts if not ZIP.match(p)]
    # "12 East 41st St, 7th Floor, 12 East 41st St, 7th floor, ...": one of each.
    parts = list({p.casefold(): p for p in reversed(parts)}.values())[::-1]
    if not parts:
        return None
    last = parts[-1].casefold()
    if last in COUNTRIES:
        if len(parts) < 2:
            return None
        return {"venue": ", ".join(parts[:-2]), "city": parts[-2], "state_code": "",
                "country": COUNTRIES[last]}
    if last in US_WORDS:
        parts = parts[:-1]
    for i in range(len(parts) - 1, 0, -1):     # the state needs a city before it
        code = aliases.get(parts[i].casefold())
        city = parts[i - 1].casefold().removeprefix("city of ").strip()
        if code and ((city, code) in cities or (code == "NY" and city in NYC_NAMES)):
            return {"venue": ", ".join(parts[:i - 1]), "city": parts[i - 1],
                    "state_code": code, "country": "USA"}
    city = next((i for i, p in enumerate(parts) if NYC.match(p)), None)
    if city is not None:
        return {"venue": ", ".join(parts[:city]), "city": parts[city], "state_code": "NY",
                "country": "USA"}
    return None


def quote(value: str) -> str:
    return "NULL" if not value else "'" + value.replace("'", "''") + "'"


def main(url: str) -> None:
    with psycopg.connect(url) as conn:
        aliases = dict(conn.execute("SELECT alias, state_code FROM us_state_alias").fetchall())
        aliases.update({"d.c.": "DC", "dc": "DC", "washington dc": "DC", "washington, d.c.": "DC"})
        events = conn.execute("SELECT event_id::text, location FROM event ORDER BY event_id").fetchall()
        cities = set(conn.execute("SELECT normalized_city, state_code FROM us_city_coord").fetchall())
    updates, empty = [], 0
    for event_id, location in events:
        found = place(location, aliases, cities)
        if not found:
            empty += 1
            continue
        updates.append(
            f"UPDATE public.event SET venue = {quote(found['venue'])}, city = {quote(found['city'])}, "
            f"state_code = {quote(found['state_code'])}, country = {quote(found['country'])} "
            f"WHERE event_id = '{event_id}' AND location = {quote(location)};")
    OUT.write_text(HEADER.format(filled=len(updates), empty=empty, total=len(events))
                   + "\n".join(updates) + FOOTER, encoding="utf-8")
    print(f"{OUT}: {len(updates)} events filled, {empty} left empty, of {len(events)}")


HEADER = """\
-- Optional fill for migration 740 (NOT part of 740; not applied anywhere).
--
-- Generated by migrations/proposed/event_740/generate.py from a copy of the database.
-- Run only after 740, and only with GHUS's go-ahead: it changes event data.
--
--   * Fills venue, city, state_code and country from `location` where the text states
--     them clearly: {filled} of {total} events. A US city counts only if the census city
--     list (us_city_coord) has it in that state. {empty} stay empty (vague, no location,
--     a venue with no city, or "New York" / "New York, USA": city or state?).
--     Each UPDATE applies only while the event's location is still the text read.
--   * region_code follows from the state (region_state). US country is written 'USA'.
--
-- One transaction: any failure changes nothing.

BEGIN;
SET LOCAL lock_timeout = '15s';

"""

FOOTER = """

UPDATE public.event e SET region_code = rs.region_code
FROM public.region_state rs
WHERE rs.state_code = e.state_code AND e.region_code IS NULL;

COMMIT;
"""

if __name__ == "__main__":
    main(sys.argv[1])
