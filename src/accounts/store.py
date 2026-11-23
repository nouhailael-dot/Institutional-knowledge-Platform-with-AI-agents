"""Compass accounts in PostgreSQL (schema ``compass``, migration 700).

Profiles, roles and their permissions, the last sign-in, and the permanent
audit history. These are platform tables, not ecosystem records: nothing here
writes an organization, person, event or hub (those stay with the backend's
approved writers).

The database is ``GHUS_ACCOUNTS_DATABASE_URL`` when set (tests point it at an
isolated database), otherwise ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock

import psycopg

from src.db import psycopg_database_url


class AccountError(Exception):
    """An account change that is refused; ``message`` is safe to show, ``status`` is HTTP."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Account:
    user_id: str
    email: str
    full_name: str
    role_code: str | None
    role_label: str | None
    status: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    sessions_valid_after: float | None = None   # epoch seconds

    @property
    def active(self) -> bool:
        """May use Compass: an active account with a role."""
        return self.status == "active" and self.role_code is not None

    def can(self, permission: str) -> bool:
        return self.active and permission in self.permissions


class AccountsStore:
    CACHE_SECONDS = 30

    def __init__(self, conninfo: str | None = None, *, clock=time.monotonic):
        raw = conninfo or os.environ.get("GHUS_ACCOUNTS_DATABASE_URL") or os.environ.get("DATABASE_URL")
        self.conninfo = psycopg_database_url(raw)
        self._clock = clock
        self._cache: dict[str, tuple[float, Account | None]] = {}
        self._lock = Lock()
        self._idle: list[psycopg.Connection] = []
        self._pool_lock = Lock()

    MAX_IDLE = 4

    @contextmanager
    def connect(self):
        """A connection for one unit of work: committed on success, rolled back on error.

        Up to MAX_IDLE connections are kept open and reused (every action used to
        open a new one, slow through Supabase's pooler). A connection that is
        broken or not idle is closed, never handed out again.
        """
        conn = None
        with self._pool_lock:
            while self._idle and conn is None:
                candidate = self._idle.pop()
                if not candidate.closed and not candidate.broken:
                    conn = candidate
                else:
                    candidate.close()
        if conn is None:
            conn = psycopg.connect(self.conninfo, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except psycopg.Error:
                conn.close()
            raise
        finally:
            reusable = (not conn.closed and not conn.broken
                        and conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE)
            with self._pool_lock:
                if reusable and len(self._idle) < self.MAX_IDLE:
                    self._idle.append(conn)
                    conn = None
            if conn is not None and not conn.closed:
                conn.close()

    # -- profiles -------------------------------------------------------------
    def account(self, user_id: str) -> Account | None:
        """The account behind a Supabase Auth user id (cached for CACHE_SECONDS)."""
        now = self._clock()
        with self._lock:
            hit = self._cache.get(user_id)
            if hit and hit[0] > now:
                return hit[1]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.user_id::text, p.email, p.full_name, p.role_code, r.label, p.status,
                       COALESCE(array_agg(rp.permission_code) FILTER (WHERE rp.permission_code IS NOT NULL),
                                '{}'),
                       extract(epoch FROM p.sessions_valid_after)::float8
                  FROM compass.user_profile p
                  LEFT JOIN compass.role r ON r.code = p.role_code
                  LEFT JOIN compass.role_permission rp ON rp.role_code = p.role_code
                 WHERE p.user_id = %s::uuid
                 GROUP BY p.user_id, r.label
            """, (user_id,))
            row = cur.fetchone()
        found = None if row is None else Account(
            user_id=row[0], email=row[1], full_name=row[2], role_code=row[3], role_label=row[4],
            status=row[5], permissions=frozenset(row[6]), sessions_valid_after=row[7])
        with self._lock:
            self._cache[user_id] = (now + self.CACHE_SECONDS, found)
        return found

    def forget(self, user_id: str | None = None) -> None:
        """Drop cached accounts, so a role or status change applies at once."""
        with self._lock:
            if user_id is None:
                self._cache.clear()
            else:
                self._cache.pop(user_id, None)

    def end_sessions(self, user_id: str, *, before: float) -> None:
        """Refuse every session of this person that began before ``before`` (epoch)."""
        with self.connect() as conn:
            conn.execute("""UPDATE compass.user_profile
                              SET sessions_valid_after = GREATEST(COALESCE(sessions_valid_after, '-infinity'),
                                                                  to_timestamp(%s))
                            WHERE user_id = %s::uuid""", (before, user_id))
        self.forget(user_id)

    def mark_login(self, user_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE compass.user_profile SET last_login_at = now() WHERE user_id = %s::uuid",
                         (user_id,))

    # -- roles -------------------------------------------------------------------
    def roles(self) -> list[dict]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT r.code, r.label, r.description,
                       COALESCE(array_agg(rp.permission_code ORDER BY rp.permission_code)
                                FILTER (WHERE rp.permission_code IS NOT NULL), '{}')
                  FROM compass.role r LEFT JOIN compass.role_permission rp ON rp.role_code = r.code
                 GROUP BY r.code ORDER BY r.code
            """)
            return [{"code": c, "label": l, "description": d, "permissions": list(p)}
                    for c, l, d, p in cur.fetchall()]

    # -- users and invitations (Phase 2) --------------------------------------------
    _USERS_SQL = """
        SELECT p.user_id::text, p.email, p.full_name, p.role_code, r.label, p.status,
               p.created_at, p.last_login_at, p.deactivated_at,
               i.invitation_id::text, i.created_at, i.expires_at, i.accepted_at, i.revoked_at,
               inviter.full_name, i.role_code
          FROM compass.user_profile p
          LEFT JOIN compass.role r ON r.code = p.role_code
          LEFT JOIN LATERAL (SELECT * FROM compass.invitation i WHERE i.user_id = p.user_id
                              ORDER BY i.created_at DESC LIMIT 1) i ON true
          LEFT JOIN compass.user_profile inviter ON inviter.user_id = i.invited_by
    """

    @staticmethod
    def _user_row(row) -> dict:
        (user_id, email, name, role, label, status, created, last_login, deactivated,
         inv_id, inv_created, inv_expires, inv_accepted, inv_revoked, inviter, inv_role) = row
        invitation = None
        if inv_id:
            state = ("accepted" if inv_accepted else "revoked" if inv_revoked
                     else "expired" if inv_expires <= _utcnow() else "open")
            invitation = {"invitation_id": inv_id, "state": state, "created_at": inv_created,
                          "expires_at": inv_expires, "invited_by": inviter or "Compass setup",
                          "role": inv_role}
        shown = status
        if status == "invited" and invitation and invitation["state"] in ("expired", "revoked"):
            shown = f"invitation {invitation['state']}"
        return {"user_id": user_id, "email": email, "full_name": name, "role": role,
                "role_label": label, "status": status, "status_label": shown, "created_at": created,
                "last_login_at": last_login, "deactivated_at": deactivated, "invitation": invitation}

    def users(self) -> list[dict]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(self._USERS_SQL + " ORDER BY lower(p.full_name)")
            return [self._user_row(r) for r in cur.fetchall()]

    def user(self, user_id: str) -> dict | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(self._USERS_SQL + " WHERE p.user_id = %s::uuid", (user_id,))
            row = cur.fetchone()
        return self._user_row(row) if row else None

    def user_by_email(self, email: str) -> dict | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(self._USERS_SQL + " WHERE p.email = %s", (email.lower(),))
            row = cur.fetchone()
        return self._user_row(row) if row else None

    def check_can_invite(self, email: str) -> None:
        """Refuse before any email is sent: an existing account or an open invitation."""
        existing = self.user_by_email(email)
        if existing is None:
            return
        if existing["status"] == "active":
            raise AccountError("That person already has an active account.", 409)
        if existing["status"] == "deactivated":
            raise AccountError("That account is deactivated. Activate it instead of inviting again.", 409)
        state = (existing["invitation"] or {}).get("state")
        if state == "open":
            raise AccountError("An invitation for that address is still open. Revoke it or wait "
                               "for it to expire, then send a new one.", 409)
        raise AccountError("That address was invited before. Use Resend on its row instead.", 409)

    def record_invitation(self, *, user_id: str, email: str, full_name: str, role_code: str,
                          invited_by: str | None, days: float, bootstrap: bool = False) -> dict:
        """The profile (status invited, no role yet) and its open invitation, together."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (email,))
            cur.execute("SELECT 1 FROM compass.role WHERE code = %s", (role_code,))
            if cur.fetchone() is None:
                raise AccountError("Unknown role.", 400)
            cur.execute("""
                INSERT INTO compass.user_profile (user_id, email, full_name, role_code, status)
                VALUES (%s::uuid, %s, %s, NULL, 'invited')
            """, (user_id, email, full_name))
            cur.execute("""
                INSERT INTO compass.invitation (email, full_name, role_code, invited_by, bootstrap,
                                                user_id, expires_at)
                VALUES (%s, %s, %s, %s::uuid, %s, %s::uuid, now() + make_interval(secs => %s))
                RETURNING invitation_id::text, expires_at
            """, (email, full_name, role_code, invited_by, bootstrap, user_id, days * 86400))
            invitation_id, expires = cur.fetchone()
        return {"invitation_id": invitation_id, "expires_at": expires}

    def invitation(self, invitation_id: str) -> dict | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT invitation_id::text, email, full_name, role_code, user_id::text, expires_at,
                       accepted_at, revoked_at, expires_at <= now()
                  FROM compass.invitation WHERE invitation_id = %s::uuid
            """, (invitation_id,))
            row = cur.fetchone()
        if row is None:
            return None
        keys = ("invitation_id", "email", "full_name", "role_code", "user_id", "expires_at",
                "accepted_at", "revoked_at", "expired")
        return dict(zip(keys, row))

    def revoke_invitation(self, invitation_id: str, *, by: str) -> dict:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE compass.invitation SET revoked_at = now(), revoked_by = %s::uuid
                 WHERE invitation_id = %s::uuid AND accepted_at IS NULL AND revoked_at IS NULL
             RETURNING email, user_id::text
            """, (by, invitation_id))
            row = cur.fetchone()
        if row is None:
            raise AccountError("That invitation was already accepted or revoked.", 409)
        return {"email": row[0], "user_id": row[1]}

    def reissue_invitation(self, invitation_id: str, *, by: str, days: float) -> dict:
        """Close an expired or revoked invitation and open a new one for the same person."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT i.email, i.full_name, i.role_code, i.user_id::text, p.status
                  FROM compass.invitation i JOIN compass.user_profile p ON p.user_id = i.user_id
                 WHERE i.invitation_id = %s::uuid FOR UPDATE OF i
            """, (invitation_id,))
            row = cur.fetchone()
            if row is None:
                raise AccountError("Unknown invitation.", 404)
            email, name, role, user_id, status = row
            if status != "invited":
                raise AccountError("That person already accepted. Nothing to resend.", 409)
            cur.execute("""
                UPDATE compass.invitation SET revoked_at = now(), revoked_by = %s::uuid
                 WHERE user_id = %s::uuid AND accepted_at IS NULL AND revoked_at IS NULL
            """, (by, user_id))
            cur.execute("""
                INSERT INTO compass.invitation (email, full_name, role_code, invited_by, user_id, expires_at)
                VALUES (%s, %s, %s, %s::uuid, %s::uuid, now() + make_interval(secs => %s))
                RETURNING invitation_id::text, expires_at
            """, (email, name, role, by, user_id, days * 86400))
            new_id, expires = cur.fetchone()
        return {"invitation_id": new_id, "expires_at": expires, "email": email, "full_name": name,
                "user_id": user_id}

    @staticmethod
    def _open_invitation(cur, user_id: str, *, lock: bool):
        """(invitation_id, role) of the person's latest invitation; AccountError unless it is
        open, unrevoked and unexpired, and the profile still waits for it."""
        cur.execute("""
            SELECT i.invitation_id, i.role_code, i.expires_at <= now(), i.revoked_at IS NOT NULL,
                   i.accepted_at IS NOT NULL, p.status
              FROM compass.invitation i JOIN compass.user_profile p ON p.user_id = i.user_id
             WHERE i.user_id = %s::uuid ORDER BY i.created_at DESC LIMIT 1
        """ + (" FOR UPDATE OF i, p" if lock else ""), (user_id,))
        row = cur.fetchone()
        if row is None:
            raise AccountError("This invitation is not valid.", 403)
        invitation_id, role, expired, revoked, accepted, status = row
        if accepted or status != "invited":
            raise AccountError("This invitation was already used. Sign in instead.", 409)
        if revoked:
            raise AccountError("This invitation was withdrawn. Ask a Compass administrator.", 403)
        if expired:
            raise AccountError("This invitation has expired. Ask a Compass administrator to "
                               "send a new one.", 403)
        return invitation_id, role

    def check_invitation_open(self, user_id: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            self._open_invitation(cur, user_id, lock=False)

    def accept_invitation(self, user_id: str, *, full_name: str | None) -> Account:
        """Activate an invited account with its invitation's role; AccountError when the
        invitation is expired, revoked, already used or missing."""
        with self.connect() as conn, conn.cursor() as cur:
            invitation_id, role = self._open_invitation(cur, user_id, lock=True)
            cur.execute("UPDATE compass.invitation SET accepted_at = now() WHERE invitation_id = %s",
                        (invitation_id,))
            cur.execute("""
                UPDATE compass.user_profile
                   SET status = 'active', role_code = %s, updated_at = now(),
                       full_name = COALESCE(NULLIF(btrim(%s), ''), full_name)
                 WHERE user_id = %s::uuid
            """, (role, full_name, user_id))
        self.forget(user_id)
        return self.account(user_id)  # type: ignore[return-value]

    # -- role, activation -------------------------------------------------------------
    @staticmethod
    def _managers_left(cur, *, without: str) -> int:
        """Active accounts that can manage users, other than ``without`` (rows locked)."""
        cur.execute("""
            SELECT p.user_id FROM compass.user_profile p
             WHERE p.status = 'active' AND p.user_id <> %s::uuid
               AND EXISTS (SELECT 1 FROM compass.role_permission rp
                            WHERE rp.role_code = p.role_code AND rp.permission_code = 'users.manage')
               FOR UPDATE
        """, (without,))
        return len(cur.fetchall())

    def _locked_profile(self, cur, user_id: str):
        cur.execute("SELECT status, role_code, full_name FROM compass.user_profile "
                    "WHERE user_id = %s::uuid FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise AccountError("Unknown user.", 404)
        return row

    def _manages(self, cur, role_code: str | None) -> bool:
        cur.execute("SELECT 1 FROM compass.role_permission WHERE role_code = %s "
                    "AND permission_code = 'users.manage'", (role_code,))
        return cur.fetchone() is not None

    def set_role(self, user_id: str, role_code: str) -> tuple[str | None, str]:
        """(old role, new role). Refuses to remove the last user manager."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('compass.managers'))")
            status, old, _ = self._locked_profile(cur, user_id)
            cur.execute("SELECT 1 FROM compass.role WHERE code = %s", (role_code,))
            if cur.fetchone() is None:
                raise AccountError("Unknown role.", 400)
            if status == "invited":
                cur.execute("""UPDATE compass.invitation SET role_code = %s
                                WHERE user_id = %s::uuid AND accepted_at IS NULL AND revoked_at IS NULL""",
                            (role_code, user_id))
            elif (status == "active" and self._manages(cur, old) and not self._manages(cur, role_code)
                  and self._managers_left(cur, without=user_id) == 0):
                raise AccountError("Compass needs at least one active administrator. Give another "
                                   "person that role first.", 409)
            if status != "invited":
                cur.execute("UPDATE compass.user_profile SET role_code = %s, updated_at = now() "
                            "WHERE user_id = %s::uuid", (role_code, user_id))
        self.forget(user_id)
        return old, role_code

    def deactivate(self, user_id: str, *, by: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('compass.managers'))")
            status, role, _ = self._locked_profile(cur, user_id)
            if status == "deactivated":
                raise AccountError("That account is already deactivated.", 409)
            if status == "invited":
                raise AccountError("That person has not accepted yet. Revoke the invitation instead.", 409)
            if self._manages(cur, role) and self._managers_left(cur, without=user_id) == 0:
                raise AccountError("Compass needs at least one active administrator. Give another "
                                   "person that role first.", 409)
            cur.execute("""UPDATE compass.user_profile SET status = 'deactivated', deactivated_at = now(),
                                  deactivated_by = %s::uuid, updated_at = now(), sessions_valid_after = now()
                            WHERE user_id = %s::uuid""",
                        (by, user_id))
        self.forget(user_id)

    def activate(self, user_id: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            status, role, _ = self._locked_profile(cur, user_id)
            if status != "deactivated":
                raise AccountError("Only a deactivated account can be activated.", 409)
            if role is None:
                raise AccountError("Give the account a role first.", 409)
            cur.execute("""UPDATE compass.user_profile SET status = 'active', deactivated_at = NULL,
                                  deactivated_by = NULL, updated_at = now() WHERE user_id = %s::uuid""",
                        (user_id,))
        self.forget(user_id)

    def update_profile(self, user_id: str, *, full_name: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE compass.user_profile SET full_name = %s, updated_at = now() "
                         "WHERE user_id = %s::uuid", (full_name, user_id))
        self.forget(user_id)

    def active_manager_count(self) -> int:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) FROM compass.user_profile p
                 WHERE p.status = 'active' AND EXISTS (
                       SELECT 1 FROM compass.role_permission rp
                        WHERE rp.role_code = p.role_code AND rp.permission_code = 'users.manage')
            """)
            return int(cur.fetchone()[0])

    def open_bootstrap_invitations(self) -> int:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM compass.invitation WHERE bootstrap AND accepted_at IS NULL "
                        "AND revoked_at IS NULL AND expires_at > now()")
            return int(cur.fetchone()[0])

    # -- ownership (Phase 3) ------------------------------------------------------
    def claim_owner(self, *, entity_type: str, entity_id: str, owner_user_id: str, origin: str,
                    source_ref: str | None = None) -> bool:
        """Record the original owner. The first claim wins and never changes (the
        database refuses updates); a later claim on the same record returns False."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO compass.record_owner (entity_type, entity_id, owner_user_id, origin, source_ref)
                VALUES (%s, %s, %s::uuid, %s, %s)
                ON CONFLICT (entity_type, entity_id) DO NOTHING RETURNING 1
            """, (entity_type, str(entity_id), owner_user_id, origin, source_ref))
            return cur.fetchone() is not None

    def owner_of(self, entity_type: str, entity_id: str) -> str | None:
        """The owner's account id of one record, request, map or import, or None."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT owner_user_id::text FROM compass.record_owner "
                        "WHERE entity_type = %s AND entity_id = %s", (entity_type, str(entity_id)))
            row = cur.fetchone()
        return row[0] if row else None

    def owners(self, entity_type: str) -> dict[str, dict]:
        """entity id -> its original owner, for one record type. Records without a
        row have no known owner ("Not recorded")."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT o.entity_id, o.owner_user_id::text, p.full_name, o.origin, o.recorded_at
                  FROM compass.record_owner o JOIN compass.user_profile p ON p.user_id = o.owner_user_id
                 WHERE o.entity_type = %s
            """, (entity_type,))
            return {eid: {"owner_user_id": uid, "owner": name, "origin": origin, "owned_since": at}
                    for eid, uid, name, origin, at in cur.fetchall()}

    def owned_by(self, user_id: str, entity_type: str | None = None) -> list[dict]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT entity_type, entity_id, origin, source_ref, recorded_at
                  FROM compass.record_owner
                 WHERE owner_user_id = %s::uuid AND (%s::text IS NULL OR entity_type = %s)
                 ORDER BY recorded_at DESC
            """, (user_id, entity_type, entity_type))
            return [{"entity_type": t, "entity_id": i, "origin": o, "source_ref": s, "recorded_at": at}
                    for t, i, o, s, at in cur.fetchall()]

    def audit_entries(self, *, user_id: str | None = None, actions: tuple[str, ...] = (),
                      entity_type: str | None = None, entity_id: str | None = None,
                      limit: int = 200) -> list[dict]:
        """Audit history, newest first, filtered by person, action prefix and record."""
        clauses, params = [], []
        if user_id:
            clauses.append("a.user_id = %s::uuid"); params.append(user_id)
        if actions:
            clauses.append("(" + " OR ".join("a.action LIKE %s" for _ in actions) + ")")
            params.extend(f"{prefix}%" for prefix in actions)
        if entity_type:
            clauses.append("a.entity_type = %s"); params.append(entity_type)
        if entity_id:
            clauses.append("a.entity_id = %s"); params.append(entity_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.audit_id, a.occurred_at, a.user_id::text, a.user_label, a.action,
                       a.entity_type, a.entity_id, a.detail
                  FROM compass.audit_event a {where}
                 ORDER BY a.audit_id DESC LIMIT %s
            """, (*params, max(1, min(int(limit), 1000))))
            keys = ("audit_id", "occurred_at", "user_id", "user_label", "action", "entity_type",
                    "entity_id", "detail")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    # -- preferences (Phase 4) ----------------------------------------------------
    def preferences(self, user_id: str) -> dict:
        from src.accounts.preferences import complete
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT preferences FROM compass.user_profile WHERE user_id = %s::uuid", (user_id,))
            row = cur.fetchone()
        return complete(row[0] if row else {})

    def set_preferences(self, user_id: str, preferences: dict) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE compass.user_profile SET preferences = %s::jsonb, updated_at = now() "
                         "WHERE user_id = %s::uuid", (json.dumps(preferences), user_id))

    # -- notifications (Phase 4) ---------------------------------------------------
    def add_notification(self, *, user_id: str, kind: str, title: str, body: str = "",
                         link: str | None = None, dedupe_key: str, email_requested: bool = False) -> bool:
        """Create a notification once per (person, key); a repeat returns False."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO compass.notification (user_id, kind, title, body, link, dedupe_key, email_requested)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, dedupe_key) DO NOTHING RETURNING notification_id
            """, (user_id, kind, title[:200], body[:2000], link, dedupe_key[:200], email_requested))
            return cur.fetchone() is not None

    def notifications(self, user_id: str, *, limit: int = 50, unread_only: bool = False) -> dict:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT notification_id, created_at, kind, title, body, link, read_at
                  FROM compass.notification WHERE user_id = %s::uuid AND (NOT %s OR read_at IS NULL)
                 ORDER BY created_at DESC, notification_id DESC LIMIT %s
            """, (user_id, unread_only, max(1, min(limit, 200))))
            keys = ("id", "created_at", "kind", "title", "body", "link", "read_at")
            items = [dict(zip(keys, row)) for row in cur.fetchall()]
            cur.execute("SELECT count(*) FROM compass.notification WHERE user_id = %s::uuid AND read_at IS NULL",
                        (user_id,))
            unread = int(cur.fetchone()[0])
        return {"unread": unread, "items": items}

    def mark_read(self, user_id: str, notification_id: int | None = None) -> int:
        """Mark one (or every) notification of this person read. Someone else's: 0."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE compass.notification SET read_at = now()
                 WHERE user_id = %s::uuid AND read_at IS NULL AND (%s::bigint IS NULL OR notification_id = %s)
            """, (user_id, notification_id, notification_id))
            return cur.rowcount

    # -- what a person's work is doing (Phase 4; existing tables, read only) ------------
    def _has_tables(self, cur, *names: str) -> bool:
        cur.execute("SELECT bool_and(to_regclass(n) IS NOT NULL) FROM unnest(%s::text[]) n", (list(names),))
        return bool(cur.fetchone()[0])

    def request_runs(self, user_id: str, *, days: int = 14) -> list[dict]:
        """Runs of the requests this person owns: running, and finished in the last ``days``."""
        with self.connect() as conn, conn.cursor() as cur:
            if not self._has_tables(cur, "public.actor_update_subscription",
                                    "public.actor_update_subscription_run", "public.collection_run"):
                return []
            cur.execute("""
                SELECT s.actor_update_subscription_id::text, COALESCE(s.title, 'Untitled request'),
                       r.collection_run_id::text, r.status, r.started_at, r.finished_at,
                       r.status_reason, r.found_count, r.staged_count, r.review_item_count
                  FROM compass.record_owner o
                  JOIN public.actor_update_subscription s
                    ON s.actor_update_subscription_id::text = o.entity_id
                  JOIN public.actor_update_subscription_run sr
                    ON sr.actor_update_subscription_id = s.actor_update_subscription_id AND NOT sr.dry_run
                  JOIN public.collection_run r ON r.collection_run_id = sr.collection_run_id
                 WHERE o.entity_type = 'request' AND o.owner_user_id = %s::uuid
                   AND (r.finished_at IS NULL OR r.finished_at > now() - make_interval(days => %s))
                 ORDER BY COALESCE(r.finished_at, r.started_at) DESC NULLS LAST LIMIT 50
            """, (user_id, days))
            keys = ("request_id", "title", "run_id", "status", "started_at", "finished_at", "reason",
                    "found", "staged", "for_review")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def requests_due(self, user_id: str, *, hours: int = 24) -> list[dict]:
        """This person's active requests due to run within ``hours``."""
        with self.connect() as conn, conn.cursor() as cur:
            if not self._has_tables(cur, "public.actor_update_subscription"):
                return []
            cur.execute("""
                SELECT s.actor_update_subscription_id::text, COALESCE(s.title, 'Untitled request'), s.next_due_at
                  FROM compass.record_owner o
                  JOIN public.actor_update_subscription s ON s.actor_update_subscription_id::text = o.entity_id
                 WHERE o.entity_type = 'request' AND o.owner_user_id = %s::uuid AND s.status = 'active'
                   AND s.next_due_at BETWEEN now() AND now() + make_interval(hours => %s)
            """, (user_id, hours))
            return [{"request_id": i, "title": t, "next_due_at": d} for i, t, d in cur.fetchall()]

    def owned_imports(self, user_id: str | None = None, run_id: str | None = None) -> list[dict]:
        """Imports with an owner (imports from before accounts have none)."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT entity_id, owner_user_id::text, origin, source_ref FROM compass.record_owner
                 WHERE entity_type = 'import' AND (%s::uuid IS NULL OR owner_user_id = %s::uuid)
                   AND (%s::text IS NULL OR entity_id = %s)
            """, (user_id, user_id, run_id, run_id))
            return [{"run_id": r, "owner_user_id": o, "origin": g,
                     "record_type": (s or "").removeprefix("type:") or None} for r, o, g, s in cur.fetchall()]

    def record_trail(self, entity_type: str, entity_id: str) -> dict:
        """Original owner, who verified it, and who last edited it: three different people
        possibly, each from its own source (ownership, Review decisions, edits)."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.full_name, o.origin, o.recorded_at FROM compass.record_owner o
                  JOIN compass.user_profile p ON p.user_id = o.owner_user_id
                 WHERE o.entity_type = %s AND o.entity_id = %s
            """, (entity_type, entity_id))
            owner = cur.fetchone()
            cur.execute("""
                SELECT user_label, occurred_at, detail->>'decision' FROM compass.audit_event
                 WHERE action LIKE 'review.%%' AND detail->>'canonical_entity_id' = %s
                 ORDER BY audit_id DESC LIMIT 1
            """, (entity_id,))
            verified = cur.fetchone()
            cur.execute("""
                SELECT user_label, occurred_at FROM compass.audit_event
                 WHERE action = 'browse.edit' AND entity_type = %s AND entity_id = %s
                 ORDER BY audit_id DESC LIMIT 1
            """, (entity_type, entity_id))
            edited = cur.fetchone()
        return {"owner": {"name": owner[0], "origin": owner[1], "at": owner[2]} if owner else None,
                "reviewed_by": {"name": verified[0], "at": verified[1], "decision": verified[2]}
                if verified else None,
                "last_edited_by": {"name": edited[0], "at": edited[1]} if edited else None}

    # -- usage (Phase 5) -------------------------------------------------------------
    def record_usage(self, *, kind: str, reference: str, user_id: str | None, trigger: str = "manual",
                     cost_usd: float | None = None, cost_basis: str = "ledger",
                     input_tokens: int | None = None, output_tokens: int | None = None,
                     detail: dict | None = None) -> bool:
        """Who started one paid operation (once per operation: a repeat is ignored)."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO compass.usage_event (user_id, kind, reference, trigger, cost_usd, cost_basis,
                                                 input_tokens, output_tokens, detail)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (kind, reference) DO NOTHING RETURNING usage_id
            """, (user_id, kind, str(reference), trigger, cost_usd, cost_basis, input_tokens, output_tokens,
                  json.dumps(detail or {}, default=str)))
            return cur.fetchone() is not None

    def usage_events(self) -> list[dict]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT u.kind, u.reference, u.user_id::text, p.full_name, u.trigger, u.occurred_at,
                       u.cost_usd::float8, u.cost_basis, u.input_tokens, u.output_tokens, u.detail
                  FROM compass.usage_event u LEFT JOIN compass.user_profile p ON p.user_id = u.user_id
                 ORDER BY u.occurred_at
            """)
            keys = ("kind", "reference", "user_id", "user_name", "trigger", "occurred_at", "cost_usd",
                    "cost_basis", "input_tokens", "output_tokens", "detail")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def run_ledger(self) -> list[dict]:
        """Every Discovery, Update and organization-check run with its recorded cost
        (collection_run), and the request it belongs to. Read only."""
        with self.connect() as conn, conn.cursor() as cur:
            if not self._has_tables(cur, "public.collection_run"):
                return []
            linked = self._has_tables(cur, "public.actor_update_subscription_run")
            cur.execute(f"""
                SELECT r.collection_run_id::text, r.job_name, r.trigger_type, r.status, r.started_at,
                       r.finished_at, COALESCE(r.spent_usd, 0)::float8, r.config_snapshot->>'check_id',
                       {"sr.actor_update_subscription_id::text" if linked else "NULL"}
                  FROM public.collection_run r
                  {"LEFT JOIN public.actor_update_subscription_run sr ON sr.collection_run_id = r.collection_run_id"
                   if linked else ""}
                 WHERE NOT COALESCE(r.dry_run, false)
            """)
            keys = ("run_id", "job_name", "trigger_type", "status", "started_at", "finished_at",
                    "spent_usd", "check_id", "subscription_id")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def datafeed_ledger(self) -> list[dict]:
        """Data Feed runs with their recorded AI cost (scrape_run). Read only."""
        with self.connect() as conn, conn.cursor() as cur:
            if not self._has_tables(cur, "public.scrape_run"):
                return []
            cur.execute("""
                SELECT run_id::text, status, started_at, finished_at, COALESCE(cost_usd, 0)::float8
                  FROM public.scrape_run WHERE source_name = 'ghus_data_feed'
            """)
            keys = ("run_id", "status", "started_at", "finished_at", "cost_usd")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    def monthly_counts(self, user_id: str | None = None) -> dict[str, dict[str, int]]:
        """Per month (UTC): records brought in, maps started, imports and Review decisions,
        for one person or everyone."""
        out: dict[str, dict[str, int]] = {}
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT to_char(recorded_at AT TIME ZONE 'UTC', 'YYYY-MM'),
                       count(*) FILTER (WHERE entity_type IN ('actor', 'person', 'event')),
                       count(*) FILTER (WHERE entity_type = 'map'),
                       count(*) FILTER (WHERE entity_type = 'import'),
                       count(*) FILTER (WHERE entity_type = 'request')
                  FROM compass.record_owner WHERE (%s::uuid IS NULL OR owner_user_id = %s::uuid)
                 GROUP BY 1
            """, (user_id, user_id))
            for month, records, maps, imports, requests in cur.fetchall():
                out.setdefault(month, {}).update(records_created=records, maps_created=maps,
                                                 imports=imports, requests_created=requests)
            cur.execute("""
                SELECT to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM'), count(*)
                  FROM compass.audit_event
                 WHERE action LIKE 'review.%%' AND (%s::uuid IS NULL OR user_id = %s::uuid)
                 GROUP BY 1
            """, (user_id, user_id))
            for month, decisions in cur.fetchall():
                out.setdefault(month, {})["review_decisions"] = decisions
        keys = ("records_created", "maps_created", "imports", "requests_created", "review_decisions")
        return {m: {k: v.get(k, 0) for k in keys} for m, v in sorted(out.items())}

    def owners_of_type(self, entity_type: str) -> dict[str, tuple[str, str]]:
        """entity id -> (owner id, owner name) for one type (requests, maps, imports)."""
        return {eid: (o["owner_user_id"], o["owner"]) for eid, o in self.owners(entity_type).items()}

    def people(self) -> dict[str, str]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id::text, full_name FROM compass.user_profile")
            return dict(cur.fetchall())

    # -- deleted records (Phase 6, migration 710) ------------------------------------
    HIDDEN_CACHE_SECONDS = 20

    def hidden_ids(self, entity_type: str) -> set[str]:
        """Records awaiting permanent deletion: hidden from every active view. Empty when
        migration 710 is not applied."""
        now = self._clock()
        key = f"hidden:{entity_type}"
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]  # type: ignore[return-value]
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT to_regclass('compass.deleted_record') IS NOT NULL")
                found = set()
                if cur.fetchone()[0]:
                    cur.execute("SELECT entity_id::text FROM compass.deleted_record WHERE entity_type = %s "
                                "AND restored_at IS NULL AND purged_at IS NULL", (entity_type,))
                    found = {r[0] for r in cur.fetchall()}
        except psycopg.Error:
            found = set()
        with self._lock:
            self._cache[key] = (now + self.HIDDEN_CACHE_SECONDS, found)  # type: ignore[assignment]
        return found

    def forget_hidden(self) -> None:
        with self._lock:
            for key in [k for k in self._cache if k.startswith("hidden:")]:
                del self._cache[key]

    def deletions(self, *, pending_only: bool = True) -> list[dict]:
        """Deleted records for Pending Deletion, newest first."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('compass.deleted_record') IS NOT NULL")
            if not cur.fetchone()[0]:
                return []
            cur.execute(f"""
                SELECT d.deletion_id::text, d.entity_type, d.entity_id::text, d.name, d.snapshot, d.reason,
                       d.deleted_at, d.purge_after, d.restored_at, d.purged_at, p.full_name, r.full_name,
                       GREATEST(0, ceil(extract(epoch FROM d.purge_after - now()) / 86400))::int,
                       o.full_name
                  FROM compass.deleted_record d
                  JOIN compass.user_profile p ON p.user_id = d.deleted_by
                  LEFT JOIN compass.user_profile r ON r.user_id = d.restored_by
                  LEFT JOIN compass.record_owner ro ON ro.entity_type = d.entity_type
                                                   AND ro.entity_id = d.entity_id::text
                  LEFT JOIN compass.user_profile o ON o.user_id = ro.owner_user_id
                 {"WHERE d.restored_at IS NULL AND d.purged_at IS NULL" if pending_only else ""}
                 ORDER BY d.deleted_at DESC LIMIT 500
            """)
            keys = ("deletion_id", "entity_type", "entity_id", "name", "snapshot", "reason", "deleted_at",
                    "purge_after", "restored_at", "purged_at", "deleted_by", "restored_by", "days_remaining",
                    "owner")
            return [dict(zip(keys, row)) for row in cur.fetchall()]

    # -- audit ----------------------------------------------------------------
    def audit(self, *, action: str, account: Account | None, label: str | None = None,
              entity_type: str | None = None, entity_id: str | None = None,
              detail: dict | None = None, client: str | None = None) -> None:
        """Append one entry to the permanent audit history."""
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO compass.audit_event (user_id, user_label, action, entity_type, entity_id,
                                                 detail, client_addr)
                VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s)
            """, (account.user_id if account else None,
                  label or (account.full_name if account else "Not recorded"),
                  action, entity_type, entity_id, json.dumps(detail or {}, default=str), client))
