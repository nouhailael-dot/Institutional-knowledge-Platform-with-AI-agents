"""Who did what, and who brought each record in (accounts Phase 3).

Two things, both tied to the signed-in account from the server session
(src.identity), never to a name or id sent by the browser:

* **One audit entry per change.** The sign-in middleware writes it after every
  successful change (POST, PUT, PATCH, DELETE) and every refusal. A route adds
  what only it knows with ``note(...)``: the decision taken, the record created,
  the fields edited.
* **Original ownership.** ``claim(...)`` records who brought a record, request,
  map or import into Compass, the moment it is created. The first claim wins and
  the database refuses any later change, so a later editor or reviewer never
  becomes the owner. Records from before accounts have no owner: "Not recorded".

Without individual accounts (the shared login) nobody is signed in and every
function here does nothing.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from src.identity import current_account

logger = logging.getLogger(__name__)

_notes: ContextVar[dict | None] = ContextVar("compass_audit_notes", default=None)

# Who brought a record in, by the route that created it.
ORIGINS = {"created", "imported", "discovered", "mapped", "requested"}
OWNED_TYPES = {"actor", "person", "event", "hub", "request", "map", "import"}


def begin() -> object:
    """Start collecting notes for this request (the middleware)."""
    return _notes.set({})


def end(token) -> dict:
    notes = _notes.get() or {}
    _notes.reset(token)
    return notes


def note(**details) -> None:
    """Add details to this request's audit entry (ignored outside a signed-in request)."""
    notes = _notes.get()
    if notes is not None:
        for key, value in details.items():
            if value is not None:
                notes[key] = value


def _store():
    from backend.accounts_routes import accounts_store
    return accounts_store()


def import_owner(source_run_id: str | None) -> str | None:
    """Who owns the Data Feed import a Review candidate came from ("datafeed:<run>")."""
    run = str(source_run_id or "")
    if current_account() is None or not run.startswith("datafeed:"):
        return None
    try:
        return _store().owner_of("import", run.split(":", 1)[1])
    except Exception:
        logger.exception("Could not read the owner of import %s", run)
        return None


def claim(entity_type: str, entity_id, origin: str, *, source_ref: str | None = None,
          owner_user_id: str | None = None) -> bool:
    """Record the original owner (first claim wins): the signed-in person, or the
    owner of the import a record came from (``owner_user_id``, read from the
    database, never from the request). Never fails the action it follows: an
    error is logged and noted in the audit entry."""
    account = current_account()
    if account is None or not entity_id:
        return False
    if entity_type not in OWNED_TYPES or origin not in ORIGINS:
        raise ValueError(f"unknown ownership {entity_type}/{origin}")
    try:
        won = _store().claim_owner(entity_type=entity_type, entity_id=str(entity_id),
                                   owner_user_id=owner_user_id or account.user_id, origin=origin,
                                   source_ref=str(source_ref) if source_ref else None)
    except Exception:
        logger.exception("Could not record the owner of %s %s", entity_type, entity_id)
        note(owner_not_recorded=f"{entity_type}:{entity_id}")
        return False
    notes = _notes.get()
    if notes is not None:
        notes.setdefault("owned", []).append({"type": entity_type, "id": str(entity_id), "origin": origin,
                                              "first": won})
        # A route that creates something (a map, a request) names it in its audit entry.
        notes.setdefault("entity_type", entity_type)
        notes.setdefault("entity_id", str(entity_id))
    return won


def record_usage(kind: str, reference, *, trigger: str = "manual", cost_usd: float | None = None,
                 cost_basis: str = "ledger", input_tokens: int | None = None, output_tokens: int | None = None,
                 detail: dict | None = None, account=None) -> bool:
    """Record who started a paid operation (accounts Phase 5). The cost stays in its
    ledger; ``cost_usd`` only for an operation that has none (Ask, an unapplied
    check). Never fails the operation it follows."""
    account = account or current_account()
    if account is None or not reference:
        return False
    try:
        return _store().record_usage(kind=kind, reference=str(reference), user_id=account.user_id,
                                     trigger=trigger, cost_usd=cost_usd, cost_basis=cost_basis,
                                     input_tokens=input_tokens, output_tokens=output_tokens, detail=detail)
    except Exception:
        logger.exception("Could not record who started %s %s", kind, reference)
        return False


def notify_user(user_id: str | None, *, title: str, body: str = "", key: str, link: str | None = None,
                kind: str = "decisions") -> bool:
    """Tell someone else about a decision on their work (never oneself). Never fails
    the action it follows."""
    account = current_account()
    if account is None or not user_id or user_id == account.user_id:
        return False
    try:
        from src.accounts.notifier import notify
        return notify(_store(), user_id, kind=kind, title=title, body=body, link=link, key=key)
    except Exception:
        logger.exception("Could not notify %s", user_id)
        return False


def notify_owner(entity_type: str, entity_id, *, title: str, body: str = "", key: str,
                 link: str | None = None) -> bool:
    """Tell a record's original owner that someone else acted on it."""
    if current_account() is None or not entity_id:
        return False
    try:
        owner = _store().owner_of(entity_type, str(entity_id))
    except Exception:
        logger.exception("Could not read the owner of %s %s", entity_type, entity_id)
        return False
    return notify_user(owner, title=title, body=body, key=key, link=link)


def owners(entity_type: str) -> dict[str, dict]:
    """entity id -> owner, when accounts are on; {} otherwise or on error."""
    if current_account() is None:
        return {}
    try:
        return _store().owners(entity_type)
    except Exception:
        logger.exception("Could not read the owners of %s records", entity_type)
        return {}


def with_owners(rows: list[dict], entity_type: str) -> list[dict]:
    """The rows with their original owner's name (or none: "Not recorded"). New
    dicts: the cached rows are never changed."""
    known = owners(entity_type)
    if not known:
        return rows
    out = []
    for row in rows:
        owner = known.get(str(row.get("id")))
        out.append({**row, "owner": owner["owner"], "owner_user_id": owner["owner_user_id"],
                    "owner_origin": owner["origin"]} if owner else row)
    return out


def subscription_id(answer) -> str | None:
    """The id of a request the discovery backend just created, wherever it put it."""
    if not isinstance(answer, dict):
        return None
    for source in (answer, answer.get("request") or {}, answer.get("subscription") or {}):
        if isinstance(source, dict):
            for key in ("subscription_id", "actor_update_subscription_id", "id"):
                value = source.get(key)
                if value and value != "preview":
                    return str(value)
    return None
