"""Facts in parts: one box's value as the individual facts it states.

A Light Pull box used to hold whatever paragraph the model wrote: "CPower is an
NRG company; serves ~2,000 customers across the U.S." went into one box, and an
update compared the whole paragraph with the next one. A box now holds its
facts as named parts - ownership, parent organisation, employees, customers -
each one checked against the page's own words, and two readings are compared
part by part:

    before {"employees": 500, "places": ["Texas"]}
    after  {"employees": 600, "places": ["Texas"]}
    ->     employees changed (500 -> 600), places confirmed

The parts live inside the box's existing fact value (Phase 11's immutable
``actor_fact.fact_value``): no new table, no new column, the same writer. A
box with no parts declared here keeps a plain value, and values recorded
before parts existed are compared as text. Nothing here reads or writes the
database.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

TEXT, NUMBER, LIST = "text", "number", "list"

# The facts each box holds. A part is filled only from the page; the rest stay empty.
FACT_PARTS: dict[str, dict[str, str]] = {
    # ---- common
    "funding_signal": {"amount": TEXT, "funder": TEXT, "funding_type": TEXT, "program": TEXT,
                       "date": TEXT},
    "international_connection": {"partner": TEXT, "country": TEXT, "connection_type": TEXT},
    # ---- company
    "ownership_and_size": {"ownership": TEXT, "parent_organization": TEXT, "employees": NUMBER,
                           "customers": NUMBER, "sites": NUMBER, "revenue": TEXT},
    "mapped_geography_operations": {"places": LIST, "scope": TEXT},
    # ---- startup
    "founding_year_location": {"founded_year": NUMBER, "founded_in": TEXT},
    "funding_stage": {"stage": TEXT, "amount": TEXT, "date": TEXT, "investors": LIST},
    "pilot_customer_evidence": {"customer": TEXT, "project": TEXT, "date": TEXT},
    # ---- research centre, laboratory, facility, hospital
    "parent_and_center_type": {"parent_organization": TEXT, "center_type": TEXT},
    "active_recent_projects": {"projects": LIST},
    "main_funders": {"funders": LIST},
    "sponsoring_agency": {"agency": TEXT},
    "facility_type_operator": {"facility_type": TEXT, "operator": TEXT},
    "current_project": {"name": TEXT, "description": TEXT},
    "hospital_type_scale": {"hospital_type": TEXT, "beds": NUMBER, "sites": NUMBER,
                            "patients": TEXT},
    "current_initiative": {"name": TEXT, "description": TEXT},
    # ---- university
    "relevant_centers_programs": {"names": LIST},
    # ---- innovation platform, investor
    "platform_type_operator": {"platform_type": TEXT, "operator": TEXT},
    "sector_focus": {"sectors": LIST},
    "platform_offerings": {"offerings": LIST},
    "scale_indicator": {"figure": TEXT, "measure": TEXT},
    "investor_type_headquarters": {"investor_type": TEXT, "headquarters": TEXT},
    "sector_stage_focus": {"sectors": LIST, "stages": LIST},
    "geographic_focus": {"places": LIST, "scope": TEXT},
    "published_fund_size": {"amount": TEXT, "fund": TEXT, "date": TEXT},
    # ---- government, foundation, association
    "jurisdiction_parent_agency": {"jurisdiction": TEXT, "parent_agency": TEXT},
    "visible_funding_programs": {"programs": LIST},
    "relevant_program": {"name": TEXT, "description": TEXT},
    "programs_grant_themes": {"themes": LIST},
    "sector_geographic_scope": {"sectors": LIST, "places": LIST},
    "member_types": {"member_types": LIST},
    "current_initiative_working_group": {"name": TEXT, "description": TEXT},
    "linked_members": {"members": LIST},
    "network_scope_locations": {"places": LIST},
}

# A box's fact needs at least one of these parts; the rest only qualify it.
# Seen on 2026-10-21: "graduates get job offers ... Mongolia, Peru, Australia"
# was read as an international connection with a country and no partner -
# where graduates work is not a connection the organisation has.
NEEDS_ONE_OF: dict[str, tuple[str, ...]] = {
    "international_connection": ("partner",),
    "funding_signal": ("amount", "funder", "program"),
    "funding_stage": ("stage", "amount"),
    "pilot_customer_evidence": ("customer", "project"),
    "published_fund_size": ("amount",),
    "scale_indicator": ("figure",),
}


def missing_core(key: str, value) -> tuple[str, ...]:
    """The core parts a box's value lacks entirely (empty when it is complete enough)."""
    needed = NEEDS_ONE_OF.get(key)
    if not needed or not isinstance(value, Mapping):
        return ()
    return () if any(value.get(part) not in (None, "", [], {}) for part in needed) else needed


