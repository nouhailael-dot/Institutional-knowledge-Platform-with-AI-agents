"""
Phase 4 extractor #2 — researchers from a hub's talent narrative.

Pure logic, no database. Given a hub's name and its talent_narrative, returns a
cleaned list of people:

    [{"full_name", "title", "research_area", "affiliation", "confidence", "evidence"}, ...]

Uses Sonnet (richer reasoning over messy prose). A person-validity filter drops
organizations, bare acronyms, and empty names so the runner never tries to
persist non-people.
"""

import re

from src.ai.client import SONNET, structured_json

ORG_TERMS = {
    "academy",
    "agency",
    "association",
    "center",
    "centre",
    "college",
    "company",
    "consortium",
    "corporation",
    "department",
    "foundation",
    "group",
    "hub",
    "institute",
    "initiative",
    "laboratories",
    "laboratory",
    "lab",
    "labs",
    "ministry",
    "office",
    "program",
    "programme",
    "school",
    "university",
}

SYSTEM = """You extract named individual people from an ecosystem hub's "talent" narrative.

Return only real, named individuals — researchers, professors, lab directors,
program leads, founders. Do NOT return organizations, departments, programs,
generic roles, or unnamed groups.

For each person provide:
- full_name: the person's name exactly as written
- title: their role/title if explicitly stated, else null
- research_area: their research area if explicitly tied to them, else null
- affiliation: the organization they are associated with if explicitly stated, else null
- confidence: 0.0-1.0, how sure you are this is a real named person from the text
- evidence: a short phrase from the narrative that mentions them

If the narrative names no individuals, return an empty list.
Respond with ONLY a JSON object, no prose and no markdown fences:
{"people": [{"full_name": "...", "title": null, "research_area": null, "affiliation": null, "confidence": 0.0, "evidence": "..."}]}"""


def _looks_like_person(name: str) -> bool:
    n = name.strip()
    if len(n) < 3 or not any(c.isalpha() for c in n):
        return False
    # a single all-caps short token is almost certainly an acronym, not a person
    if " " not in n and n.isupper() and len(n) <= 6:
        return False
    words = {w.lower().strip(".,;:()[]") for w in n.split()}
    if words & ORG_TERMS:
        return False
    return True


def _clean_optional(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def extract_researchers(hub_name: str, talent_narrative: str,
                       model: str = SONNET, tracker=None) -> list[dict]:
    text = (talent_narrative or "").strip()
    if not text:
        return []
    user = (f"Hub: {hub_name}\n\n"
            f"Talent narrative:\n{text}\n\n"
            "Extract the named people.")
    out = structured_json(SYSTEM, user, model=model, max_tokens=2000, tracker=tracker)
    if not out:
        return []

    people = out.get("people", [])
    cleaned = []
    for p in people if isinstance(people, list) else []:
        name = str(p.get("full_name", "")).strip()
        if not name or not _looks_like_person(name):
            continue
        try:
            conf = max(0.0, min(1.0, float(p.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        cleaned.append({
            "full_name": re.sub(r"\s+", " ", name),
            "title": _clean_optional(p.get("title")),
            "research_area": _clean_optional(p.get("research_area")),
            "affiliation": _clean_optional(p.get("affiliation")),
            "confidence": conf,
            "evidence": str(p.get("evidence", ""))[:500],
        })
    return cleaned
