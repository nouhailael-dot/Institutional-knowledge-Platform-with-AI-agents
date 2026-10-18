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
    assert "no web search" in plan["pages"]
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
    assert plan["deep"]["permitted"]
    # Permitted, but there is no Deep Pull reader yet: said, not faked.
    assert not plan["can_check"] and "no Deep Pull reader" in plan["refusal"]


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