# Boxes whose parts are independent facts about the organisation: a reading
# that does not restate one (it gives the headcount, not the ownership) leaves
# the recorded one standing. In every other box the parts describe ONE thing
# (one project, one grant), and a different thing replaces them together.
PROFILE_BOXES = frozenset({
    "ownership_and_size", "founding_year_location", "parent_and_center_type",
    "facility_type_operator", "hospital_type_scale", "platform_type_operator",
    "investor_type_headquarters", "jurisdiction_parent_agency",
})
# Boxes the agent writes in its own sentences (an explanation or a short
# description), not a figure or a name. The model words them differently on
# every read (2026-10-22: "UA's mining engineering degree program ..." twice,
# 53% of the same words), which is not new information. They are the same
# when they share half their words and no figure differs.
DESCRIPTIVE = frozenset({
    "topic_unit_and_work", "topic_research_focus", "topic_program_area",
    "testing_demonstration_scope", "clinical_research_focus", "topic_business_segment_product",
    "technology_and_problem", "topic_investment_thesis", "topic_mandate_program",
    "mission_sector_focus", "association_type", "description",
})

# Kept inside a stored value to say which parts an earlier reading supplied.
CARRIED_OVER = "carried_over"

# Boxes that record dated events, not one state (GHUS decision, 4 Nov 2026): a
# new grant, activity or project is ADDED beside the recorded ones instead of
# replacing them. Stored as {"entries": [...]}, newest first; an entry older than
# ENTRY_YEARS leaves the current value (it stays in the fact history).
ENTRY_BOXES = frozenset({
    "funding_signal", "recent_activity", "current_project", "current_initiative",
    "relevant_program", "pilot_customer_evidence", "current_initiative_working_group",
    "international_connection",
})
ENTRIES = "entries"
STATUS = "status"
MAX_ENTRIES = 10
MAX_ENTRIES_PER_READ = 5
ENTRY_YEARS = 2

_STOP = frozenset({"the", "and", "for", "with", "its", "from", "this", "that", "are", "has",
                   "was", "our", "inc", "llc", "ltd", "corp"})


def part_schema(key: str) -> dict | None:
    """The JSON schema the reader asks for, or None for a plain value."""
    parts = FACT_PARTS.get(key)
    if not parts:
        return None
    properties = {}
    for name, kind in parts.items():
        if kind == NUMBER:
            properties[name] = {"type": ["integer", "null"]}
        elif kind == LIST:
            properties[name] = {"type": "array", "items": {"type": "string"}}
        else:
            properties[name] = {"type": ["string", "null"]}
    return {"type": "object", "additionalProperties": False, "properties": properties}


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"\s*~?\s*(\d[\d,]*)\s*\+?\s*", str(value or ""))
    return int(match.group(1).replace(",", "")) if match else None


def clean_parts(key: str, value) -> dict:
    """Only the declared parts that say something, in their declared kind."""
    parts = FACT_PARTS.get(key) or {}
    out: dict = {}
    if not isinstance(value, Mapping):
        return out
    for name, kind in parts.items():
        item = value.get(name)
        if kind == NUMBER:
            number = _as_int(item)
            if number is not None:
                out[name] = number
        elif kind == LIST:
            items = item if isinstance(item, (list, tuple)) else ([item] if item else [])
            seen, kept = set(), []
            for entry in items:
                text = " ".join(str(entry or "").split())
                if text and text.casefold() not in seen:
                    seen.add(text.casefold())
                    kept.append(text)
            if kept:
                out[name] = kept
        else:
            text = " ".join(str(item or "").split())
            if text:
                out[name] = text
    return out


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*", str(text))}


def _words(text: str) -> set[str]:
    # Figures are compared by _numbers ("2,000" is one number, not "2" and "000").
    return {w for w in re.findall(r"[a-z0-9&]+", str(text).casefold())
            if len(w) > 2 and w not in _STOP and not w.isdigit()}


def part_supported(item, quotes_text: str) -> bool:
    """A part is backed by the quotes: its numbers are there, and most of its words."""
    text = str(item)
    numbers = _numbers(text)
    if numbers and not numbers <= _numbers(quotes_text):
        return False
    words = _words(text)
    if not words:
        return bool(numbers)
    return len(words & _words(quotes_text)) / len(words) >= 0.6


