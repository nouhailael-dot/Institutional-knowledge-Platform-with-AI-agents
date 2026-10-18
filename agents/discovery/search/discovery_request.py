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

    def __post_init__(self) -> None:
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
        return {
            "subscription_id": self.subscription_id,
            "title": self.title,
            "sector_codes": list(self.sector_codes),
            "focus_terms": list(self.focus_terms),
            "states": list(self.states),
            "region_code": self.region_code,
            "city": self.city,
            "max_new_actors": self.max_new_actors,
        }


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


def apply_new_actor_cap(candidates, cap: int):
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
                    f"Held back: this request adds at most {cap} new actors per run, "
                    f"and {cap} stronger candidates were found. "
                    + (candidate.triage_reason or "")
                ).strip(),
            ))
        else:
            result.append(candidate)
    return result, held
