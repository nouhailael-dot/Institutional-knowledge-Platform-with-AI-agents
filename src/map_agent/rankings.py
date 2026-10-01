"""Validate source-linked university rankings; dedicated lookups live in research.py."""
import re
from src.map_agent.search_backend import canonical_url

PUBLISHERS = ("QS World University Rankings", "Times Higher Education World University Rankings")
RANKING_DOMAINS = {PUBLISHERS[0]: "topuniversities.com", PUBLISHERS[1]: "timeshighereducation.com"}
UNIVERSITY_TYPES = {"university", "academic institution", "university academic institution", "university academic"}


def is_university(entity):
    kind = re.sub(r"[^a-z]+", " ", str(entity.get("actor_type", "")).lower()).strip()
    # A university-affiliated lab or department is not the ranked institution.
    return kind in UNIVERSITY_TYPES and not re.search(
        r"\b(lab|laboratory|laboratories|department|center|centre|school of)\b",
        str(entity.get("name", "")), re.I)


def institution_name(name):
    """The name the ranking publishers use, with a short alias dropped.

    Records carry two kinds of parenthetical: an alias of the institution itself
    ("(MIT)"), which publishers omit, and a unit inside it ("(Office of
    Environmental Stewardship)"), which is not the ranked entity at all. Only the
    first is removed, so a unit keeps a name no publisher will match.
    """
    def strip(match):
        inner = match.group(1).strip()
        return "" if len(inner) <= 15 and len(inner.split()) <= 2 else match.group(0)
    return re.sub(r"\s*\(([^)]*)\)", strip, str(name or "")).strip()


def is_ranked_institution(entity):
    """Whole institutions only — a named unit inside one inherits no ranking."""
    return is_university(entity) and "(" not in institution_name(entity.get("name", ""))


def same_institution(left, right):
    """Compare publisher and record names ignoring case, spacing and punctuation."""
    def words(value):
        return " ".join(w for w in re.split(r"[\W_]+", str(value or "")) if w).casefold()
    return bool(words(left)) and words(left) == words(right)


def filter_rankings(entity, available):
    """Reject unsupported publishers, incomplete entries and absent source URLs.

    This validates structure/provenance, not the truth of the reported rank.
    """
    if not is_university(entity):
        entity.pop("rankings", None)
        return
    out, seen = [], set()
    rows = entity.get("rankings")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("system") not in PUBLISHERS:
            continue
        rank, year, scope = row.get("rank"), row.get("year"), row.get("scope")
        if not isinstance(rank, str) or not re.fullmatch(r"=?\d{1,4}(?:[-–]\d{1,4}|\+)?", rank.strip()):
            continue
        if type(year) is not int or not 1900 <= year <= 2100 or scope not in ("overall", "subject"):
            continue
        subject = row.get("subject", "")
        if not isinstance(subject, str) or (scope == "subject" and not subject.strip()):
            continue
        try:
            url = canonical_url(row.get("source_url", ""))
        except (ValueError, TypeError):
            continue
        if url not in available:
            continue
        clean = {"system": row["system"], "rank": rank.strip(), "year": year,
                 "scope": scope, "subject": subject.strip() if scope == "subject" else "",
                 "source_url": url}
        key = tuple(clean.values())
        if key not in seen:
            seen.add(key)
            out.append(clean)
    entity["rankings"] = out