def supported_parts(key: str, value, quotes_text: str) -> tuple[dict, list[str]]:
    """The parts the quotes back, and what was dropped because they do not."""
    kept, dropped = {}, []
    for name, item in clean_parts(key, value).items():
        if isinstance(item, list):
            items = [entry for entry in item if part_supported(entry, quotes_text)]
            dropped += [f"{name}: {entry}" for entry in item if entry not in items]
            if items:
                kept[name] = items
        elif part_supported(item, quotes_text):
            kept[name] = item
        else:
            dropped.append(f"{name}: {item}")
    return kept, dropped


# ------------------------------------------------------------------ comparison

def _decode(value):
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        return decoded if isinstance(decoded, (dict, list)) else value
    return value


def _text(value) -> str:
    if isinstance(value, Mapping):
        # STATUS is computed from the entry's own dates, never read: not compared.
        return " ".join(_text(v) for k, v in value.items()
                        if k not in (CARRIED_OVER, STATUS, "reported"))
    if isinstance(value, (list, tuple)):
        return " ".join(_text(v) for v in value)
    return "" if value is None else str(value)


def same_text(before, after) -> bool:
    """The same fact in other words: the same numbers, most of the shorter wording."""
    numbers_a, numbers_b = _numbers(_text(before)), _numbers(_text(after))
    if numbers_a != numbers_b:
        return False
    words_a, words_b = _words(_text(before)), _words(_text(after))
    if not words_a or not words_b:
        return bool(numbers_a) or (not words_a and not words_b)
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.7


def covers(richer, poorer, *, share: float = 0.7) -> bool:
    """Everything ``poorer`` says is in ``richer``: its numbers, and nearly all its words."""
    numbers_r, numbers_p = _numbers(_text(richer)), _numbers(_text(poorer))
    words_r, words_p = _words(_text(richer)), _words(_text(poorer))
    if not numbers_p <= numbers_r or not (words_p or numbers_p):
        return False
    return not words_p or len(words_r & words_p) / len(words_p) >= share


def _same_part(before, after) -> bool:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return before == after
    return same_text(before, after)


def entries_of(value) -> list:
    """An entry box's entries, whatever shape was stored: a list, one item, or none."""
    value = _decode(value)
    if value in (None, "", [], {}):
        return []
    if isinstance(value, Mapping) and isinstance(value.get(ENTRIES), list):
        return [e for e in value[ENTRIES] if e not in (None, "", [], {})]
    if isinstance(value, list):
        return [e for e in value if e not in (None, "", [], {})]
    return [value]


def _entry_year(entry) -> int | None:
    text = " ".join(str(entry.get(part) or "") for part in ("date", "end_year", "year")) \
        if isinstance(entry, Mapping) else ""
    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)]
    return max(years) if years else None


# Funding (GHUS, 6 Nov 2026): documented funding is never "not found" because it
# is old. Each grant keeps its amount, funder, purpose and dates, and is labelled
# from its own dates: active, recently awarded, recently completed or historical.
RECENT_FUNDING_YEARS = 3
FUNDING_STATUS_ORDER = ("active", "recent_award", "recently_completed", "historical", "undated")
FUNDING_STATUS_LABELS = {
    "active": "Active", "recent_award": "Awarded recently (end not stated)",
    "recently_completed": "Recently completed", "historical": "Historical",
    "undated": "Date not stated",
}
_ONGOING = re.compile(r"\b(ongoing|present|current(ly)?|to date)\b", re.I)
_YEAR4 = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
REPORTED = "reported"     # the announcing page's own date, when the grant states none


def _years_in(text: str) -> list[int]:
    """Four-digit years, and fiscal years written "FY25" / "FY 2025"."""
    years = {int(y) for y in _YEAR4.findall(text)}
    years |= {2000 + int(y) for y in re.findall(r"\bFY\s?'?(\d{2})\b", text, re.I)}
    return sorted(years)


_RANGE = re.compile(r"\b(through|until|thru|to|ends?|ending)\b|\d\s*[-\u2013\u2014]\s*\d", re.I)


def funding_status(entry, *, today_year: int | None = None) -> str:
    """A funding entry's status from the dates it states (never guessed).

    A range ("2022-2026", "through 2027") is active while its end year has not
    passed, recently completed for RECENT_FUNDING_YEARS after, then historical.
    A single year is an award: active in its own year, "awarded recently (end not
    stated)" for RECENT_FUNDING_YEARS, then historical. "Ongoing" is active.
    """
    from datetime import date

    year = today_year or date.today().year
    text = str(entry.get("date") or "") if isinstance(entry, Mapping) else ""
    years = _years_in(text)
    if not years and not _ONGOING.search(text) and isinstance(entry, Mapping):
        # No date of its own: the date of the page that announced it, when its
        # address carries one (".../2026/07/30/doe-awards-..."), read as the award year.
        text = str(entry.get(REPORTED) or "")
        years = _years_in(text)
    if not years:
        return "active" if _ONGOING.search(text) else "undated"
    ranged = len(years) > 1 or bool(_RANGE.search(text))
    last = years[-1]
    if _ONGOING.search(text) or last >= year:
        return "active"
    if year - last <= RECENT_FUNDING_YEARS:
        return "recently_completed" if ranged else "recent_award"
    return "historical"


