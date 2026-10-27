"""Isolated PostgreSQL proof of actor updates: plan, check, apply, Review decisions.

Synthetic fixtures only: each test makes its own topic, so the facts it writes
never meet another test's (or the demo's). The page reader is a stand-in; no
network, no model call.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from agents.collection import actor_updates as au
from agents.collection.deep_pull import DEEP_FIELDS
from agents.collection.deep_pull_reader import MAX_DEEP_FIELDS
from agents.collection.light_pull_reader import LightRead
from agents.common.facts import ActorFactWrite
from agents.enrichment.decisions import (
    append_actor_fact,
    record_fact_review_decision,
    record_verification_decision,
)

pytestmark = pytest.mark.skipif(not os.environ.get("V2_TEST_DATABASE_URL"),
                                reason="V2_TEST_DATABASE_URL is required")
CONFIG = {"actor_updates": dict(au.DEFAULT_SETTINGS)}


def _guarded_url() -> str:
    raw = os.environ["V2_TEST_DATABASE_URL"]
    parsed = urlsplit(raw.replace("postgresql+psycopg2", "postgresql", 1))
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or not parsed.path.removeprefix("/").endswith("_test")):
        raise RuntimeError("actor update integration tests refuse non-local/non-test databases")
    return raw


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(_guarded_url(), future=True)
    yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    engine.dispose()


@pytest.fixture()
def world(session_factory):
    """A company actor with a website, and a fresh topic of its own."""
    with session_factory() as session:
        actor = session.execute(text(
            "SELECT actor_id::text FROM actor WHERE actor_category = 'company' "
            "AND website LIKE 'http%' ORDER BY actor_id LIMIT 1")).scalar_one()
        code = f"AU{uuid.uuid4().hex[:8].upper()}"
        topic = session.execute(text(
            # Inactive: a test topic must never appear in a sector list.
            "INSERT INTO topic(code, name, active) VALUES (:c, :n, false) RETURNING topic_id::text"
        ), {"c": code, "n": f"Actor update test {code}"}).scalar_one()
        session.commit()
    return {"actor": actor, "topic": topic, "code": code}


class FakeMeter:
    def __init__(self, spent):
        self.spent_usd = spent


class FakeReader:
    """Returns fixed evidence; records what it was asked."""

    def __init__(self, evidence, rejected=None, pages=("https://co.example/",
                                                       "https://co.example/about")):
        self.evidence, self.rejected, self.pages, self.calls = evidence, rejected or {}, pages, []

    def read(self, **kwargs):
        self.calls.append(kwargs)
        read = LightRead(pages=list(self.pages))
        if not self.pages:
            read.error = "site could not be read: HTTPError: 403"
            return read
        for key in kwargs["fields"]:
            value = self.evidence.get(key)
            read.evidence[key] = (
                {"collection_state": "found", "value": value, "confidence": "high",
                 "source_url": self.pages[-1], "date_read": kwargs["read_at"].isoformat(),
                 "source_origin": "newly_found"} if value is not None else
                {"collection_state": "not_found", "value": None, "confidence": "medium",
                 "source_url": self.pages[0], "date_read": kwargs["read_at"].isoformat(),
                 "source_origin": "newly_found"})
        read.rejected = dict(self.rejected)
        return read


def _factory(reader, spent=0.03, seen=None):
    def make(cap):
        if seen is not None:
            seen.append(cap)
        return reader, FakeMeter(spent), "fake-model"
    return make


def _seed(session, world, key, value, *, when, confidence="medium", by="agent.seed",
          origin="newly_found"):
    return append_actor_fact(session, ActorFactWrite(
        actor_id=world["actor"], topic_id=world["topic"], field_key=key, fact_type="light_pull",
        layer=1, value=value, collection_state="found",
        source_url=f"https://seed.example/{uuid.uuid4().hex}", source_origin=origin,
        date_read=when, confidence=confidence, created_by=by), live=True)


def _count(session, sql, **params):
    return session.execute(text(sql), params).scalar_one()


def _ledger(session):
    return (_count(session, "SELECT count(*) FROM actor_fact"),
            _count(session, "SELECT count(*) FROM collection_run"),
            _count(session, "SELECT count(*) FROM review_item"))


EVIDENCE = {
    "location": "Austin, TX",                                   # new
    "funding_signal": "$2M grant from NSF in 2026.",            # changed
    "recent_activity": "Opened a pilot plant in May 2026.",     # conflict (current is newer)
    "international_connection": "Office in Rabat, Morocco.",    # protected (GHUS)
    "um6p_ocp_connection": "Has a partnership with UM6P on water reuse.",  # corroborated
    "why_matched": None,                                        # not found
}


def _seed_world(session, world):
    past = datetime.now(UTC) - timedelta(days=400)
    _seed(session, world, "funding_signal", "$1M grant from DOE in 2024.", when=past)
    _seed(session, world, "recent_activity", "Hosted a summit in 2025.",
          when=datetime.now(UTC) + timedelta(days=30), confidence="high")
    _seed(session, world, "international_connection", "Office in Casablanca.", when=past,
          by="ghus:reviewer", origin="ghus_manual")
    _seed(session, world, "um6p_ocp_connection", "Partnership with UM6P on water reuse.",
          when=past)
    session.commit()


# ---------------------------------------------------------------- plan

def test_plan_is_free_and_writes_nothing(session_factory, world, tmp_path):
    with session_factory() as session:
        before = _ledger(session)
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              scope="topic", config=CONFIG, runs_dir=tmp_path)
        assert _ledger(session) == before
    assert plan["ok"] and plan["can_check"]
    assert plan["topic"]["code"] == world["code"]
    assert plan["fields"] == au.schema_fields("company")
    assert plan["cost"]["cap_usd"] == CONFIG["actor_updates"]["max_usd_per_actor"]
    # Three page requests at most; a fallback search is disclosed, never hidden.
    assert plan["pages"].startswith("Up to 3 page requests in total")
    assert "web search" in plan["pages"]
    assert plan["summary"].startswith("Re-read ")


def test_cost_estimate_comes_from_recorded_runs_never_invented(session_factory, tmp_path):
    with session_factory() as session:
        estimate = au.cost_estimate(session, CONFIG["actor_updates"], runs_dir=tmp_path)
        recorded = _count(session, "SELECT count(*) FROM collection_run "
                                   "WHERE job_name='actor_update' AND spent_usd > 0")
    if recorded == 0:
        assert estimate["typical_usd"] is None and "no history" in estimate["basis"]
    else:
        assert estimate["runs"] == min(recorded, 50) and estimate["low_usd"] > 0


def test_deep_pull_is_refused_without_verification_for_that_exact_topic(
        session_factory, world, tmp_path):
    with session_factory() as session:
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              depth="deep", config=CONFIG, runs_dir=tmp_path)
        assert plan["ok"] and not plan["can_check"]
        assert not plan["deep"]["permitted"]
        assert "Light Refresh" in plan["refusal"]
        reader = FakeReader(EVIDENCE)
        result = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                 depth="deep", config=CONFIG, runs_dir=tmp_path,
                                 reader_factory=_factory(reader))
        assert result["ok"] is False and reader.calls == []


def test_deep_pull_permission_follows_the_ghus_decision_for_the_topic(
        session_factory, world, tmp_path):
    with session_factory() as session:
        record_verification_decision(session, entity_type="actor", entity_ids=[world["actor"]],
                                     decision="verified", decided_by="ghus:test",
                                     topic_id=world["topic"])
        session.commit()
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              depth="deep", config=CONFIG, runs_dir=tmp_path)
    assert plan["deep"]["permitted"] and plan["can_check"] and not plan.get("refusal")


def _verify(session, world, decision="verified"):
    record_verification_decision(
        session, entity_type="actor", entity_ids=[world["actor"]], decision=decision,
        decided_by="ghus:test", topic_id=world["topic"],
        rejection_reason="Other" if decision == "rejected" else None)
    session.commit()


def test_a_verified_actor_gets_a_selected_deep_pull_written_as_layer_2(
        session_factory, world, tmp_path):
    deep = DEEP_FIELDS["company"]
    with session_factory() as session:
        _verify(session, world)
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              depth="deep", config=CONFIG, runs_dir=tmp_path)
        assert plan["schema"] == list(deep)
        # Selected, never exhaustive: a few Deep items, the rest said to wait.
        assert 0 < len(plan["fields"]) <= MAX_DEEP_FIELDS < len(deep)
        assert set(plan["fields"]) | {s["field"] for s in plan["skipped"]} == set(deep)
        assert "Deep Pull, selected" in plan["summary"]
        stated = plan["fields"][0]
        reader = FakeReader({stated: "Filtration units for small-town water systems."})
        checked = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                  depth="deep", config=CONFIG, runs_dir=tmp_path,
                                  reader_factory=_factory(reader))
        assert checked["ok"], checked.get("error")
        assert reader.calls[0]["fields"] == plan["fields"]
        applied = au.apply_check(session, checked["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert applied["ok"], applied.get("error")
        rows = session.execute(text(
            "SELECT fact_key, layer, fact_type, collection_state FROM actor_fact "
            "WHERE actor_id = CAST(:a AS uuid) AND topic_id = CAST(:t AS uuid)"),
            {"a": world["actor"], "t": world["topic"]}).all()
        assert {(r.fact_key, r.layer, r.fact_type) for r in rows} == {
            (f, 2, "deep_pull") for f in plan["fields"]}
        assert {r.fact_key: r.collection_state for r in rows}[stated] == "found"
        kind = session.execute(text(
            "SELECT q.request_kind, q.layer FROM collection_run r JOIN collection_request q "
            "ON q.collection_request_id = r.collection_request_id "
            "WHERE r.collection_run_id = CAST(:r AS uuid)"), {"r": applied["run_id"]}).one()
        assert tuple(kind) == ("deep_pull", 2)


def test_a_deep_pull_is_not_written_when_verification_is_reversed_after_the_check(
        session_factory, world, tmp_path):
    with session_factory() as session:
        _verify(session, world)
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              depth="deep", config=CONFIG, runs_dir=tmp_path)
        reader = FakeReader({plan["fields"][0]: "Filtration units for small towns."})
        checked = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                  depth="deep", config=CONFIG, runs_dir=tmp_path,
                                  reader_factory=_factory(reader))
        _verify(session, world, decision="rejected")
        before = _ledger(session)
        applied = au.apply_check(session, checked["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert applied["ok"] is False and "no longer" in applied["error"]
        assert _ledger(session) == before


# ---------------------------------------------------------- check + apply

def test_check_predicts_and_apply_writes_exactly_the_phase11_outcomes(
        session_factory, world, tmp_path):
    with session_factory() as session:
        _seed_world(session, world)
        ghus_fact = session.execute(text(
            "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE "
            "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) "
            "AND fact_key='international_connection'"),
            {"a": world["actor"], "t": world["topic"]}).scalar_one()
        old_funding = session.execute(text(
            "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE "
            "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) "
            "AND fact_key='funding_signal'"),
            {"a": world["actor"], "t": world["topic"]}).scalar_one()
        before = _ledger(session)
        reader = FakeReader(EVIDENCE)
        check = au.check_update(
            session, actor_id=world["actor"], topic_code=world["code"], scope="specific",
            fields=list(EVIDENCE), config=CONFIG, runs_dir=tmp_path,
            reader_factory=_factory(reader))
        # A check reads pages but writes no database row.
        assert _ledger(session) == before
        predicted = {f["field"]: f["outcome"] for f in check["findings"]}
        assert predicted == {
            "location": "new", "funding_signal": "changed", "recent_activity": "conflict",
            "international_connection": "protected", "um6p_ocp_connection": "corroborated",
            "why_matched": "not_found",
        }
        assert check["counts"] == {"new": 1, "changed": 1, "conflicts": 2, "confirmed": 1,
                                   "missing": 1}
        finding = next(f for f in check["findings"] if f["field"] == "funding_signal")
        assert finding["previous"]["value"] == "$1M grant from DOE in 2024."
        assert finding["proposed"]["source_url"] == "https://co.example/about"
        assert finding["proposed"]["confidence"] == "high"
        assert finding["topic"].startswith("Actor update test")

        applied = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert applied["ok"], applied
        actual = {r["field"]: r["actual"] for r in applied["results"]}
        assert actual == predicted
        assert applied["review_items"] == 2

        # GHUS's value is still current; the old funding fact is history, not gone.
        pointer = session.execute(text(
            "SELECT fact_key, actor_fact_id::text FROM actor_fact_current_pointer WHERE "
            "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid)"),
            {"a": world["actor"], "t": world["topic"]}).all()
        current = dict(pointer)
        assert current["international_connection"] == ghus_fact
        assert current["funding_signal"] != old_funding
        assert _count(session, "SELECT count(*) FROM actor_fact WHERE "
                               "actor_fact_id=CAST(:id AS uuid)", id=old_funding) == 1
        # The run is in the ledger, with its cost, and every fact carries it.
        run = session.execute(text(
            "SELECT r.status, r.spent_usd, r.fetch_count, r.review_item_count, "
            "q.collection_request_id::text AS request_id, q.actor_id::text AS actor_id "
            "FROM collection_run r JOIN collection_request q USING (collection_request_id) "
            "WHERE r.collection_run_id=CAST(:id AS uuid)"), {"id": applied["run_id"]}
        ).mappings().one()
        assert (run["status"], float(run["spent_usd"]), run["fetch_count"]) == (
            "succeeded", 0.03, 2)
        assert run["review_item_count"] == 2 and run["actor_id"] == world["actor"]
        assert _count(session, "SELECT count(*) FROM actor_fact WHERE request_id="
                               "CAST(:r AS uuid)", r=run["request_id"]) == 5
        assert _count(session, "SELECT count(*) FROM review_item WHERE entity_id="
                               "CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND status="
                               "'pending' AND review_kind IN ('fact_conflict','pending_update')",
                      a=world["actor"], t=world["topic"]) == 2

        # Applying the same check again writes nothing twice.
        again = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert again["ok"] and again["results"] == []

        # The last successful update is shown on the next plan.
        plan = au.plan_update(session, actor_id=world["actor"], topic_code=world["code"],
                              config=CONFIG, runs_dir=tmp_path)
        assert plan["last_update"]["status"] == "succeeded"


def test_an_update_compares_fact_by_fact_and_never_makes_a_box_poorer(
        session_factory, world, tmp_path):
    """500 -> 600 employees is one change; what the page did not restate is kept."""
    with session_factory() as session:
        past = datetime.now(UTC) - timedelta(days=40)
        old = _seed(session, world, "ownership_and_size",
                    {"employees": 500, "ownership": "private", "customers": 2000},
                    when=past, confidence="medium")
        session.commit()
        reader = FakeReader({"ownership_and_size": {"employees": 600}})
        check = au.check_update(
            session, actor_id=world["actor"], topic_code=world["code"], scope="specific",
            fields=["ownership_and_size"], config=CONFIG, runs_dir=tmp_path,
            reader_factory=_factory(reader))
        finding = check["findings"][0]
        assert finding["outcome"] == "changed"
        assert {p["part"]: p["outcome"] for p in finding["parts"]} == {
            "employees": "changed", "ownership": "not_restated", "customers": "not_restated"}
        assert finding["what_changed"].startswith("Employees: 500 → 600")
        applied = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert applied["ok"], applied
        current = session.execute(text(
            "SELECT f.fact_value, f.supersedes_fact_id::text AS supersedes FROM "
            "actor_fact_current_pointer p JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id "
            "WHERE p.actor_id=CAST(:a AS uuid) AND p.topic_id=CAST(:t AS uuid) "
            "AND p.fact_key='ownership_and_size'"),
            {"a": world["actor"], "t": world["topic"]}).mappings().one()
        assert current["fact_value"] == {"employees": 600, "ownership": "private",
                                         "customers": 2000,
                                         "carried_over": ["customers", "ownership"]}
        assert current["supersedes"] == old           # the earlier fact is history, not gone
        # The same facts again, in fewer words: confirmed, nothing replaced.
        again = au.check_update(
            session, actor_id=world["actor"], topic_code=world["code"], scope="specific",
            fields=["ownership_and_size"], config=CONFIG, runs_dir=tmp_path,
            reader_factory=_factory(FakeReader({"ownership_and_size": {"employees": 600}})))
        assert again["findings"][0]["outcome"] == "corroborated"


def test_missing_scope_skips_the_read_when_nothing_is_missing(session_factory, world, tmp_path):
    with session_factory() as session:
        now = datetime.now(UTC)
        for key in au.schema_fields("company"):
            _seed(session, world, key, f"Recorded {key}.", when=now)
        session.commit()
        reader = FakeReader(EVIDENCE)
        result = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                 scope="missing", config=CONFIG, runs_dir=tmp_path,
                                 reader_factory=_factory(reader))
    assert result["ok"] and result["fields"] == [] and result["cost_usd"] == 0.0
    assert reader.calls == []


def test_the_cost_cap_is_the_configured_one_or_lower(session_factory, world, tmp_path):
    caps: list[float] = []
    with session_factory() as session:
        au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                        scope="specific", fields=["location"], config=CONFIG, max_usd=0.05,
                        runs_dir=tmp_path, reader_factory=_factory(FakeReader(EVIDENCE), seen=caps))
        au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                        scope="specific", fields=["location"], config=CONFIG, max_usd=5.0,
                        runs_dir=tmp_path, reader_factory=_factory(FakeReader(EVIDENCE), seen=caps))
    assert caps == [0.05, CONFIG["actor_updates"]["max_usd_per_actor"]]


def test_an_unreadable_site_reports_the_failure_and_writes_nothing(
        session_factory, world, tmp_path):
    with session_factory() as session:
        before = _ledger(session)
        result = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                 config=CONFIG, runs_dir=tmp_path,
                                 reader_factory=_factory(FakeReader({}, pages=())))
        assert _ledger(session) == before
    assert result["ok"] is False and "could not be read" in result["error"]
    assert list(tmp_path.glob("*.json")) == []


def test_a_failed_box_does_not_stop_the_others_and_a_retry_writes_only_it(
        session_factory, world, tmp_path, monkeypatch):
    with session_factory() as session:
        check = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                scope="specific", fields=["location", "funding_signal"],
                                config=CONFIG, runs_dir=tmp_path,
                                reader_factory=_factory(FakeReader(EVIDENCE)))
        import agents.enrichment.decisions as decisions

        real = decisions.append_actor_fact

        def flaky(session_, write, live=False):
            if write.field_key == "funding_signal":
                raise RuntimeError("simulated outage")
            return real(session_, write, live=live)

        monkeypatch.setattr(decisions, "append_actor_fact", flaky)
        first = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert first["ok"] is False and first["failed"] == 1
        assert {r["field"]: r["written"] for r in first["results"]} == {
            "location": True, "funding_signal": False}
        status = _count(session, "SELECT status FROM collection_run WHERE "
                                 "collection_run_id=CAST(:id AS uuid)", id=first["run_id"])
        assert status == "attention"

        monkeypatch.setattr(decisions, "append_actor_fact", real)
        retry = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert retry["ok"] and [r["field"] for r in retry["results"]] == ["funding_signal"]
        assert retry["run_id"] == first["run_id"]
        assert _count(session, "SELECT count(*) FROM actor_fact WHERE actor_id=CAST(:a AS uuid) "
                               "AND topic_id=CAST(:t AS uuid)",
                      a=world["actor"], t=world["topic"]) == 2


def test_an_old_check_must_be_run_again(session_factory, world, tmp_path):
    with session_factory() as session:
        check = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                scope="specific", fields=["location"], config=CONFIG,
                                runs_dir=tmp_path, reader_factory=_factory(FakeReader(EVIDENCE)))
        later = datetime.now(UTC) + timedelta(hours=25)
        result = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG,
                                now=later)
    assert result["ok"] is False and "Run the check again" in result["error"]


def test_updates_never_create_or_duplicate_actors(session_factory, world, tmp_path):
    with session_factory() as session:
        actors = _count(session, "SELECT count(*) FROM actor")
        check = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                config=CONFIG, runs_dir=tmp_path,
                                reader_factory=_factory(FakeReader(EVIDENCE)))
        au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert _count(session, "SELECT count(*) FROM actor") == actors


# -------------------------------------------------------- Review decision

def _conflict(session, world, *, ghus=False):
    past = datetime.now(UTC) - timedelta(days=10)
    current = _seed(session, world, "funding_signal", "$1M.", when=past,
                    by="ghus:reviewer" if ghus else "agent.seed",
                    origin="ghus_manual" if ghus else "newly_found", confidence="high")
    proposed = _seed(session, world, "funding_signal", "$3M.", when=past - timedelta(days=5),
                     confidence="low")
    session.commit()
    item = session.execute(text(
        "SELECT review_item_id::text FROM review_item WHERE payload->>'new_fact_id' = :f"),
        {"f": proposed}).scalar_one()
    return current, proposed, item


def _pointer(session, world):
    return session.execute(text(
        "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE "
        "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND fact_key='funding_signal'"),
        {"a": world["actor"], "t": world["topic"]}).scalar_one()


def test_review_can_accept_the_new_value_and_both_facts_stay(session_factory, world):
    with session_factory() as session:
        current, proposed, item = _conflict(session, world, ghus=True)
        result = record_fact_review_decision(session, review_item_id=item, decided_by="Reviewer",
                                             accept=True, live=True)
        session.commit()
        assert result["action"] == "decided"
        assert _pointer(session, world) == proposed
        resolutions = dict(session.execute(text(
            "SELECT actor_fact_id::text, resolution FROM fact_resolution WHERE actor_fact_id "
            "IN (CAST(:a AS uuid), CAST(:b AS uuid)) AND decided_by='Reviewer'"),
            {"a": current, "b": proposed}).all())
        assert resolutions == {current: "superseded", proposed: "accepted"}
        assert _count(session, "SELECT status FROM review_item WHERE "
                               "review_item_id=CAST(:i AS uuid)", i=item) == "approved"
        again = record_fact_review_decision(session, review_item_id=item, decided_by="Reviewer",
                                            accept=False, live=True)
        assert again["action"] == "already_resolved"


def test_review_can_keep_the_current_value(session_factory, world):
    with session_factory() as session:
        current, proposed, item = _conflict(session, world)
        record_fact_review_decision(session, review_item_id=item, decided_by="Reviewer",
                                    accept=False, live=True)
        session.commit()
        assert _pointer(session, world) == current
        assert _count(session, "SELECT resolution FROM fact_resolution WHERE actor_fact_id="
                               "CAST(:f AS uuid) AND decided_by='Reviewer'", f=proposed) == "rejected"
        assert _count(session, "SELECT status FROM review_item WHERE "
                               "review_item_id=CAST(:i AS uuid)", i=item) == "rejected"


def test_review_can_keep_both_locations_and_only_locations(session_factory, world):
    """Keep both adds the proposed place as an additional location; never committed here.

    Rolled back at the end: the world actor is a real record of the test database,
    and an extra location would show on it everywhere.
    """
    past = datetime.now(UTC) - timedelta(days=10)
    with session_factory() as session:
        try:
            current = _seed(session, world, "location", {"city": "Austin", "state": "TX"},
                            when=past, confidence="high")
            proposed = _seed(session, world, "location",
                             {"city": "Dallas", "state": "TX", "country": "US"},
                             when=past - timedelta(days=5), confidence="low")
            item = session.execute(text(
                "SELECT review_item_id::text FROM review_item WHERE payload->>'new_fact_id' = :f"),
                {"f": proposed}).scalar_one()
            result = record_fact_review_decision(session, review_item_id=item,
                                                 decided_by="Reviewer", accept=False,
                                                 keep_both=True, live=True)
            assert result["decision"] == "keep_both" and result["action"] == "decided"
            assert result["added_location"]["state_code"] == "TX"
            pointer = session.execute(text(
                "SELECT actor_fact_id::text FROM actor_fact_current_pointer WHERE "
                "actor_id=CAST(:a AS uuid) AND topic_id=CAST(:t AS uuid) AND fact_key='location'"),
                {"a": world["actor"], "t": world["topic"]}).scalar_one()
            assert pointer == current                       # the current place stays current
            added = session.execute(text(
                "SELECT l.city, l.is_primary FROM actor_location l JOIN actor_fact f "
                "ON f.source_id = l.source_id WHERE f.actor_fact_id = CAST(:f AS uuid) "
                "AND l.actor_id = CAST(:a AS uuid)"), {"f": proposed, "a": world["actor"]}).one()
            assert (added.city, added.is_primary) == ("Dallas", False)
            assert _count(session, "SELECT status FROM review_item WHERE "
                                   "review_item_id=CAST(:i AS uuid)", i=item) == "approved"
            # Every other box holds one current value: keep both is refused there.
            _seed(session, world, "funding_signal", "$1M.", when=past, confidence="high")
            other = _seed(session, world, "funding_signal", "$3M.",
                          when=past - timedelta(days=5), confidence="low")
            other_item = session.execute(text(
                "SELECT review_item_id::text FROM review_item WHERE payload->>'new_fact_id' = :f"),
                {"f": other}).scalar_one()
            with pytest.raises(ValueError, match="only to locations"):
                record_fact_review_decision(session, review_item_id=other_item,
                                            decided_by="Reviewer", accept=False,
                                            keep_both=True, live=True)
        finally:
            session.rollback()


def test_review_refuses_to_accept_over_a_value_that_changed_since(session_factory, world):
    with session_factory() as session:
        _current, _proposed, item = _conflict(session, world)
        _seed(session, world, "funding_signal", "$9M.", when=datetime.now(UTC),
              confidence="high")
        session.commit()
        with pytest.raises(ValueError, match="changed after this review"):
            record_fact_review_decision(session, review_item_id=item, decided_by="Reviewer",
                                        accept=True, live=True)
        session.rollback()


# ---------------------------------------------------------- update requests
# Need migration 570 (applied to the local clone only).

def _has_570(session):
    from agents.collection import subscription_store as store

    return store.has_update_requests(session)


@pytest.fixture()
def three_actors(session_factory, world):
    with session_factory() as session:
        if not _has_570(session):
            pytest.skip("migration 570 is not applied to this test database")
        ids = session.execute(text(
            "SELECT actor_id::text FROM actor WHERE actor_category = 'company' "
            "AND website LIKE 'http%' ORDER BY actor_id LIMIT 3")).scalars().all()
    return ids


def _payload(world, ids, **changes):
    payload = {"actor_ids": ids, "topic": world["code"], "scope": "general",
               "cadence": "once", "max_actors_per_run": len(ids), "max_usd_per_run": 1.0}
    payload.update(changes)
    return payload


def _runner(session, subscription_id, tmp_path, reader, **kwargs):
    from agents.collection import subscription_runner as runner

    def update(session_, subscription, *, ledger, config):
        return au.run_request(session_, subscription, ledger=ledger, config=CONFIG,
                              reader_factory=_factory(reader, **kwargs), runs_dir=tmp_path)

    return runner.run_due_requests(session, live=True, request_id=subscription_id,
                                   config={"max_pages_fetched": 30, "max_usd_per_run": 5.0},
                                   runs_dir=tmp_path, update=update)


def test_a_request_plan_is_free_and_orders_actors_by_their_gaps(
        session_factory, world, three_actors, tmp_path):
    with session_factory() as session:
        # The first actor already has every box filled and fresh: it waits.
        for key in au.schema_fields("company"):
            _seed(session, {**world, "actor": three_actors[0]}, key, f"Recorded {key}.",
                  when=datetime.now(UTC))
        _seed(session, {**world, "actor": three_actors[1]}, "location", "Austin, TX",
              when=datetime.now(UTC))
        session.commit()
        before = _ledger(session)
        plan = au.plan_request(session, _payload(world, three_actors, scope="missing"),
                               config=CONFIG, runs_dir=tmp_path)
        assert _ledger(session) == before
    assert plan["can_save"] and plan["matched"] == 3
    assert [a["actor_id"] for a in plan["chosen"]] == [three_actors[2], three_actors[1]]
    assert plan["chosen"][0]["boxes"] > plan["chosen"][1]["boxes"]
    assert plan["waiting"][0]["actor_id"] == three_actors[0]
    assert "filled and fresh" in plan["waiting"][0]["reason"]
    assert plan["cost"]["per_actor_cap_usd"] == CONFIG["actor_updates"]["max_usd_per_actor"]
    assert plan["runs"] == 1 and "Review" in plan["summary"]


def test_a_saved_request_is_paused_resumed_and_cancelled(session_factory, world, three_actors):
    from agents.collection import subscription_store as store

    with session_factory() as session:
        made = au.create_request(session, _payload(world, three_actors, cadence="monthly",
                                                   end_date="2027-03-01"),
                                 config=CONFIG, live=True)
        listing = au.list_requests(session)
        listed = {r["subscription_id"]: r for r in listing["requests"]}
        request = listed[made["subscription_id"]]
        assert request["status"] == "active" and request["cadence"] == "monthly"
        # The world topic is inactive: the page counts this request, never lists it.
        assert request["test_sector"] is True
        assert isinstance(listing["one_time"], list)
        assert all(u["topic_name"] != world["code"] for u in listing["one_time"])
        assert request["update_options"]["scope"] == "general"
        assert float(request["max_usd_per_run"]) == 1.0
        assert len(request["actor_names"]) == 3
        for action, status in (("pause", "paused"), ("resume", "active"),
                               ("cancel", "cancelled")):
            assert store.change_status(session, made["subscription_id"], action,
                                       live=True).values["status"] == status
        with pytest.raises(Exception, match="cannot be resumed"):
            store.change_status(session, made["subscription_id"], "resume", live=True)


def test_the_runner_runs_a_due_update_request_and_records_one_run(
        session_factory, world, three_actors, tmp_path):
    with session_factory() as session:
        made = au.create_request(session, _payload(world, three_actors), config=CONFIG,
                                 live=True)
        report = _runner(session, made["subscription_id"], tmp_path, FakeReader(EVIDENCE))
        outcome = report.outcomes[0]
        assert outcome.kind == "actor_update" and outcome.status == "succeeded", outcome
        assert outcome.next_status == "expired"  # a one-time request is done
        run = session.execute(text(
            "SELECT r.job_name, r.status, r.spent_usd, r.trigger_type, r.initiated_by, "
            "r.config_snapshot->'actor_results' AS results, "
            "r.collection_request_id::text AS req "
            "FROM collection_run r WHERE r.collection_run_id = CAST(:id AS uuid)"),
            {"id": outcome.collection_run_id}).mappings().one()
        assert (run["job_name"], run["status"], run["trigger_type"], run["initiated_by"]) == (
            "actor_update_request", "succeeded", "subscription", "actor_updates")
        assert float(run["spent_usd"]) == pytest.approx(0.09)
        assert {r["actor_id"] for r in run["results"]} == set(three_actors)
        # Every fact the run wrote carries the request; the run is in the request history.
        assert _count(session, "SELECT count(DISTINCT actor_id) FROM actor_fact "
                               "WHERE request_id = CAST(:r AS uuid)", r=run["req"]) == 3
        requests = au.list_requests(session)["requests"]
        mine = next(r for r in requests if r["subscription_id"] == made["subscription_id"])
        assert mine["status"] == "expired" and len(mine["runs"]) == 1
        assert mine["runs"][0]["actor_results"]


def test_a_run_stops_at_its_spend_ceiling_and_says_who_waits(
        session_factory, world, three_actors, tmp_path):
    with session_factory() as session:
        made = au.create_request(session, _payload(world, three_actors, max_usd_per_run=0.05),
                                 config=CONFIG, live=True)
        report = _runner(session, made["subscription_id"], tmp_path, FakeReader(EVIDENCE))
        outcome = report.outcomes[0]
        assert outcome.status == "attention"
        assert "spend ceiling" in outcome.status_reason
        run = session.execute(text(
            "SELECT spent_usd, max_usd, status_reason, jsonb_array_length("
            "config_snapshot->'actor_results') AS reached FROM collection_run "
            "WHERE collection_run_id = CAST(:id AS uuid)"),
            {"id": outcome.collection_run_id}).mappings().one()
        assert run["reached"] == 2  # $0.03, then $0.03 against the $0.02 left
        # The true spend is recorded and the overshoot stated, never hidden.
        assert float(run["spent_usd"]) == pytest.approx(0.06)
        assert run["max_usd"] is None and "over the" in run["status_reason"]


def test_one_actor_failing_does_not_stop_the_run(session_factory, world, three_actors,
                                                 tmp_path):
    class OneSiteDown(FakeReader):
        down = ""

        def read(self, **kwargs):
            if kwargs["name"] == self.down:
                self.calls.append(kwargs)
                read = LightRead()
                read.error = "site could not be read: HTTPError: 403"
                return read
            return super().read(**kwargs)

    with session_factory() as session:
        names = dict(session.execute(text(
            "SELECT actor_id::text, name FROM actor "
            "WHERE actor_id = ANY(CAST(:ids AS uuid[]))"), {"ids": three_actors}).all())
        reader = OneSiteDown(EVIDENCE)
        reader.down = names[three_actors[1]]
        made = au.create_request(session, _payload(world, three_actors), config=CONFIG,
                                 live=True)
        outcome = _runner(session, made["subscription_id"], tmp_path, reader).outcomes[0]
        assert outcome.status == "attention"
        assert "1 actor(s) could not be updated" in outcome.status_reason
        assert outcome.counts["actors"] == 2


def test_the_plan_only_runner_lists_update_requests_and_writes_nothing(
        session_factory, world, three_actors, tmp_path):
    from agents.collection import subscription_runner as runner

    with session_factory() as session:
        made = au.create_request(session, _payload(world, three_actors), config=CONFIG,
                                 live=True)
        before = _ledger(session)
        report = runner.run_due_requests(session, live=False,
                                         request_id=made["subscription_id"],
                                         config={}, runs_dir=tmp_path)
        assert _ledger(session) == before
    outcome = report.outcomes[0]
    assert outcome.kind == "actor_update" and outcome.status == "planned"
    assert len(outcome.queries) == 3 and "box(es) to read" in outcome.queries[0]
    assert "Actors (3):" in runner.render_report(report)


def test_aggregate_placeholders_are_never_updated(session_factory, world, tmp_path):
    """AGENTS rule 5: aggregate stays out of agent outputs."""
    with session_factory() as session:
        aggregate = session.execute(text(
            "SELECT actor_id::text FROM actor WHERE COALESCE(NULLIF(to_jsonb(actor)->>'actor_category', ''), "
            "to_jsonb(actor)->>'actor_type') = 'aggregate' LIMIT 1")).scalar()
        if aggregate is None:
            pytest.skip("no aggregate row in this test database")
        plan = au.plan_update(session, actor_id=aggregate, topic_code=world["code"],
                              config=CONFIG, runs_dir=tmp_path)
        assert plan["ok"] is False and "aggregate" in plan["error"]
        sector = session.execute(text(
            "SELECT t.code FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id "
            "JOIN topic t ON t.topic_id = h.topic_id GROUP BY t.code "
            "ORDER BY count(*) DESC LIMIT 1")).scalar()
        if sector and _has_570(session):
            members = au.group_actors(session, sector=sector, category=None, state=None)
            categories = {m["actor_category"] for m in members}
            assert "aggregate" not in categories


# ------------------------------------------- related organisations and hubs (phase C)

class NamingClient:
    """Stands in for the model: names organisations it is told to."""

    def __init__(self, organisations):
        self.organisations = organisations

    def extract_with_tool(self, **kwargs):
        return {"organisations": self.organisations}


class ReaderWithClient(FakeReader):
    def __init__(self, evidence, organisations):
        super().__init__(evidence)
        self.client = NamingClient(organisations)


def test_named_organisations_are_routed_mapped_first_and_proposed_to_review(
        session_factory, world, tmp_path):
    from agents.enrichment.decisions import record_relationship_review_decision

    with session_factory() as session:
        other = session.execute(text(
            "SELECT actor_id::text, name FROM actor WHERE actor_id <> CAST(:a AS uuid) "
            "AND actor_category = 'research_center' AND name ~ '^[A-Za-z ]+$' "
            "AND merged_into_actor_id IS NULL "  # a merged record is not on the map
            # One no earlier run has linked or proposed, so each run starts clean.
            "AND NOT EXISTS (SELECT 1 FROM entity_edge e WHERE e.subject_id = CAST(:a AS uuid) "
            "  AND e.object_id = actor.actor_id) "
            "AND NOT EXISTS (SELECT 1 FROM review_item r WHERE r.review_kind = "
            "  'relationship_review' AND r.entity_id = CAST(:a AS uuid) "
            "  AND r.candidate_entity_id = actor.actor_id) "
            "ORDER BY actor_id LIMIT 1"), {"a": world["actor"]}).one()
        evidence = {**EVIDENCE,
                    "international_connection": f"Joint project with {other.name} and "
                                                "Nowhere Unmapped Institute."}
        reader = ReaderWithClient(evidence, [
            {"name": other.name, "box": "international_connection", "relation": "partner"},
            {"name": "Nowhere Unmapped Institute", "box": "international_connection",
             "relation": "partner"},
            {"name": "Invented Corp", "box": "international_connection", "relation": "partner"},
        ])
        check = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                scope="specific", fields=["international_connection"],
                                config=CONFIG, runs_dir=tmp_path,
                                reader_factory=_factory(reader))
        by_name = {r["name"]: r for r in check["related"]}
        assert set(by_name) == {other.name, "Nowhere Unmapped Institute"}  # invented one dropped
        assert by_name[other.name]["status"] == "on_map"
        assert by_name[other.name]["proposal"] == {
            "subject_actor_id": world["actor"], "object_actor_id": other.actor_id,
            "relationship_type": "collaborates_with"}
        assert by_name["Nowhere Unmapped Institute"]["status"] == "not_on_map"
        edges_before = _count(session, "SELECT count(*) FROM entity_edge")

        applied = au.apply_check(session, check["check_id"], runs_dir=tmp_path, config=CONFIG)
        proposal = next(p for p in applied["proposals"] if p["kind"] == "relationship")
        assert proposal["action"] == "proposed"
        # Proposed, not written: no edge until a person approves.
        assert _count(session, "SELECT count(*) FROM entity_edge") == edges_before
        item = session.execute(text(
            "SELECT review_kind, payload->>'source_url' AS url, candidate_entity_id::text AS other "
            "FROM review_item WHERE review_item_id = CAST(:i AS uuid)"),
            {"i": proposal["review_item_id"]}).mappings().one()
        assert (item["review_kind"], item["other"]) == ("relationship_review", other.actor_id)
        assert item["url"] == "https://co.example/about"

        # The same link found again is not proposed twice.
        again = au.check_update(session, actor_id=world["actor"], topic_code=world["code"],
                                scope="specific", fields=["international_connection"],
                                config=CONFIG, runs_dir=tmp_path,
                                reader_factory=_factory(reader))
        second = au.apply_check(session, again["check_id"], runs_dir=tmp_path, config=CONFIG)
        assert [p["action"] for p in second["proposals"] if p["kind"] == "relationship"] == [
            "already_proposed"]

        # A person approves, with the page as the source: now the edge exists.
        result = record_relationship_review_decision(
            session, review_item_id=proposal["review_item_id"], decided_by="Reviewer",
            approve=True, source_url=item["url"], live=True)
        session.commit()
        assert result["action"] == "approved"
        assert _count(session, "SELECT count(*) FROM entity_edge") == edges_before + 1


def _hub(session, world, *, name, lat, lon, radius=50):
    return session.execute(text(
        "INSERT INTO hub (hub_id, name, slug, topic_id, center_latitude, center_longitude, "
        "radius_miles, center_frozen, center_method, center_method_version, center_computed_at) "
        "VALUES (gen_random_uuid(), :n, :slug, CAST(:t AS uuid), :lat, :lon, :r, false, "
        "'test', 'test', now()) RETURNING hub_id::text"),
        {"n": f"{name} {uuid.uuid4().hex[:6]}",
         "slug": f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
         "t": world["topic"], "lat": lat, "lon": lon, "r": radius}).scalar_one()


def test_hub_fit_is_reported_proposed_to_review_and_never_removed(session_factory, world):
    from agents.collection import hub_reassessment
    from agents.enrichment.decisions import (
        propose_hub_membership,
        record_hub_membership_decision,
    )

    with session_factory() as session:
        actor = session.execute(text(
            "SELECT actor_id::text, CAST(latitude AS float) AS lat, CAST(longitude AS float) AS lon "
            "FROM actor WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
            "ORDER BY actor_id LIMIT 1")).one()
        near = _hub(session, world, name="Near test hub", lat=actor.lat + 0.1, lon=actor.lon)
        far = _hub(session, world, name="Far test hub", lat=-actor.lat, lon=actor.lon)
        # A GHUS membership in the far hub, which no longer fits.
        session.execute(text(
            "INSERT INTO hub_actor (hub_id, actor_id, relationship_type, is_primary, topic_id, "
            "assignment_outcome, overlap_flag) VALUES (CAST(:h AS uuid), CAST(:a AS uuid), "
            "'member', false, CAST(:t AS uuid), 'legacy_membership_preserved', false)"),
            {"h": far, "a": actor.actor_id, "t": world["topic"]})
        session.commit()

        report = hub_reassessment.assess(session, actor.actor_id, sector_codes=[world["code"]])
        far_member = next(m for m in report["memberships"] if m["hub_id"] == far)
        assert far_member["fit"] == "outside_radius" and far_member["preserved"]
        assert "never removed" in far_member["action"]
        # It already has a hub in this sector, so the near one is not proposed.
        assert report["proposals"] == []

        # Reporting never removed the membership that no longer fits.
        assert _count(session, "SELECT count(*) FROM hub_actor WHERE hub_id = CAST(:h AS uuid) "
                               "AND actor_id = CAST(:a AS uuid)", h=far, a=actor.actor_id) == 1

        # A proposal is accepted only by a person, and only then is it a membership.
        proposal = propose_hub_membership(session, actor_id=actor.actor_id, hub_id=near,
                                          distance_miles=6.9, radius_miles=50,
                                          sector_code=world["code"], live=True)
        session.commit()
        assert proposal["action"] == "proposed"
        assert propose_hub_membership(session, actor_id=actor.actor_id, hub_id=near,
                                      distance_miles=6.9, radius_miles=50,
                                      sector_code=world["code"])["action"] == "already_proposed"
        decided = record_hub_membership_decision(session, review_item_id=proposal["review_item_id"],
                                                 decided_by="Reviewer", accept=True, live=True)
        session.commit()
        assert decided["action"] == "decided"
        membership = session.execute(text(
            "SELECT relationship_type, assignment_outcome, source_id IS NOT NULL AS sourced "
            "FROM hub_actor WHERE hub_id = CAST(:h AS uuid) AND actor_id = CAST(:a AS uuid)"),
            {"h": near, "a": actor.actor_id}).one()
        assert tuple(membership) == ("reviewed_assignment", "assigned", True)


def test_an_unassigned_actor_stays_eligible_for_a_hub_added_later(session_factory, world):
    from agents.collection import hub_reassessment

    with session_factory() as session:
        actor = session.execute(text(
            "SELECT a.actor_id::text, CAST(a.latitude AS float) AS lat, "
            "CAST(a.longitude AS float) AS lon FROM actor a WHERE a.latitude IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM hub_actor ha WHERE ha.actor_id = a.actor_id) "
            "ORDER BY a.actor_id LIMIT 1")).one()
        before = hub_reassessment.assess(session, actor.actor_id, sector_codes=[world["code"]])
        assert before["unassigned"] and before["proposals"] == []
        assert "stays eligible" in before["note"]
        hub = _hub(session, world, name="Later test hub", lat=actor.lat, lon=actor.lon + 0.05)
        session.commit()
        after = hub_reassessment.assess(session, actor.actor_id, sector_codes=[world["code"]])
        assert [p["hub_id"] for p in after["proposals"]] == [hub]
        assert "Review" in after["proposals"][0]["action"]
        # Assessing never writes.
        assert _count(session, "SELECT count(*) FROM hub_actor WHERE actor_id = CAST(:a AS uuid)",
                      a=actor.actor_id) == 0


def test_a_found_location_fills_only_an_empty_record(session_factory):
    from agents.enrichment.decisions import fill_actor_location

    with session_factory() as session:
        located = session.execute(text(
            "SELECT actor_id::text FROM actor WHERE latitude IS NOT NULL LIMIT 1")).scalar_one()
        assert fill_actor_location(session, actor_id=located, city="Austin", state="TX",
                                   live=True)["action"] == "already_located"
        empty = session.execute(text(
            "SELECT actor_id::text FROM actor WHERE latitude IS NULL "
            "AND NULLIF(to_jsonb(actor)->>'state_code', '') IS NULL "
            "AND NULLIF(to_jsonb(actor)->>'state', '') IS NULL "
            "AND NULLIF(to_jsonb(actor)->>'location_city', '') IS NULL LIMIT 1")).scalar_one()
        assert fill_actor_location(session, actor_id=empty, city="Nowhereville", state="TX",
                                   live=True)["action"] == "not_in_gazetteer"
        result = fill_actor_location(session, actor_id=empty, city="Montpelier", state="VT",
                                     live=True)
        assert (result["action"], result["region_code"]) == ("located", "northeast")
        row = session.execute(text(
            "SELECT state_code, region_code, latitude IS NOT NULL FROM actor "
            "WHERE actor_id = CAST(:a AS uuid)"), {"a": empty}).one()
        assert tuple(row) == ("VT", "northeast", True)
        session.rollback()  # leave the clone as it was
