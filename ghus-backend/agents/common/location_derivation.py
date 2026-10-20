"""Fill an actor's missing state, region or coordinates from what its record already says.

Deterministic, and only where the answer is unique - nothing is guessed:

* **state from the city** - the city names a place in exactly ONE US state in
  the vendored Census gazetteer ("Urbana" alone is ambiguous; "Montpelier" is
  not, in this sense, unless several states have one - then it stays empty);
* **coordinates from the city** - the city as written often defeats an exact
  lookup ("Urbana-Champaign", "Washington D.C.", "Knoxville / Lexington"), so
  each part is tried; a part counts only if it is a place IN the record's state;
* **region from the state** - the fixed seven-region map;
* **state from the name** - only when neither city nor state is recorded, and
  the name contains exactly one full state name in a pattern that means the
  place ("University of Texas", "Arizona State University", "Texas A&M",
  "California Department of ..."). Never a city, and never "Washington" alone
  (Washington University is in Missouri).

Every value derived says how (``how``), and is written only into an EMPTY
field by ``decisions.fill_actor_location_gaps``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agents.common.geography import (
    STATE_NAMES,
    STATE_TO_REGION,
    _plain_text,
    default_gazetteer,
    normalize_city,
    normalize_state,
)

US = {"", "US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA", "U S", "U S A"}


@dataclass
class Derivation:
    city: str | None = None
    state_code: str | None = None
    region_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    how: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.how)


def is_us(country: object) -> bool:
    return _plain_text(country).upper() in US


def city_variants(city: object) -> list[str]:
    """The city as written, then each part of a compound name."""
    raw = " ".join(str(city or "").split())
    if not raw:
        return []
    cleaned = re.sub(r"\bD\.?\s?C\.?$", "", raw).strip(" ,")  # "Washington D.C."
    parts = [p.strip() for p in re.split(r"\s*(?:/|–|—|-|&|\band\b|,)\s*", cleaned) if p.strip()]
    out = []
    for value in (raw, cleaned, *parts):
        if value and value not in out:
            out.append(value)
    return out


def _states_for_city(gazetteer, city: str) -> set[str]:
    key = normalize_city(city)
    return {state for (state, name) in gazetteer._index if name == key} if key else set()


# Name patterns where a state name means the place, and names where it does not.
_STATE_WORDS = sorted(STATE_NAMES.values(), key=len, reverse=True)
_NOT_A_PLACE = re.compile(r"\bwashington university\b|\bgeorge washington\b|\bbooker t\b", re.I)


def state_from_name(name: object) -> str | None:
    text = " ".join(str(name or "").split())
    if not text or _NOT_A_PLACE.search(text):
        return None
    found, rest = [], text
    for state in _STATE_WORDS:  # longest first: "West Virginia" before "Virginia"
        # "Kansas City" is mostly in Missouri: a state name before "City" is a city.
        pattern = re.compile(rf"\b{re.escape(state)}\b(?!\s+city\b)", re.I)
        if pattern.search(rest):
            found.append(state)
            rest = pattern.sub(" ", rest)
    if len(found) != 1:
        return None
    state = found[0]
    if state.casefold() == "washington" and not re.search(
            r"\bwashington state\b|\bstate of washington\b", text, re.I):
        return None  # Washington, D.C. or a person's name, as often as the state
    return normalize_state(state)


def city_from_name(name: object, state_code: str, gazetteer) -> str | None:
    """A city the name places it in - "... at Austin", "... - Corpus Christi" - in that state."""
    match = re.search(r"(?:\bat\b|\bin\b|\s[-–—]\s?|–)\s*([A-Z][\w.'’ ]{2,40})$",
                      str(name or "").strip())
    if not match:
        return None
    candidate = match.group(1).strip(" .")
    if normalize_state(candidate):  # "... in Texas" names the state, not a city
        return None
    return candidate if gazetteer.lookup(candidate, state_code, "US").found else None


def derive(*, name: object, city: object, state: object, country: object = "US",
           has_coordinates: bool = False, gazetteer=None) -> Derivation:
    """What can be derived for the empty fields, and how."""
    out = Derivation()
    if not is_us(country):
        return out  # the gazetteer is US-only; nothing abroad is derived
    gazetteer = gazetteer or default_gazetteer()
    state_code = normalize_state(state)
    if str(state or "").strip() and not state_code:
        return out  # "Oregon / Pennsylvania / West Virginia": several sites, not one place
    variants = city_variants(city)
    if not state_code and variants:
        # The state comes from the whole city name only, never from one part
        # of a compound ("Pittsburgh / Morgantown" spans two states).
        for variant in variants[:2]:
            states = _states_for_city(gazetteer, variant)
            if len(states) == 1:
                state_code = states.pop()
                out.state_code = state_code
                out.how.append(f"state {state_code} from the city “{variant}”, the only US "
                               "place of that name")
                break
    if not state_code and not variants:
        from_name = state_from_name(name)
        if from_name:
            state_code = out.state_code = from_name
            out.how.append(f"state {from_name} from the name")
            named_city = city_from_name(name, from_name, gazetteer)
            if named_city:
                out.city = named_city
                variants = [named_city]
                out.how.append(f"city {named_city} from the name")
    if state_code and not has_coordinates and variants:
        for variant in variants:
            result = gazetteer.lookup(variant, state_code, "US")
            if result.found:
                out.latitude, out.longitude = result.latitude, result.longitude
                out.how.append(f"coordinates of {result.matched_place_name}, {state_code}")
                break
    if state_code:
        out.region_code = STATE_TO_REGION.get(state_code)
    return out
