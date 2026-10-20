"""Deterministic Architecture V2 geography derived from Census place data.

Region and coordinate values in this module are derived outputs. Callers must
not trust candidate-supplied region names or coordinates.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

GAZETTEER_YEAR = 2025
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2025_Gazetteer/2025_Gaz_place_national.zip"
)
GAZETTEER_SHA256 = "49644173a453469d9bd77fb7a493b027f87567e209edaf2078aac7543ac2ee29"
DEFAULT_GAZETTEER_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "gazetteer"
    / "2025_Gaz_place_national.zip"
)
EARTH_RADIUS_MILES = 3958.7613


REGION_STATES: dict[str, tuple[str, ...]] = {
    "northeast": ("CT", "ME", "MA", "NH", "NY", "RI", "VT"),
    "mid_atlantic": ("DE", "MD", "NJ", "PA", "VA", "WV", "DC"),
    "southeast": ("AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"),
    "midwest_great_lakes": (
        "IL",
        "IN",
        "IA",
        "KS",
        "MI",
        "MN",
        "MO",
        "NE",
        "ND",
        "OH",
        "SD",
        "WI",
    ),
    "south_central_texas_gulf": ("AR", "LA", "OK", "TX"),
    "mountain_west": ("AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"),
    "west_coast_pacific": ("AK", "CA", "HI", "OR", "WA"),
}
STATE_TO_REGION = {
    state_code: region_code
    for region_code, state_codes in REGION_STATES.items()
    for state_code in state_codes
}
STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
STATE_ALIASES = {_name.casefold(): code for code, _name in STATE_NAMES.items()}
STATE_ALIASES.update({code.casefold(): code for code in STATE_NAMES})
STATE_ALIASES.update(
    {
        "d c": "DC",
        "washington d c": "DC",
        "washington dc": "DC",
        "district columbia": "DC",
        "washington district of columbia": "DC",
        "washington state": "WA",
    }
)

_CITY_SUFFIXES = (
    ("consolidated", "government", "balance"),
    ("metropolitan", "government", "balance"),
    ("unified", "government", "balance"),
    ("urban", "county", "balance"),
    ("consolidated", "government"),
    ("metropolitan", "government"),
    ("unified", "government"),
    ("municipality",),
    ("borough",),
    ("village",),
    ("town",),
    ("city",),
    ("cdp",),
    ("balance",),
)
_CITY_TOKEN_ALIASES = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}
_DERIVED_INPUT_KEYS = {
    "region",
    "region_code",
    "latitude",
    "longitude",
    "lat",
    "lon",
}


@dataclass(frozen=True)
class GazetteerPlace:
    geoid: str
    state_code: str
    place_name: str
    normalized_city: str
    latitude: float
    longitude: float
    lsad: str
    function_status: str


@dataclass(frozen=True)
class GeocodeResult:
    state: str
    reason: str | None
    country: str
    state_code: str | None
    city: str
    normalized_city: str
    region_code: str | None
    latitude: float | None
    longitude: float | None
    matched_place_name: str | None
    geoid: str | None

    @property
    def found(self) -> bool:
        return self.state == "found"


@dataclass(frozen=True)
class PreparedLocation:
    location_name: str | None
    is_primary: bool
    result: GeocodeResult


@dataclass(frozen=True)
class PreparedActorGeography:
    actor_values: dict[str, object]
    locations: tuple[PreparedLocation, ...]
    failures: tuple[PreparedLocation, ...]


def _plain_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", text).casefold().split())


def normalize_state(value: object) -> str | None:
    """Return a USPS code, keeping Washington State distinct from Washington DC."""
    normalized = _plain_text(value)
    if not normalized:
        return None
    return STATE_ALIASES.get(normalized)


def region_for_state(value: object) -> str | None:
    """Derive one of the seven fixed regions from state name/code input."""
    state_code = normalize_state(value)
    return STATE_TO_REGION.get(state_code or "")


def normalize_city(value: object) -> str:
    """Normalize Census place names and common St/Saint, Ft/Fort variants."""
    tokens = [_CITY_TOKEN_ALIASES.get(token, token) for token in _plain_text(value).split()]
    removed = True
    while tokens and removed:
        removed = False
        for suffix in _CITY_SUFFIXES:
            if tuple(tokens[-len(suffix) :]) == suffix:
                del tokens[-len(suffix) :]
                removed = True
                break
    return " ".join(tokens)


class CensusPlacesGazetteer:
    """In-memory deterministic index loaded from the vendored Census archive."""

    def __init__(self, places: Iterable[GazetteerPlace]):
        self.places = tuple(places)
        index: dict[tuple[str, str], list[GazetteerPlace]] = {}
        for place in self.places:
            index.setdefault((place.state_code, place.normalized_city), []).append(place)
        self._index = {key: tuple(value) for key, value in index.items()}

    @classmethod
    def from_zip(
        cls,
        path: Path | str = DEFAULT_GAZETTEER_PATH,
        *,
        verify_checksum: bool = True,
    ) -> "CensusPlacesGazetteer":
        archive_path = Path(path)
        archive_bytes = archive_path.read_bytes()
        if verify_checksum:
            actual = hashlib.sha256(archive_bytes).hexdigest()
            if actual != GAZETTEER_SHA256:
                raise ValueError(
                    f"Census gazetteer checksum mismatch: expected {GAZETTEER_SHA256}, got {actual}"
                )
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = [name for name in archive.namelist() if name.casefold().endswith(".txt")]
            if len(names) != 1:
                raise ValueError("Census Places archive must contain exactly one text table")
            with archive.open(names[0]) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"), delimiter="|")
                required = {
                    "USPS",
                    "GEOID",
                    "NAME",
                    "LSAD",
                    "FUNCSTAT",
                    "INTPTLAT",
                    "INTPTLONG",
                }
                if not reader.fieldnames or not required <= set(reader.fieldnames):
                    raise ValueError("Census Places table is missing required columns")
                places = [
                    GazetteerPlace(
                        geoid=row["GEOID"].strip(),
                        state_code=row["USPS"].strip(),
                        place_name=row["NAME"].strip(),
                        normalized_city=normalize_city(row["NAME"]),
                        latitude=float(row["INTPTLAT"]),
                        longitude=float(row["INTPTLONG"]),
                        lsad=row["LSAD"].strip(),
                        function_status=row["FUNCSTAT"].strip(),
                    )
                    for row in reader
                    if row["USPS"].strip() in STATE_TO_REGION
                ]
        covered = {place.state_code for place in places}
        if covered != set(STATE_TO_REGION):
            missing = sorted(set(STATE_TO_REGION) - covered)
            raise ValueError(f"Census Places table is missing jurisdictions: {missing}")
        return cls(places)

    def lookup(self, city: object, state: object, country: object = "US") -> GeocodeResult:
        country_code = normalize_country(country)
        raw_city = str(city or "").strip()
        normalized_city = normalize_city(raw_city)
        state_code = normalize_state(state)
        region_code = STATE_TO_REGION.get(state_code or "")
        if country_code != "US":
            return _not_found(
                reason="country_not_supported",
                country=country_code,
                state_code=state_code,
                city=raw_city,
                normalized_city=normalized_city,
                region_code=region_code,
            )
        if not normalized_city or not state_code:
            reason = "missing_city" if not normalized_city else "unknown_state"
            return _not_found(
                reason=reason,
                country=country_code,
                state_code=state_code,
                city=raw_city,
                normalized_city=normalized_city,
                region_code=region_code,
            )
        candidates = self._index.get((state_code, normalized_city), ())
        if not candidates:
            return _not_found(
                reason="city_not_found",
                country=country_code,
                state_code=state_code,
                city=raw_city,
                normalized_city=normalized_city,
                region_code=region_code,
            )
        if len(candidates) > 1:
            exact = [place for place in candidates if _plain_text(place.place_name) == _plain_text(raw_city)]
            if len(exact) != 1:
                return _not_found(
                    reason="ambiguous_city",
                    country=country_code,
                    state_code=state_code,
                    city=raw_city,
                    normalized_city=normalized_city,
                    region_code=region_code,
                )
            candidates = tuple(exact)
        place = candidates[0]
        return GeocodeResult(
            state="found",
            reason=None,
            country="US",
            state_code=place.state_code,
            city=raw_city,
            normalized_city=place.normalized_city,
            region_code=STATE_TO_REGION[place.state_code],
            latitude=place.latitude,
            longitude=place.longitude,
            matched_place_name=place.place_name,
            geoid=place.geoid,
        )


def _not_found(
    *,
    reason: str,
    country: str,
    state_code: str | None,
    city: str,
    normalized_city: str,
    region_code: str | None,
) -> GeocodeResult:
    return GeocodeResult(
        state="not_found",
        reason=reason,
        country=country,
        state_code=state_code,
        city=city,
        normalized_city=normalized_city,
        region_code=region_code,
        latitude=None,
        longitude=None,
        matched_place_name=None,
        geoid=None,
    )


def normalize_country(value: object) -> str:
    normalized = _plain_text(value)
    if normalized in {"", "us", "usa", "united states", "united states of america"}:
        return "US"
    return str(value or "").strip()


@lru_cache(maxsize=1)
def default_gazetteer() -> CensusPlacesGazetteer:
    return CensusPlacesGazetteer.from_zip()


def prepare_actor_geography(
    payload: Mapping[str, object],
    *,
    gazetteer: CensusPlacesGazetteer | None = None,
) -> PreparedActorGeography:
    """Discard supplied derived values and deterministically prepare actor locations."""
    gazetteer = gazetteer or default_gazetteer()
    actor_values = dict(payload)
    for key in _DERIVED_INPUT_KEYS:
        actor_values.pop(key, None)

    raw_locations = payload.get("locations")
    if isinstance(raw_locations, list) and raw_locations:
        locations = [dict(value) for value in raw_locations if isinstance(value, Mapping)]
    else:
        locations = [
            {
                "location_name": payload.get("location_name"),
                "country": payload.get("country"),
                "state": payload.get("state_code") or payload.get("state"),
                "city": payload.get("location_city") or payload.get("city"),
            }
        ]
    if not locations:
        locations = [{}]

    is_multi_location = bool(payload.get("is_multi_location")) or len(locations) > 1
    primary_index = next(
        (index for index, location in enumerate(locations) if bool(location.get("is_primary"))),
        0,
    )
    prepared: list[PreparedLocation] = []
    for index, location in enumerate(locations):
        result = gazetteer.lookup(
            location.get("city") or location.get("location_city"),
            location.get("state_code") or location.get("state"),
            location.get("country") or "US",
        )
        prepared.append(
            PreparedLocation(
                location_name=str(location.get("location_name") or "").strip() or None,
                is_primary=index == primary_index,
                result=result,
            )
        )

    actor_values["is_multi_location"] = is_multi_location
    for key in ("state", "city", "locations"):
        actor_values.pop(key, None)
    if is_multi_location:
        for key in ("country", "location_city", "state_code"):
            actor_values.pop(key, None)
    else:
        result = prepared[0].result
        actor_values.update(
            {
                "country": result.country,
                "location_city": result.city or None,
                "state_code": result.state_code,
                "region_code": result.region_code,
                "latitude": result.latitude,
                "longitude": result.longitude,
            }
        )

    return PreparedActorGeography(
        actor_values=actor_values,
        locations=tuple(prepared),
        failures=tuple(location for location in prepared if not location.result.found),
    )


def distance_miles(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in miles using the haversine formula."""
    lat_a, lon_a, lat_b, lon_b = map(
        math.radians, (latitude_a, longitude_a, latitude_b, longitude_b)
    )
    delta_latitude = lat_b - lat_a
    delta_longitude = lon_b - lon_a
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(haversine))
