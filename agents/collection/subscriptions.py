"""WS6: actor update subscriptions.

Replaces the default weekly all-sector actor sweep with opt-in, scoped requests.
GHUS asks for a set of actors, sectors, topics or places to be kept current for
a stated period; nothing else is swept. The EVENT schedule is untouched.

Four rules this module exists to enforce, in the order they matter:

1. **Only active, in-period subscriptions run.** Paused, cancelled and expired
   ones are skipped, and a subscription whose end date has passed is reported as
   expired rather than quietly run one last time.
2. **Deduplicate before discovering.** Architecture V2 rule 1 is to check what
   is already mapped before searching. An actor already in the map is not
   rediscovered; it is listed as already known.
3. **Dry run is the default.** A live run has to be asked for explicitly, and
   dry and live runs load the same candidates so the funnel counts can be
   compared.
4. **Nothing is ever auto-verified or auto-rejected.** Discovered actors enter
   the staged to review flow and wait for a GHUS person.

Trigger policy, cadence options and ranking weights are configuration, not
constants here: they are awaiting GHUS sign-off (brief WS6 item 4).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

CADENCE_DAYS: dict[str, int | None] = {
    "once": None,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 91,
}
ACTIVE = "active"
PAUSED = "paused"
EXPIRED = "expired"
CANCELLED = "cancelled"
RUNNABLE_STATUSES = (ACTIVE,)
DISCOVERY_PAGE = "discovery_page"
# Actor update requests (migration 570): keep chosen actors current.
ACTOR_UPDATES = "actor_updates"
REQUESTED_VIA = ("map_verification", "review_updates", DISCOVERY_PAGE, ACTOR_UPDATES)
# Mirrors the migration 570 hard bound; the configured ceiling is lower.
MAX_USD_PER_RUN = 5.0
# Mirrors the migration 550 constraints, so a bad request is refused before it
# reaches the database rather than by it.
MAX_FOCUS_TERMS = 8
MAX_NEW_ACTORS_PER_RUN = 50
DEFAULT_NEW_ACTORS_PER_RUN = 10
MAX_TITLE_CHARS = 160


class SubscriptionError(ValueError):
    """A subscription is malformed or is being asked to do something it may not."""


@dataclass(frozen=True)
class Subscription:
    subscription_id: str
    end_date: date
    cadence: str
    requested_via: str
    start_date: date = field(default_factory=date.today)
    status: str = ACTIVE
    actor_ids: tuple[str, ...] = ()
    sector_codes: tuple[str, ...] = ()
    topic_ids: tuple[str, ...] = ()
    country: str | None = None
    state_code: str | None = None
    city: str | None = None
    region_code: str | None = None
    # Nullable until authentication exists. Never defaulted, never inferred.
    requested_by: str | None = None
    last_run_at: date | None = None
    # Discovery requests (migration 550).
    title: str | None = None
    focus_terms: tuple[str, ...] = ()
    max_new_actors_per_run: int = DEFAULT_NEW_ACTORS_PER_RUN
    # Actor update requests (migration 570). Validated in full by
    # agents/collection/actor_updates.py; here only what the table enforces.
    update_options: dict = field(default_factory=dict)
    max_usd_per_run: float | None = None

    def __post_init__(self) -> None:
        if self.requested_via not in REQUESTED_VIA:
            raise SubscriptionError(
                f"requested_via must be one of {list(REQUESTED_VIA)}, got {self.requested_via!r}"
            )
        if self.cadence not in CADENCE_DAYS:
            raise SubscriptionError(
                f"cadence must be one of {sorted(CADENCE_DAYS)}, got {self.cadence!r}"
            )
        if self.status not in (ACTIVE, PAUSED, EXPIRED, CANCELLED):
            raise SubscriptionError(f"unknown subscription status {self.status!r}")
        if self.end_date < self.start_date:
            raise SubscriptionError("a subscription cannot end before it starts")
        if not self.has_scope:
            raise SubscriptionError(
                "a subscription needs a scope: actors, sectors, topics or a place. "
                "An unscoped subscription is the all-sector sweep it replaces."
            )
        if self.requested_via == DISCOVERY_PAGE and not (self.sector_codes or self.topic_ids):
            raise SubscriptionError(
                "a discovery request needs a topic or sector: an area alone is the "
                "unscoped sweep this design replaces"
            )
        if self.requested_via == ACTOR_UPDATES:
            if not self.update_options.get("scope"):
                raise SubscriptionError("an actor update request needs a scope")
            if self.max_usd_per_run is None or not 0 < float(self.max_usd_per_run) <= MAX_USD_PER_RUN:
                raise SubscriptionError(
                    f"an actor update request needs a spend ceiling above $0 and at most "
                    f"${MAX_USD_PER_RUN:.2f} per run")
        if self.title is not None and not 1 <= len(self.title.strip()) <= MAX_TITLE_CHARS:
            raise SubscriptionError(f"a title must be 1 to {MAX_TITLE_CHARS} characters")
        if len(self.focus_terms) > MAX_FOCUS_TERMS:
            raise SubscriptionError(f"at most {MAX_FOCUS_TERMS} sub-topic terms")
        if not 1 <= int(self.max_new_actors_per_run) <= MAX_NEW_ACTORS_PER_RUN:
            raise SubscriptionError(
                f"max_new_actors_per_run must be 1 to {MAX_NEW_ACTORS_PER_RUN}"
            )

    @property
    def is_discovery_request(self) -> bool:
        return self.requested_via == DISCOVERY_PAGE

    @property
    def is_actor_update_request(self) -> bool:
        return self.requested_via == ACTOR_UPDATES

    @property
    def has_scope(self) -> bool:
        return bool(
            self.actor_ids or self.sector_codes or self.topic_ids
            or (self.country or "").strip() or self.state_code
            or (self.city or "").strip() or self.region_code
        )

    def is_expired(self, today: date) -> bool:
        return today > self.end_date

    def is_due(self, today: date) -> bool:
        """Whether this subscription should run today.

        Status first, then period, then cadence. A paused subscription is never
        due no matter how long it has been waiting.
        """

        if self.status not in RUNNABLE_STATUSES:
            return False
        if today < self.start_date or self.is_expired(today):
            return False
        if self.last_run_at is None:
            return True
        interval = CADENCE_DAYS[self.cadence]
        if interval is None:
            return False  # 'once' has already run
        return today >= self.last_run_at + timedelta(days=interval)

    def next_due(self, today: date) -> date | None:
        """The next date this subscription will run, or None if it never will again."""

        if self.status not in RUNNABLE_STATUSES or self.is_expired(today):
            return None
        if self.last_run_at is None:
            return max(today, self.start_date)
        interval = CADENCE_DAYS[self.cadence]
        if interval is None:
            return None
        nxt = max(self.last_run_at + timedelta(days=interval), self.start_date)
        return nxt if nxt <= self.end_date else None

    def skip_reason(self, today: date) -> str | None:
        """Why this subscription is not running, in words a report can print."""

        if self.status == PAUSED:
            return "paused"
        if self.status == CANCELLED:
            return "cancelled"
        if self.status == EXPIRED or self.is_expired(today):
            return "expired"
        if today < self.start_date:
            return "not_started"
        if not self.is_due(today):
            return "not_due"
        return None


@dataclass(frozen=True)
class SubscriptionPlan:
    """What one subscription would do. Computing this writes nothing."""

    subscription_id: str
    dry_run: bool
    scope: dict[str, object]
    already_mapped: tuple[str, ...]
    to_discover: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "found": len(self.already_mapped) + len(self.to_discover),
            "deduplicated": len(self.already_mapped),
            "staged": len(self.to_discover),
        }


def due_subscriptions(
    subscriptions: Iterable[Subscription], *, today: date | None = None
) -> tuple[tuple[Subscription, ...], dict[str, str]]:
    """Split subscriptions into the ones to run and the ones skipped, with reasons."""

    when = today or date.today()
    due: list[Subscription] = []
    skipped: dict[str, str] = {}
    for item in sorted(subscriptions, key=lambda row: row.subscription_id):
        reason = item.skip_reason(when)
        if reason is None:
            due.append(item)
        else:
            skipped[item.subscription_id] = reason
    return tuple(due), skipped


def _normalise(values: Iterable[str]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def plan_subscription_run(
    subscription: Subscription,
    candidates: Sequence[str],
    mapped_identifiers: Iterable[str],
    *,
    dry_run: bool = True,
) -> SubscriptionPlan:
    """Plan one run: deduplicate against the map, then stage what is left.

    ``candidates`` are identifiers a discovery step would look at — a name, a
    domain, an actor id. ``mapped_identifiers`` is what the map already holds.
    Checking the map first is Architecture V2 rule 1, and doing it here means a
    subscription cannot spend a fetch budget rediscovering what GHUS already has.

    Comparison is case-insensitive and whitespace-trimmed, because "UC Davis"
    and "uc davis " are the same organisation and treating them as two is how
    duplicates get created.
    """

    if subscription.status not in RUNNABLE_STATUSES:
        raise SubscriptionError(
            f"subscription {subscription.subscription_id} is {subscription.status} and must not run"
        )
    mapped = _normalise(mapped_identifiers)
    seen: set[str] = set()
    already: list[str] = []
    fresh: list[str] = []
    for candidate in candidates:
        key = str(candidate).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        (already if key in mapped else fresh).append(str(candidate).strip())
    # The per-run ceiling: one request can never flood the review queue.
    fresh = fresh[: subscription.max_new_actors_per_run]
    return SubscriptionPlan(
        subscription_id=subscription.subscription_id,
        dry_run=dry_run,
        scope={
            "actor_ids": list(subscription.actor_ids),
            "sector_codes": list(subscription.sector_codes),
            "topic_ids": list(subscription.topic_ids),
            "country": subscription.country,
            "state_code": subscription.state_code,
            "city": subscription.city,
            "region_code": subscription.region_code,
            "focus_terms": list(subscription.focus_terms),
            "max_new_actors_per_run": subscription.max_new_actors_per_run,
        },
        already_mapped=tuple(already),
        to_discover=tuple(fresh),
    )


def run_configuration(config: dict[str, object] | None) -> dict[str, object]:
    """The subscription settings, read from configuration rather than hard-coded.

    Trigger policy, cadence options, the monthly default and the sector ranking
    weight all need GHUS sign-off (brief WS6 item 4). They live in
    config/architecture_v2.yaml so a decision changes a value, not the code.
    """

    section = (config or {}).get("actor_update_subscriptions") or {}
    if not isinstance(section, dict):
        raise SubscriptionError("actor_update_subscriptions configuration must be a mapping")
    missing = [
        key for key in ("default_cadence", "allowed_cadences", "sector_rank_weight",
                        "dry_run_default", "max_duration_days")
        if key not in section
    ]
    if missing:
        raise SubscriptionError(
            "actor_update_subscriptions configuration is missing: " + ", ".join(missing)
        )
    if section["default_cadence"] not in section["allowed_cadences"]:
        raise SubscriptionError("the default cadence is not in the allowed list")
    unknown = set(section["allowed_cadences"]) - set(CADENCE_DAYS)
    if unknown:
        raise SubscriptionError(f"unknown cadence(s) in configuration: {sorted(unknown)}")
    return dict(section)
