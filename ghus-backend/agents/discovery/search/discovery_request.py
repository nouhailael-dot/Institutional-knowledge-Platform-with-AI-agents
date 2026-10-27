"""Actor discovery scoped to what a person asked for.

The weekly actor sweep chose its own targets: the thinnest existing hubs, every
actor type, every week. Discovery now runs only for a request made on the
Discovery page - "for three months, keep me updated on energy actors in the
Northeast, especially battery storage" - and everything a run does is derived
from that request:

  * the search queries   - the request's sub-topic terms (or its topic) in its
                           area, across actor types; no other hub or sector
  * the quality gates    - an actor outside the requested sector or area is
                           rejected; one that never mentions the sub-topic is
                           held for review rather than accepted
  * the topic it is for  - the requested topic, not whichever hub a query hit
  * how much it may add  - at most ``max_new_actors_per_run`` per run

Nothing here writes. A request is read from ``actor_update_subscription``
(migrations 540/550) and turned into queries and a scope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from agents.common.geography import REGION_STATES, STATE_NAMES, normalize_state
from agents.discovery.search.actor_quality import Scope

# What each use case looks like as a search, when the request names one theme.
_USE_CASE_TEMPLATES = (
    "{theme} research center {geo}",
    "{theme} accelerator program {geo}",
    "{theme} industry partnership {geo}",
    "{theme} pilot project {geo}",
    "{theme} innovation hub {geo}",
)
# Actor types that read naturally in a search; the full enum still drives
# classification later.
_QUERY_ACTOR_TYPES = (
    "university", "research institute", "startup", "company", "nonprofit",
    "accelerator", "government agency", "investor",
)


class DiscoveryRequestError(ValueError):
    """A request cannot be turned into a scoped discovery run."""


@dataclass(frozen=True)
class DiscoveryRequest:
    subscription_id: str
    title: str
    sector_codes: tuple[str, ...]
    focus_terms: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    region_code: str | None = None
    city: str | None = None
    max_new_actors: int = 10
    # Event and people requests (migration 580). An actor request leaves them
    # at their defaults and runs exactly as before.
    entity: str = "actor"
    date_from: date | None = None
    date_to: date | None = None
    event_types: tuple[str, ...] = ()
    institution: str | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        if self.entity not in ("actor", "event", "person"):
            raise DiscoveryRequestError(f"unknown discovery entity {self.entity!r}")
        if not self.sector_codes:
            raise DiscoveryRequestError(
                "a discovery request needs a topic; an area alone is the unscoped sweep"
            )
        if self.max_new_actors < 1:
            raise DiscoveryRequestError("max_new_actors must be at least 1")

    @classmethod
    def from_subscription(
        cls, subscription, *, topic_codes: Mapping[str, str] | None = None
    ) -> DiscoveryRequest:
        """Build from an ``agents.collection.subscriptions.Subscription``.

        ``topic_codes`` maps topic_id -> code; topics mirror sectors one-to-one
        (AGRI, AI, ... WATER), so a request made by topic searches that sector.
        """

        codes = [str(code).upper() for code in subscription.sector_codes]
        for topic_id in subscription.topic_ids:
            code = (topic_codes or {}).get(str(topic_id))
            if code is None:
                raise DiscoveryRequestError(f"unknown topic {topic_id}")
            codes.append(code.upper())
        state = normalize_state(subscription.state_code) if subscription.state_code else None
        if subscription.state_code and state is None:
            raise DiscoveryRequestError(f"unknown state {subscription.state_code!r}")
        region = (subscription.region_code or "").strip() or None
        if region and region not in REGION_STATES:
            raise DiscoveryRequestError(f"unknown region {region!r}")
        states = (state,) if state else REGION_STATES.get(region or "", ())
        options = dict(getattr(subscription, "discovery_options", None) or {})

        def day(key: str) -> date | None:
            return date.fromisoformat(str(options[key])) if options.get(key) else None

        return cls(
            subscription_id=str(subscription.subscription_id),
            title=(subscription.title or "").strip() or "Discovery request",
            sector_codes=tuple(dict.fromkeys(codes)),
            focus_terms=tuple(
                term.strip() for term in subscription.focus_terms if term.strip()
            ),
            states=tuple(states),
            region_code=region,
            city=(subscription.city or "").strip() or None,
            max_new_actors=int(subscription.max_new_actors_per_run),
            entity=str(getattr(subscription, "discovery_entity", None) or "actor"),
            date_from=day("date_from"),
            date_to=day("date_to"),
            event_types=tuple(str(t) for t in options.get("event_types") or ()),
            institution=" ".join(str(options.get("institution") or "").split()) or None,
            role=" ".join(str(options.get("role") or "").split()) or None,
        )

    def quality_scope(self) -> Scope:
        return Scope(
            sector_codes=self.sector_codes,
            states=self.states,
            region_code=self.region_code,
            focus_terms=self.focus_terms,
        )

    def geographies(self) -> list[str]:
        """Search geography: the city if given, else each state by name, else the US."""

        if self.city and len(self.states) == 1:
            return [f"{self.city} {STATE_NAMES.get(self.states[0], self.states[0])}"]
        names = [STATE_NAMES.get(code, code) for code in self.states]
        return names or ["United States"]

    def themes(self, sectors: Sequence[Mapping[str, str]]) -> list[str]:
        """The sub-topic terms if given; otherwise the requested sectors by name."""

        if self.focus_terms:
            return list(self.focus_terms)
        names = {str(s.get("code") or "").upper(): str(s.get("name") or "") for s in sectors}
        return [
            names.get(code, code).lower() for code in self.sector_codes if names.get(code, code)
        ]

    def describe(self) -> dict[str, object]:
        described: dict[str, object] = {
            "subscription_id": self.subscription_id,
            "title": self.title,
            "sector_codes": list(self.sector_codes),
            "focus_terms": list(self.focus_terms),
            "states": list(self.states),
            "region_code": self.region_code,
            "city": self.city,
            "max_new_actors": self.max_new_actors,
        }
        if self.entity != "actor":
            described.update({
                "entity": self.entity,
                "date_from": self.date_from.isoformat() if self.date_from else None,
                "date_to": self.date_to.isoformat() if self.date_to else None,
                "event_types": list(self.event_types),
                "institution": self.institution,
                "role": self.role,
            })
        return described


def request_actor_queries(
    request: DiscoveryRequest,
    sectors: Sequence[Mapping[str, str]],
    *,
    actor_types: Iterable[str] = _QUERY_ACTOR_TYPES,
    max_queries: int = 24,
    rotation_seed: int = 0,
) -> tuple[list[str], dict[str, object]]:
    """Queries for one request: theme x actor type x place, then use cases.

    The grid is walked so every theme and every place is reached before any
    combination repeats; a cap therefore trims depth, never a whole theme or a
    whole state. Rotation varies the order from run to run so a recurring
    request does not ask the same twenty questions every time.
    """

    if max_queries <= 0:
        raise DiscoveryRequestError("max_queries must be positive")
    themes = request.themes(sectors)
    geos = request.geographies()
    types = [t for t in actor_types if str(t).strip()]
    if not themes or not types:
        raise DiscoveryRequestError("a request produced no searchable theme")

    grid = [
        (themes[i % len(themes)], types[(i + rotation_seed) % len(types)],
         geos[(i + rotation_seed) % len(geos)])
        for i in range(len(themes) * len(types) * len(geos))
    ]
    use_case_budget = max(1, max_queries // 4)
    grid_budget = max_queries - use_case_budget

    queries: list[str] = []
    plan: list[dict[str, object]] = []
    seen: set[str] = set()
    for theme, actor_type, geo in grid:
        if len(queries) >= grid_budget:
            break
        query = " ".join(f"{actor_type} {theme} {geo}".split())
        if query.casefold() in seen:
            continue
        seen.add(query.casefold())
        queries.append(query)
        plan.append({"query": query, "request_title": request.title, "theme": theme,
                     "geography": geo, "actor_type": actor_type})

    use_case_queries: list[str] = []
    use_case_plan: list[dict[str, object]] = []
    for index in range(len(themes) * len(_USE_CASE_TEMPLATES) * len(geos)):
        if len(use_case_queries) >= use_case_budget:
            break
        theme = themes[index % len(themes)]
        template = _USE_CASE_TEMPLATES[(index + rotation_seed) % len(_USE_CASE_TEMPLATES)]
        geo = geos[(index + rotation_seed) % len(geos)]
        query = " ".join(template.format(theme=theme, geo=geo).split())
        if query.casefold() in seen:
            continue
        seen.add(query.casefold())
        use_case_queries.append(query)
        use_case_plan.append({"query": query, "request_title": request.title, "theme": theme,
                              "geography": geo, "query_type": "use_case"})

    return queries, {
        "discovery_request": request.describe(),
        "actor_types": types,
        "actor_type_enum": [],
        "query_grid_size": len(grid),
        "selected_hubs": [],
        "distinct_hubs_covered": 0,
        "query_plan": plan,
        "use_case_queries": use_case_queries,
        "use_case_query_plan": use_case_plan,
        "use_case_query_count": len(use_case_queries),
    }


def apply_new_actor_cap(candidates, cap: int, *, noun: str = "actors"):
    """Keep at most ``cap`` candidates that would reach the map or the queue.

    Accepted candidates rank first, then review candidates, each by engagement
    priority and then relevance. The
    rest keep their score and evidence on the candidate row but get no band, so
    they are neither created nor queued; their reason says why. Returns the new
    list (same order as given) and how many were held back.
    """

    from dataclasses import replace

    live = [c for c in candidates if c.score_band in ("auto_high", "review")]

    def priority(c) -> float:
        # GHUS engagement priority orders the kept set; it never excludes.
        return float((getattr(c, "score_breakdown", None) or {}).get("priority_score", 0.0))

    ranked = sorted(
        live,
        key=lambda c: (c.score_band != "auto_high", -priority(c), -float(c.fit_score or 0.0),
                       c.url),
    )
    keep = {c.candidate_id for c in ranked[:cap]}
    held = 0
    result = []
    for candidate in candidates:
        if candidate.score_band in ("auto_high", "review") and candidate.candidate_id not in keep:
            held += 1
            result.append(replace(
                candidate,
                score_band=None,
                triage_verdict="capped",
                triage_reason=(
                    f"Held back: this request adds at most {cap} new {noun} per run, "
                    f"and {cap} stronger candidates were found. "
                    + (candidate.triage_reason or "")
                ).strip(),
            ))
        else:
            result.append(candidate)
    return result, held


# ------------------------------------------------------------ events and people
#
# The same request, for events or people. Queries come only from what was
# asked - the topic or sub-topics, the event types or the role and institution,
# the area and the dates - never from the hub grid the automatic runs use.

# The event types a request may choose (agents/collection/subscriptions.py);
# all of them when it names none. The query cap keeps the search bounded.
_DEFAULT_EVENT_TYPES = ("conference", "summit", "symposium", "forum", "training")
_DEFAULT_ROLES = ("researcher", "director")


def _years(request: DiscoveryRequest, today: date) -> str:
    start = request.date_from or today
    end = request.date_to or date(start.year + 1, start.month, 1)
    return " ".join(str(y) for y in range(start.year, end.year + 1)[:3])


def request_event_queries(
    request: DiscoveryRequest,
    sectors: Sequence[Mapping[str, str]],
    *,
    today: date,
    max_queries: int = 24,
) -> tuple[list[str], dict[str, object]]:
    """Theme x event type x place, in the requested years; then official pages.

    Every theme and place is reached before a combination repeats, as for
    actors. A quarter of the budget asks for the event's own site, so an
    official source is found before a listing page.
    """
    if max_queries <= 0:
        raise DiscoveryRequestError("max_queries must be positive")
    themes = request.themes(sectors)
    if not themes:
        raise DiscoveryRequestError("a request produced no searchable theme")
    types = list(request.event_types or _DEFAULT_EVENT_TYPES)
    geos = request.geographies()
    years = _years(request, today)
    # A quarter for official sites - no more than there are theme and type pairs.
    official_budget = max(1, min(max_queries // 4, len(themes) * len(types)))
    queries: list[str] = []
    plan: list[dict[str, object]] = []
    seen: set[str] = set()

    def add(query: str, **meta) -> None:
        query = " ".join(query.split())
        if query.casefold() not in seen:
            seen.add(query.casefold())
            queries.append(query)
            plan.append({"query": query, "request_title": request.title, **meta})

    # Every combination, places and themes first: a cap trims event types,
    # never a whole theme or place. (Indexing all three lists by one counter
    # repeated pairs whenever two lists had the same length.)
    combos = [(theme, kind, geo) for kind in types for geo in geos for theme in themes]
    for theme, kind, geo in combos:
        if len(queries) >= max_queries - official_budget:
            break
        add(f"{theme} {kind} {geo} {years}", theme=theme, event_type=kind, geography=geo)
    for i in range(len(themes) * len(types)):
        if len(queries) >= max_queries:
            break
        theme, kind = themes[i % len(themes)], types[(i // len(themes)) % len(types)]
        add(f"{theme} {kind} {years} official site registration",
            theme=theme, event_type=kind, query_type="official_source")
    return queries, {"discovery_request": request.describe(), "query_plan": plan}


def request_person_queries(
    request: DiscoveryRequest,
    sectors: Sequence[Mapping[str, str]],
    *,
    max_queries: int = 24,
) -> tuple[list[str], dict[str, object]]:
    """Expertise x role x institution or place, worded to reach official profiles.

    "profile", "faculty" and "biography" bring institutional pages ahead of
    news and lists; a name in an article is never enough on its own.
    """
    if max_queries <= 0:
        raise DiscoveryRequestError("max_queries must be positive")
    themes = request.themes(sectors)
    if not themes:
        raise DiscoveryRequestError("a request produced no searchable theme")
    roles = [request.role] if request.role else list(_DEFAULT_ROLES)
    places = [request.institution] if request.institution else request.geographies()
    shapes = ("{role} {theme} {place} profile", "{theme} {role} {place} faculty",
              "{place} {theme} expert biography")
    queries: list[str] = []
    plan: list[dict[str, object]] = []
    seen: set[str] = set()
    for i in range(len(themes) * len(roles) * len(places) * len(shapes)):
        if len(queries) >= max_queries:
            break
        theme, role = themes[i % len(themes)], roles[i % len(roles)]
        place, shape = places[i % len(places)], shapes[(i // len(themes)) % len(shapes)]
        query = " ".join(shape.format(role=role, theme=theme, place=place).split())
        if query.casefold() in seen:
            continue
        seen.add(query.casefold())
        queries.append(query)
        plan.append({"query": query, "request_title": request.title, "theme": theme,
                     "role": role, "place": place})
    return queries, {"discovery_request": request.describe(), "query_plan": plan,
                     "sector_codes_covered": list(request.sector_codes)}


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def event_outside_request(record: Mapping[str, object], request: DiscoveryRequest) -> str | None:
    """Why an event falls outside what was asked, or None. Unknown is not outside.

    A date or a state the page does not state is left to the quality gates
    (missing, not out of scope).
    """
    start = _day(record.get("start_date"))
    if start and request.date_from and start < request.date_from:
        return (f"It takes place on {start.isoformat()}, before the requested dates "
                f"(from {request.date_from.isoformat()}).")
    if start and request.date_to and start > request.date_to:
        return (f"It takes place on {start.isoformat()}, after the requested dates "
                f"(to {request.date_to.isoformat()}).")
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    online = str((facts or {}).get("format") or "") == "online"
    state = normalize_state(record.get("state")) if record.get("state") else None
    if request.states and state and state not in request.states and not online:
        return f"It takes place in {STATE_NAMES.get(state, state)}, outside the requested area."
    return None


_ORG_WORDS = {"the", "of", "and", "at", "for", "in", "inc", "llc", "ltd", "co"}
# Words that make another institution of a similar name: "Michigan State
# University" is not the "University of Michigan".
_DISTINGUISHING = {"state", "tech", "technological", "technology", "institute", "college",
                   "polytechnic", "community", "medical", "northern", "southern", "eastern",
                   "western", "central", "christian", "baptist", "methodist"}


def _org_tokens(value: object) -> set[str]:
    import re

    return {w for w in re.findall(r"[a-z0-9]+", str(value or "").lower())
            if w not in _ORG_WORDS and len(w) > 2}


def person_outside_request(record: Mapping[str, object], request: DiscoveryRequest) -> str | None:
    """Why a person falls outside what was asked: another institution. Unknown is not outside."""
    if not request.institution or not record.get("affiliation"):
        return None
    asked, stated = _org_tokens(request.institution), _org_tokens(record.get("affiliation"))
    if asked and (not asked <= stated or (stated - asked) & _DISTINGUISHING):
        return (f"Works at {record.get('affiliation')}, not at the requested "
                f"{request.institution}.")
    return None
