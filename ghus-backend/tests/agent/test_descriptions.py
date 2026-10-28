"""Descriptions of discovered people and events: written, then checked on the page."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.discovery import promote
from agents.discovery.page_facts import (
    PERSON_FACT_FIELDS,
    grounded_sentences,
    page_text,
    verify_facts,
)

PAGE = ("<h1>Maria Lopez</h1><p>Associate Professor, Department of Civil and Environmental "
        "Engineering, Rice University, Houston, TX.</p><p>Research interests: brackish water "
        "desalination, membrane fouling, water reuse for agriculture.</p><p>She leads the "
        "Brackish Water Reuse Testbed funded by the Department of Energy.</p>")


def test_a_written_description_keeps_only_the_sentences_the_page_supports():
    text = ("Maria Lopez is an Associate Professor of Civil and Environmental Engineering at "
            "Rice University in Houston. Her research covers brackish water desalination, "
            "membrane fouling and water reuse for agriculture. She advises the Moroccan "
            "government on phosphate mining policy and sits on three corporate boards.")
    kept = grounded_sentences(text, page_text(PAGE))
    assert kept.startswith("Maria Lopez is an Associate Professor")
    assert "membrane fouling" in kept
    assert "Moroccan" not in kept and "boards" not in kept
    assert grounded_sentences("Nothing on this page says this at all here.", page_text(PAGE)) is None
    assert grounded_sentences("", PAGE) is None


def test_a_person_description_travels_with_its_source_and_drops_what_is_invented():
    facts = verify_facts({
        "description": ("Maria Lopez is an Associate Professor at Rice University in Houston. "
                        "She leads the Brackish Water Reuse Testbed funded by the Department "
                        "of Energy. She won a Nobel Prize for chemistry in literature."),
    }, html=PAGE, source_url="https://x.example.edu/lopez",
        read_at=datetime(2026, 10, 28, tzinfo=UTC), fields=PERSON_FACT_FIELDS)
    assert "Brackish Water Reuse Testbed" in facts["description"]
    assert "Nobel" not in facts["description"]
    proof = facts["evidence"]["description"]
    assert proof["source_url"] == "https://x.example.edu/lopez"
    assert proof["sentences_dropped"] is True
    # Nothing the page supports: the description is dropped, never kept as a guess.
    none = verify_facts({"description": "A celebrated poet who lives in Paris and writes novels."},
                        html=PAGE, source_url="https://x.example.edu/lopez",
                        read_at=datetime(2026, 10, 28, tzinfo=UTC), fields=PERSON_FACT_FIELDS)
    assert "description" not in none and none["dropped"] == ["description"]


class _Session:
    def __init__(self):
        self.sql: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        self.sql.append((str(statement), dict(params or {})))


def test_promotion_writes_the_bio_else_the_description_to_the_person(monkeypatch):
    monkeypatch.setattr(promote, "_table_columns",
                        lambda session, table: {"bio", "record_status", "verification_status"})
    payload = {"name": "Maria Lopez", "role": "Associate Professor",
               "facts": {"description": "Maria Lopez is an Associate Professor at Rice University."}}
    session = _Session()
    promote._insert_person(session, payload, "00000000-0000-0000-0000-000000000001", confidence=0.8)
    assert session.sql[-1][1]["bio"] == "Maria Lopez is an Associate Professor at Rice University."
    payload["facts"]["bio"] = "Maria Lopez joined Rice in 2019."
    session = _Session()
    promote._insert_person(session, payload, "00000000-0000-0000-0000-000000000001", confidence=0.8)
    assert session.sql[-1][1]["bio"] == "Maria Lopez joined Rice in 2019."
    session = _Session()
    promote._insert_person(session, {"name": "A B", "role": "Engineer"},
                           "00000000-0000-0000-0000-000000000001", confidence=0.8)
    assert "bio" not in session.sql[-1][1]
