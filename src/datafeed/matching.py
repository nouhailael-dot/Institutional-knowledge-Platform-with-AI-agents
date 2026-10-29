"""Find what a Data Feed record may already be, on the map. Read-only.

    existing  - the same record: same website domain, or the same name (or one
                of its other names) - Review is offered "Same as existing"
    possible  - a close name (and, for events, a close date): Review decides
    new       - nothing close

A match only suggests; Review decides identity, and the backend's admission
routes every record through entity resolution again. Parent organisations are
resolved here to an actor already on the map, or the row says why not.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from rapidfuzz import fuzz

POSSIBLE_SCORE = 90
EVENT_DAYS = 7
_LEGAL = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|the|of|and)\b")


def norm(value: Any) -> str:
    text_ = unicodedata.normalize("NFKD", " ".join(str(value or "").split()).casefold())
    text_ = "".join(ch for ch in text_ if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text_).strip()


def core_name(value: Any) -> str:
    return " ".join(_LEGAL.sub(" ", norm(value)).split())


def domain(url: Any) -> str:
    raw = str(url or "").strip().casefold()
    if not raw:
        return ""
    host = urlsplit(raw if "://" in raw else f"https://{raw}").hostname or ""
    host = host.removeprefix("www.")
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in {"co.uk", "ac.uk", "com.au", "co.ma",
                                                      "ac.ma", "org.uk", "edu.au"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def identity_keys(record_type: str, payload: dict[str, Any]) -> list[str]:
    """The keys two rows of one file share when they are the same record."""
    if record_type == "actor":
        keys = []
        if domain(payload.get("website")):
            keys.append(f"website|{domain(payload.get('website'))}")
        keys.append(f"name|{core_name(payload.get('name'))}|{payload.get('state_code') or ''}")
        return keys
    if record_type == "event":
        return [f"event|{core_name(payload.get('name'))}|{payload.get('start_date') or ''}"]
    return [f"person|{norm(payload.get('name'))}|{core_name(payload.get('affiliation'))}"]


def _first_token(name: str) -> str:
    words = [w for w in core_name(name).split() if len(w) > 2]
    return words[0] if words else core_name(name)


class Matcher:
    """One read-only connection; ``conn.execute(sql, params).fetchall()``."""

    def __init__(self, conn):
        self.conn = conn
        # V2 final name, or its pre-cutover name on an older copy.
        columns = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'actor'").fetchall()}
        self.alt = "alt_names" if "alt_names" in columns else "alternate_names"

    def _rows(self, sql: str, params: tuple) -> list[tuple]:
        return list(self.conn.execute(sql, params).fetchall())

    # ---------------------------------------------------------------- actors
    def actor(self, payload: dict[str, Any]) -> dict[str, Any]:
        site = domain(payload.get("website"))
        if site:
            rows = self._rows(
                "SELECT actor_id::text, name, status FROM actor WHERE merged_into_actor_id IS NULL "
                "AND (lower(website_domain) = %s OR lower(website) LIKE %s OR lower(website) "
                "LIKE %s) ORDER BY name LIMIT 3", (site, f"%//{site}%", f"%.{site}%"))
            if rows:
                return self._found("existing", rows[0], 1.0, f"same website ({site})", rows)
        names = [payload.get("name"), *(payload.get("alternate_names") or [])]
        wanted = {core_name(n) for n in names if core_name(n)}
        token = _first_token(payload.get("name"))
        candidates = self._rows(
            f"SELECT actor_id::text, name, status, COALESCE({self.alt}, ARRAY[]::text[]), "
            f"state_code FROM actor WHERE merged_into_actor_id IS NULL AND (name ILIKE %s OR "
            f"EXISTS (SELECT 1 FROM unnest(COALESCE({self.alt}, ARRAY[]::text[])) a "
            f"WHERE a ILIKE %s)) LIMIT 200", (f"%{token}%", f"%{token}%")) if token else []
        exact = [r for r in candidates
                 if wanted & {core_name(r[1]), *(core_name(a) for a in r[3])}]
        if exact:
            return self._found("existing", exact[0], 0.97, "same name", exact)
        own = core_name(payload.get("name"))
        scored = sorted(((max([fuzz.token_sort_ratio(own, core_name(r[1])),
                               *(fuzz.token_sort_ratio(own, core_name(a)) for a in r[3])]), r)
                         for r in candidates), key=lambda item: item[0], reverse=True)
        close = [r for score, r in scored if score >= POSSIBLE_SCORE]
        if close:
            return self._found("possible", close[0], round(scored[0][0] / 100, 3),
                               "similar name", close)
        return {"kind": "new"}

    def parent(self, name_or_site: str) -> dict[str, Any]:
        """The actor a 'Parent organization' cell names, or why it cannot be linked."""
        raw = " ".join(str(name_or_site or "").split())
        if not raw:
            return {}
        site = domain(raw) if ("." in raw and " " not in raw) else ""
        if site:
            rows = self._rows("SELECT actor_id::text, name FROM actor WHERE merged_into_actor_id "
                              "IS NULL AND (lower(website_domain) = %s OR lower(website) LIKE %s "
                              "OR lower(website) LIKE %s) LIMIT 3",
                              (site, f"%//{site}%", f"%.{site}%"))
        else:
            rows = self._rows(
                f"SELECT actor_id::text, name FROM actor WHERE merged_into_actor_id IS NULL AND "
                f"(lower(name) = lower(%s) OR EXISTS (SELECT 1 FROM unnest(COALESCE({self.alt}, "
                f"ARRAY[]::text[])) a WHERE lower(a) = lower(%s))) LIMIT 3", (raw, raw))
        if len(rows) == 1:
            return {"actor_id": rows[0][0], "name": rows[0][1]}
        if len(rows) > 1:
            return {"error": f"Parent organization '{raw}' matches several records in the directory; "
                             "give its website instead."}
        return {"error": f"Parent organization '{raw}' is not in the directory yet. Add it first "
                         "(or in this file, then link it in Review), or leave it empty."}

    # ---------------------------------------------------------------- events
    def event(self, payload: dict[str, Any]) -> dict[str, Any]:
        name, start = core_name(payload.get("name")), payload.get("start_date")
        token = _first_token(payload.get("name"))
        if not token:
            return {"kind": "new"}
        rows = self._rows(
            "SELECT event_id::text, name, COALESCE(start_date, next_date)::text FROM event "
            "WHERE name ILIKE %s LIMIT 200", (f"%{token}%",))
        best: tuple[float, tuple] | None = None
        for row in rows:
            same_day = bool(start and row[2] and row[2][:10] == start)
            if core_name(row[1]) == name and same_day:
                return self._found("existing", row, 1.0, "same name and start date", [row])
            score = fuzz.token_sort_ratio(name, core_name(row[1]))
            near = (start and row[2] and abs((date.fromisoformat(row[2][:10])
                                              - date.fromisoformat(start)).days) <= EVENT_DAYS)
            if score >= POSSIBLE_SCORE and (near or not row[2] or not start) and \
                    (best is None or score > best[0]):
                best = (score, row)
        if best:
            return self._found("possible", best[1], round(best[0] / 100, 3),
                               "similar name, close date", [best[1]])
        return {"kind": "new"}

    # ---------------------------------------------------------------- people
    def person(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = norm(payload.get("name"))
        if not name:
            return {"kind": "new"}
        rows = self._rows(
            "SELECT p.person_id::text, p.full_name, COALESCE(string_agg(a.name, '; '), '') "
            "FROM person p LEFT JOIN actor_person ap ON ap.person_id = p.person_id "
            "LEFT JOIN actor a ON a.actor_id = ap.actor_id "
            "WHERE lower(p.full_name) = lower(%s) GROUP BY 1, 2 LIMIT 5",
            (" ".join(str(payload.get("name") or "").split()),))
        affiliation = core_name(payload.get("affiliation"))
        for row in rows:
            if affiliation and affiliation in {core_name(a) for a in row[2].split("; ")}:
                return self._found("existing", row, 1.0, "same name and organization", rows)
        if rows:
            return self._found("possible", rows[0], 0.9, "same name, organization not confirmed",
                               rows)
        return {"kind": "new"}

    @staticmethod
    def _found(kind, row, score, why, rows) -> dict[str, Any]:
        return {"kind": kind, "entity_id": row[0], "name": row[1], "score": score,
                "reason": why, "others": [{"entity_id": r[0], "name": r[1]} for r in rows[1:3]]}
