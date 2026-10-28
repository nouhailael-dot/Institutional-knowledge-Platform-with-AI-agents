"""Results a reviewer can use: grounded descriptions, one event once, readable actors first."""

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


def test_one_event_is_staged_once_however_its_pages_spell_it():
    from agents.discovery.quality_gates import event_name_key, same_event

    official = {"title": "2027 WateReuse Symposium", "start_date": "2027-03-01",
                "source_url": "https://watereuse.org/news-events/conferences/2027-watereuse-symposium/"}
    # Measured 2026-10-28: staged six times in three runs.
    assert same_event({**official, "title": "anything"},
                      {"name": "x", "source_url": "https://www.watereuse.org/news-events/"
                                                  "conferences/2027-watereuse-symposium"})
    assert same_event({"title": "2027 WaterReuse Symposium", "start_date": "2027-03-01",
                       "source_url": "https://allianceforwaterefficiency.org/2027-waterreuse-symposium"},
                      official)
    assert same_event({"title": "WateReuse Symposium 2027 (42nd Annual)", "start_date": "2027-03-01",
                       "source_url": "https://emitree.com/conferences/watereuse-symposium"}, official)
    assert event_name_key("WateReuse Symposium 2027 (42nd Annual)") == "watereusesymposium"
    # Another edition, another series, or a name alone without dates: not the same.
    assert not same_event({**official, "start_date": "2028-03-06", "source_url": "u1"},
                          {**official, "source_url": "u2"})
    assert not same_event({"title": "2027 WateReuse California", "start_date": "2027-03-01",
                           "source_url": "u1"}, official)
    assert not same_event({"title": "2027 WaterReuse Symposium", "source_url": "u1"},
                          {"name": "2027 WateReuse Symposium", "source_url": "u2"})
    assert same_event({"title": "2027 WateReuse Symposium", "source_url": "u1"},
                      {"name": "WateReuse Symposium", "source_url": "u2"})


def test_an_update_reads_actors_whose_sites_answer_before_one_that_refused(monkeypatch):
    from agents.collection import actor_updates

    actors = [{"actor_id": "glc", "name": "Great Lakes Commission", "website": "https://www.glc.org",
               "actor_category": "association_network"},
              {"actor_id": "nu", "name": "Northwestern", "website": "https://nu.example.edu",
               "actor_category": "university_academic"},
              {"actor_id": "tamu", "name": "Texas A&M", "website": "https://tamu.example.edu",
               "actor_category": "university_academic"}]
    monkeypatch.setattr(actor_updates, "group_actors", lambda session, **kw: actors)
    monkeypatch.setattr(actor_updates, "topic_by_code",
                        lambda session, code: {"topic_id": "t", "code": code})
    monkeypatch.setattr(actor_updates, "schema_fields", lambda category: ["a", "b", "c"])
    monkeypatch.setattr(actor_updates, "current_values", lambda *args: {})
    # The Great Lakes Commission has the most gaps.
    monkeypatch.setattr(actor_updates, "plan_fields", lambda *args, **kw: (["a", "b", "c"], []))

    class Blocked:
        def blocked(self, url):
            return ({"retry_after": "2026-11-11T12:52:16+00:00"} if "glc.org" in url else None)

    prepared = {"actor_ids": [], "sector": "WATER", "state": None,
                "options": {"category": None, "topic": "WATER", "scope": "general", "fields": [],
                            "categories": [], "max_actors_per_run": 2}}
    choice = actor_updates.choose_actors(None, prepared, blocked_sites=Blocked())
    assert [a["actor_id"] for a in choice["chosen"]] == ["nu", "tamu"]
    waiting = {w["actor_id"]: w["reason"] for w in choice["waiting"]}
    assert "refuses automated access" in waiting["glc"] and "2026-11-11" in waiting["glc"]
    # With room under the cap it is still read, last, through the fallback sources.
    prepared["options"]["max_actors_per_run"] = 3
    choice = actor_updates.choose_actors(None, prepared, blocked_sites=Blocked())
    assert [a["actor_id"] for a in choice["chosen"]] == ["nu", "tamu", "glc"]