def _funding_value(entries, year: int) -> dict:
    labelled = []
    for entry in entries:
        if isinstance(entry, Mapping):
            entry = {**{k: v for k, v in entry.items() if k != STATUS},
                     STATUS: funding_status(entry, today_year=year)}
        labelled.append(entry)

    def rank(entry):
        status = entry.get(STATUS) if isinstance(entry, Mapping) else "undated"
        return (FUNDING_STATUS_ORDER.index(status), -(_entry_year(entry) or 0))

    return {ENTRIES: sorted(labelled, key=rank)[:MAX_ENTRIES]}


def entry_value(entries, *, today_year: int | None = None, key: str | None = None) -> dict:
    """The stored value of an entry box: newest first, at most MAX_ENTRIES, none stale.

    Funding keeps every documented grant, old ones included, each with its status.
    """
    from datetime import date

    year = today_year or date.today().year
    if key == "funding_signal":
        return _funding_value(entries, year)
    ordered = sorted(entries, key=lambda e: _entry_year(e) or year, reverse=True)
    kept = [e for e in ordered if (_entry_year(e) or year) >= year - ENTRY_YEARS]
    # Never an empty box from a found value: when every entry is old, the newest stays.
    return {ENTRIES: (kept or ordered[:1])[:MAX_ENTRIES]}


def same_entry(before, after) -> bool:
    """Two readings of one event: the same figures and most of the same words."""
    return same_text(before, after) or covers(before, after) or covers(after, before)


def compare_entries(before, after, key: str | None = None) -> dict:
    """An entry box: each new entry is confirmed (already recorded) or added.

    Never "changed": a different grant or activity is another one, recorded
    beside the others. The merged value keeps every recorded entry.
    """
    old, new = entries_of(before), entries_of(after)
    added = [e for e in new if not any(same_entry(o, e) for o in old)]
    added = [e for i, e in enumerate(added) if not any(same_entry(p, e) for p in added[:i])]
    if not added:
        return {"outcome": "corroborated", "parts": [], "merged": entry_value(old, key=key)}
    return {"outcome": "additional",
            "parts": [{"part": ENTRIES, "previous": len(old), "new": added,
                       "outcome": "additional"}],
            "merged": entry_value([*added, *old], key=key)}


def compare_values(key: str, before, after) -> dict:
    """Compare a recorded value with a new reading, fact by fact.

    Returns ``outcome`` - corroborated (nothing new), additional (the same
    facts and more) or changed (a fact is different) - with ``parts``, each
    confirmed, changed, additional or not_restated, and ``merged``: the value
    to write. A reading never makes a recorded value poorer: in a profile box
    and in a list, what it does not restate is kept.
    """
    before, after = _decode(before), _decode(after)
    if key in ENTRY_BOXES:
        return compare_entries(before, after, key)
    if key == "why_matched" and isinstance(before, Mapping) and isinstance(after, Mapping):
        # The agent's own explanation: a new wording of it is not new
        # information. Only a different strength of match is a change.
        if before.get("strength") == after.get("strength"):
            return {"outcome": "corroborated", "parts": [], "merged": before}
        return {"outcome": "changed",
                "parts": [{"part": "strength", "previous": before.get("strength"),
                           "new": after.get("strength"), "outcome": "changed"}],
                "merged": after}
    if (key in DESCRIPTIVE and isinstance(before, str) and isinstance(after, str)
            and _numbers(before) == _numbers(after)):
        old_words, new_words = _words(before), _words(after)
        shared = old_words & new_words
        if old_words and new_words and len(shared) >= 0.5 * min(len(old_words), len(new_words)):
            return {"outcome": "corroborated", "parts": [], "merged": before}
    if (key in DESCRIPTIVE and isinstance(before, str) and isinstance(after, str)
            and covers(before, after, share=0.6)):
        # 6 Nov 2026: a shorter description saying nothing the recorded one does
        # not already say never replaces it.
        return {"outcome": "corroborated", "parts": [], "merged": before}
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        return _compare_parts(key, dict(before), dict(after))
    if isinstance(before, list) and isinstance(after, list):
        return _compare_lists(before, after)
    # Plain text, or a value recorded before parts: compare what they say. A
    # recorded paragraph that already states a new reading's parts (in its
    # own words: "an NRG company" / "subsidiary of NRG Energy") is kept.
    legacy = isinstance(before, str) and isinstance(after, Mapping)
    if same_text(before, after) or covers(before, after, share=0.5 if legacy else 0.7):
        return {"outcome": "corroborated", "parts": [], "merged": before}
    if covers(after, before):
        return {"outcome": "additional", "parts": [], "merged": after}
    return {"outcome": "changed", "parts": [], "merged": after}


