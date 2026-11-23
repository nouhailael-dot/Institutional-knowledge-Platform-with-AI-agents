"""Personal pages (GHUS, 23 Nov 2026).

Everything a person does in Compass is theirs alone: their maps, their Monitor
and Update requests (and the scheduled runs of those requests), their Data Feed
imports and map saves, their Review Results and their Pending Deletion. The
Ecosystem Directory is the one shared page, showing each record's owner. An
administrator's own pages are personal too; everyone's work is seen only on
Users, Usage and Costs and Audit History.

Visible to the signed-in person: what they own, and what has no recorded owner -
made before accounts went live (20 Nov 2026) - which stays shared with everyone
(GHUS's choice). Nothing is reassigned or guessed. Without individual accounts
(the shared login) everything is visible, as before.

Fails closed: when owners cannot be read, the page or action is refused, never
shown in full. Someone else's item answers "not found", so its existence is not
revealed either.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from src.identity import current_account

logger = logging.getLogger(__name__)

UNAVAILABLE = "Compass could not check whose items these are right now. Try again in a moment."

# Path values that name something personal, and what they name.
PERSONAL_PATHS = {"job_id": "map", "subscription_id": "request", "run_id": "import"}

# Set by backend.app: candidate id -> its review run id (None when unknown).
candidate_run: Callable[[str], str | None] | None = None


class OwnershipUnavailable(RuntimeError):
    """Owners could not be read: refuse rather than show everyone's items."""

    def __init__(self, message: str = UNAVAILABLE):
        super().__init__(message)
        self.message = message


def _store():
    from backend.accounts_routes import accounts_store
    return accounts_store()


def _read(fn, *args):
    try:
        return fn(*args)
    except OwnershipUnavailable:
        raise
    except Exception as exc:
        logger.exception("Personal pages: owners could not be read")
        raise OwnershipUnavailable() from exc


def visible_to(owner_id: str | None, user_id: str) -> bool:
    """Theirs, or shared (no recorded owner: made before accounts)."""
    return owner_id is None or owner_id == user_id


def keep(rows: Iterable[dict], entity_type: str, key: str = "id") -> list[dict]:
    """Only the signed-in person's own rows, plus those with no recorded owner, which
    are marked ``shared`` (from before accounts). New dicts: cached rows never change."""
    rows = list(rows)
    me = current_account()
    if me is None:
        return rows
    owners = _read(_store().owner_ids, entity_type)
    out = []
    for row in rows:
        owner = owners.get(str(row.get(key) or ""))
        if owner is None:
            out.append({**row, "shared": True})
        elif owner == me.user_id:
            out.append(row)
    return out


def visible_test(entity_type: str) -> Callable[[str], bool]:
    """id -> visible to the signed-in person, read now (for work that runs later,
    like Ask's streamed answer, after the request's sign-in context is gone)."""
    me = current_account()
    if me is None:
        return lambda _id: True
    owners = _read(_store().owner_ids, entity_type)
    return lambda entity_id: visible_to(owners.get(str(entity_id)), me.user_id)


def keep_checks(rows: Iterable[dict], key: str = "check_id") -> list[dict]:
    """One-off organization updates: only those whose check the person ran (or unknown)."""
    rows = list(rows)
    me = current_account()
    if me is None:
        return rows
    owners = _read(_store().check_owners)
    return [r for r in rows if visible_to(owners.get(str(r.get(key) or "")), me.user_id)]


def may_open(entity_type: str, entity_id) -> bool:
    me = current_account()
    if me is None or not entity_id:
        return True
    return visible_to(_read(_store().owner_of, entity_type, str(entity_id)), me.user_id)


def review_run_owners(run_ids: Iterable[str]) -> dict[str, str | None]:
    """Review run id -> the account it belongs to (None: shared, no owner recorded).

    A Data Feed import or map save: the importer. A Discovery or Update run: the
    owner of its Monitor request (scheduled runs included), or, for a one-off
    organization update, whoever ran the check. Anything else: no owner.
    """
    store = _store()
    run_ids = sorted({str(r) for r in run_ids if r})
    imports = _read(store.owner_ids, "import")
    requests = _read(store.owner_ids, "request")
    links = _read(store.review_run_links, run_ids)
    checks = _read(store.check_owners) if any(v.get("check") for v in links.values()) else {}
    out: dict[str, str | None] = {}
    for run in run_ids:
        owner = None
        if run.startswith("datafeed:"):
            owner = imports.get(run.split(":", 1)[1])
        elif run in links:
            link = links[run]
            owner = requests.get(str(link.get("request") or "")) or checks.get(str(link.get("check") or ""))
        out[run] = owner
    return out


def hidden_review_runs(run_ids: Iterable[str]) -> frozenset[str]:
    """The review runs that belong to someone else (empty without accounts)."""
    me = current_account()
    if me is None:
        return frozenset()
    return frozenset(run for run, owner in review_run_owners(run_ids).items()
                     if not visible_to(owner, me.user_id))


def may_open_candidate(candidate_id: str) -> bool:
    me = current_account()
    if me is None or candidate_run is None:
        return True
    run = _read(candidate_run, str(candidate_id))
    if not run:
        return True            # unknown here: the route answers "not found" itself
    return visible_to(review_run_owners([run]).get(run), me.user_id)


def may_open_deletion(deletion_id: str) -> bool:
    me = current_account()
    if me is None:
        return True
    owner = _read(_store().deletion_owner, str(deletion_id))
    return owner is None or owner == me.user_id


def may_open_check(check_id: str) -> bool:
    me = current_account()
    if me is None:
        return True
    return visible_to(_read(_store().check_owners).get(str(check_id)), me.user_id)


def allowed_path(values: dict[str, str]) -> bool:
    """Whether the signed-in person may act on what a route's path names.

    Raises OwnershipUnavailable when that cannot be told."""
    for name, entity_type in PERSONAL_PATHS.items():
        if values.get(name) and not may_open(entity_type, values[name]):
            return False
    if values.get("candidate_id") and not may_open_candidate(values["candidate_id"]):
        return False
    if values.get("deletion_id") and not may_open_deletion(values["deletion_id"]):
        return False
    if values.get("check_id") and not may_open_check(values["check_id"]):
        return False
    return True