def _compare_lists(before: list, after: list) -> dict:
    known = [str(item) for item in before]
    added = [item for item in after
             if not any(same_text(item, old) for old in known)]
    if not added:
        return {"outcome": "corroborated", "parts": [], "merged": before}
    return {"outcome": "additional",
            "parts": [{"part": "items", "previous": before, "new": added, "outcome": "additional"}],
            "merged": [*before, *added]}


def _compare_parts(key: str, before: dict, after: dict) -> dict:
    carried = set(before.get(CARRIED_OVER) or [])
    names = [n for n in dict.fromkeys([*after, *before]) if n != CARRIED_OVER]
    parts, merged = [], {}
    for name in names:
        old, new = before.get(name), after.get(name)
        has_old, has_new = old not in (None, "", [], {}), new not in (None, "", [], {})
        if has_old and has_new:
            if isinstance(old, list) and isinstance(new, list):
                listed = _compare_lists(old, new)
                outcome = "confirmed" if listed["outcome"] == "corroborated" else "additional"
                merged[name] = listed["merged"]
            elif (_same_part(old, new) and not isinstance(new, (int, float))
                  and covers(new, old) and len(_words(_text(new))) > len(_words(_text(old)))):
                # The same fact, stated more fully: the fuller wording is kept.
                outcome, merged[name] = "additional", new
            elif _same_part(old, new):
                outcome, merged[name] = "confirmed", old
            elif not isinstance(old, (int, float)) and covers(old, new):
                # The recorded part already says it, and more ("U.S. Department of
                # Energy, Office of Science" read again as "Department of Energy"):
                # kept, never made poorer (6 Nov 2026).
                outcome, merged[name] = "confirmed", old
            elif not isinstance(new, (int, float)) and covers(new, old):
                outcome, merged[name] = "additional", new
            else:
                outcome, merged[name] = "changed", new
            parts.append({"part": name, "previous": old, "new": new, "outcome": outcome})
            carried.discard(name)
        elif has_new:
            merged[name] = new
            parts.append({"part": name, "previous": None, "new": new, "outcome": "additional"})
        elif has_old:
            parts.append({"part": name, "previous": old, "new": None, "outcome": "not_restated"})
            merged[name] = old
            carried.add(name)
    changed = any(p["outcome"] == "changed" for p in parts)
    added = any(p["outcome"] == "additional" for p in parts)
    if not changed and not added:
        return {"outcome": "corroborated", "parts": parts, "merged": before}
    if changed and key not in PROFILE_BOXES:
        # One thing described (a project, a grant): a different one replaces it.
        replaced = {n: after[n] for n in after if after[n] not in (None, "", [], {})
                    and n != CARRIED_OVER}
        return {"outcome": "changed", "parts": parts, "merged": replaced}
    if carried:
        merged[CARRIED_OVER] = sorted(carried)
    return {"outcome": "changed" if changed else "additional", "parts": parts,
            "merged": merged}


def parts_line(parts) -> str:
    """'Employees: 500 → 600 · Places: confirmed · Customers: added (2000)'."""
    words = []
    for part in parts or []:
        label = part["part"].replace("_", " ").capitalize()
        if part["outcome"] == "changed":
            words.append(f"{label}: {_short(part['previous'])} → {_short(part['new'])}")
        elif part["outcome"] == "confirmed":
            words.append(f"{label}: confirmed")
        elif part["outcome"] == "additional" and part["part"] == ENTRIES:
            count = len(part["new"])
            words.append(f"{count} new {'entry' if count == 1 else 'entries'} added beside "
                         f"the {part['previous']} recorded")
        elif part["outcome"] == "additional":
            words.append(f"{label}: added ({_short(part['new'])})")
        elif part["outcome"] == "not_restated":
            words.append(f"{label}: kept (not on these pages)")
    return " · ".join(words)


def _short(value) -> str:
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    return text if len(text) <= 60 else text[:59] + "…"
