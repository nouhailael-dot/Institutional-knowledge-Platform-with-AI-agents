"""On-request Event and People discovery (migration 580), beside the automatic runs.

The request is the Discovery page's own (actor_update_subscription), run by the
same request runner; the pipeline is the automatic one, with the request's
scope added. These tests pin what changes and what must not:

* an organization request is exactly what it was (no new columns written);
* an event or people request carries only its own options, refused otherwise;
* queries come only from the request; nothing outside it is staged;
* Needs More Research reads one official page, bounded, then decides;
* every qualified event and person goes to Review - none is created.
"""

from __future__ import annotations

import uuid
from argparse import Namespace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from agents.collection import subscription_store as store
from agents.collection.subscriptions import Subscription, SubscriptionError
from agents.discovery.quality_gates import event_gate
from agents.discovery.search.discovery_request import (
    DiscoveryRequest,
    event_outside_request,
    person_outside_request,
    request_event_queries,
    request_person_queries,
)
from agents.discovery.search.followup import (
    FollowupBudget,
    event_followup_urls,
    merge_event_reads,
    pending_review_events,
    person_followup_urls,
    same_person,
)
from agents.discovery.sources.base import FetchedDoc

ROOT = Path(__file__).resolve().parents[2]
SECTORS = [{"code": "WATER", "name": "Water"}, {"code": "ENERGY", "name": "Energy"}]


def _request_sub(entity="event", **options) -> Subscription:
    return Subscription(
        subscription_id="req-1", start_date=date(2026, 11, 1), end_date=date(2027, 1, 31),
        cadence="once", requested_via="discovery_page", sector_codes=("WATER",),
        focus_terms=("water reuse",), region_code="midwest_great_lakes",
        title="Water reuse events", discovery_entity=entity, discovery_options=options)


# ----------------------------------------------------------------- the request

def test_an_organization_request_is_unchanged():
    sub = Subscription(subscription_id="a", start_date=date(2026, 11, 1),
                       end_date=date(2027, 1, 31), cadence="weekly",
                       requested_via="discovery_page", sector_codes=("WATER",))
    assert sub.discovery_entity == "actor" and sub.discovery_options == {}
    request = DiscoveryRequest.from_subscription(sub)
    assert request.entity == "actor"
    assert "entity" not in request.describe()          # the snapshot actors always had
    written = store.create_request(None, title="Water organizations", end_date=date(2027, 1, 31),
                                   cadence="weekly", sector_codes=["WATER"],
                                   start_date=date(2026, 11, 1))
    assert "discovery_entity" not in written.statement and "discovery_entity" not in written.values


def test_event_and_people_requests_carry_only_their_own_options():
    event = _request_sub("event", date_from="2027-03-01", date_to="2027-06-30",
                         event_types=["conference", "workshop"])
    request = DiscoveryRequest.from_subscription(event)
    assert (request.entity, request.date_from, request.date_to, request.event_types) == (
        "event", date(2027, 3, 1), date(2027, 6, 30), ("conference", "workshop"))
    person = DiscoveryRequest.from_subscription(
        _request_sub("person", institution="University of Michigan", role="professor"))
    assert (person.institution, person.role) == ("University of Michigan", "professor")

    with pytest.raises(SubscriptionError, match="unknown option"):
        _request_sub("event", institution="MIT")
    with pytest.raises(SubscriptionError, match="event types"):
        _request_sub("event", event_types=["party"])
    with pytest.raises(SubscriptionError, match="ends before it starts"):
        _request_sub("event", date_from="2027-06-30", date_to="2027-03-01")
    with pytest.raises(SubscriptionError, match="one of"):
        _request_sub("organisation")


def test_an_event_request_is_written_with_its_entity_and_options():
    written = store.create_request(
        None, title="Water reuse events", end_date=date(2027, 1, 31), cadence="once",
        sector_codes=["WATER"], start_date=date(2026, 11, 1), discovery_entity="event",
        discovery_options={"date_from": "2027-03-01", "event_types": ["conference"]})
    assert written.live is False
    assert ":discovery_entity" in written.statement
    assert written.values["discovery_entity"] == "event"
    assert '"event_types": ["conference"]' in written.values["discovery_options"]


def test_migration_580_is_additive_with_a_refusing_rollback():
    sql = (ROOT / "agents/sql/580_v2_event_people_requests.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS discovery_entity text NOT NULL DEFAULT 'actor'" in sql
    assert "DROP COLUMN" not in sql and "RENAME" not in sql
    rollback = (ROOT / "agents/sql/rollback/580_v2_event_people_requests.sql").read_text(
        encoding="utf-8")
    assert "rollback refused" in rollback


# ------------------------------------------------------------------- queries

def test_event_queries_come_only_from_the_request():
    request = DiscoveryRequest.from_subscription(_request_sub(
        "event", date_from="2027-03-01", date_to="2027-06-30", event_types=["workshop"]))
    queries, meta = request_event_queries(request, SECTORS, today=date(2026, 10, 23),
                                          max_queries=8)
    assert len(queries) == 8
    assert all("water reuse" in q and "2027" in q for q in queries)
    assert all("workshop" in q for q in queries)
    assert any("official site" in q for q in queries)          # official sources first
    assert "Michigan" in " ".join(queries)                      # the requested region
    assert meta["discovery_request"]["entity"] == "event"


def test_people_queries_aim_at_official_profiles_never_linkedin():
    request = DiscoveryRequest.from_subscription(
        _request_sub("person", institution="University of Michigan", role="professor"))
    queries, _ = request_person_queries(request, SECTORS, max_queries=10)
    assert queries and all("University of Michigan" in q for q in queries)
    assert any("profile" in q or "faculty" in q for q in queries)
    assert not any("linkedin" in q.lower() for q in queries)


def test_the_generator_uses_the_request_with_no_model_call():
    from agents.discovery.search.query_generation import QueryGenerator

    request = DiscoveryRequest.from_subscription(_request_sub("event"))
    bundle = QueryGenerator(None, {"people_enabled": True}, today=date(2026, 10, 23)).generate(
        "event", project_root=ROOT, request=request)
    assert bundle.llm_queries == [] and bundle.queries
    assert all("water reuse" in q for q in bundle.queries)


# --------------------------------------------------------------- request scope

def test_an_event_outside_the_requested_dates_or_area_is_excluded_unknown_is_not():
    request = DiscoveryRequest.from_subscription(
        _request_sub("event", date_from="2027-03-01", date_to="2027-06-30"))
    assert "before the requested dates" in event_outside_request(
        {"start_date": "2027-01-10"}, request)
    assert "after the requested dates" in event_outside_request(
        {"start_date": "2027-09-10"}, request)
    assert "outside the requested area" in event_outside_request(
        {"start_date": "2027-04-01", "state": "TX"}, request)
    assert event_outside_request({"start_date": "2027-04-01", "state": "MI"}, request) is None
    assert event_outside_request({"state": "TX", "facts": {"format": "online"}}, request) is None
    assert event_outside_request({}, request) is None          # unknown is the gate's job


def test_a_person_at_another_institution_is_excluded():
    request = DiscoveryRequest.from_subscription(
        _request_sub("person", institution="University of Michigan"))
    assert person_outside_request({"affiliation": "Michigan State University"}, request) \
        is not None
    assert person_outside_request({"affiliation": "University of Michigan, Ann Arbor"},
                                  request) is None
    assert person_outside_request({"affiliation": "Michigan Technological University"},
                                  request) is not None
    assert person_outside_request({}, request) is None


# ------------------------------------------------------- Needs More Research

def _official_event(**extra):
    return {"title": "Great Lakes Water Reuse Workshop 2027", "sector_codes": ["WATER"],
            "website": "https://reuse.example.org/workshop", **extra}


def _rubric(**flags):
    return {name: {"present": on, "evidence": "stated" if on else None}
            for name, on in {"single_discrete_event": True, "specific_ghus_topic": True,
                             **flags}.items()}


def test_an_official_event_without_date_or_place_needs_research_not_review():
    gate = event_gate(_official_event(), facts={}, page_url="https://reuse.example.org/workshop",
                      page_text="Great Lakes Water Reuse Workshop 2027", rubric=_rubric(),
                      run_date=date(2026, 10, 23))
    assert gate.decision == "research" and gate.outcome == "needs_research"
    assert "confirmed date" in gate.missing_mandatory


def test_the_follow_up_reads_the_agenda_page_and_fills_only_what_was_missing():
    html = ('<a href="/workshop/agenda">Agenda and venue</a> <a href="/news">News</a>'
            '<a href="https://linkedin.com/company/x">LinkedIn</a>')
    urls = event_followup_urls(_official_event(website=None),
                               "https://reuse.example.org/workshop", html)
    assert urls == ["https://reuse.example.org/workshop/agenda"]
    merged = merge_event_reads(
        _official_event(description="One day on reuse."),
        {"start_date": "2027-04-14", "city": "Ann Arbor", "description": "Other words",
         "facts": {"organizer": "Reuse Institute",
                   "evidence": {"organizer": {"quote": "Hosted by the Reuse Institute",
                                              "source_url": urls[0],
                                              "date_read": "2026-10-23"}}}},
        urls[0])
    assert merged["start_date"] == "2027-04-14" and merged["city"] == "Ann Arbor"
    assert merged["description"] == "One day on reuse."        # the first page wins
    assert merged["facts"]["evidence"]["organizer"]["source_url"] == urls[0]
    assert merged["followup"] == {"url": urls[0],
                                  "filled": ["city", "organizer", "start_date"]}
    gate = event_gate(merged, facts=merged["facts"], page_url="https://reuse.example.org/workshop",
                      page_text="Great Lakes Water Reuse Workshop 2027 Ann Arbor",
                      rubric=_rubric(), run_date=date(2026, 10, 23))
    assert gate.decision in ("accept", "review") and gate.outcome == "qualified"


def test_the_follow_up_is_bounded_and_never_reads_social_pages():
    budget = FollowupBudget(remaining=1)
    assert budget.take() is True and budget.take() is False
    assert person_followup_urls({"public_profile_url": "https://www.linkedin.com/in/x"},
                                "https://news.example.com/a") == []
    assert person_followup_urls({"public_profile_url": "https://umich.edu/people/lee"},
                                "https://news.example.com/a") == ["https://umich.edu/people/lee"]
    assert same_person("Dr. Ana Lee", "Ana Lee") and not same_person("Ana Lee", "Ana Park")


def test_the_event_follow_up_runs_through_the_extractor_once(tmp_path):
    from agents.common.cost import CostMeter
    from agents.common.raw_storage import RawContentStore
    from agents.common.run_log import InMemoryRunLog
    from agents.discovery.search import phase2
    from agents.discovery.search.event_scoring import EventPageAnalysis, EventRubricExtractor

    class AgendaExtractor(EventRubricExtractor):
        calls = 0

        def __init__(self):
            pass

        def extract(self, doc, **_):
            AgendaExtractor.calls += 1
            return EventPageAnalysis(rubric=_rubric(), record={
                "title": "Great Lakes Water Reuse Workshop 2027", "start_date": "2027-04-14",
                "city": "Ann Arbor", "sector_codes": ["WATER"]}, facts={})

    class Pages:
        fetched: list[str] = []

        def fetch(self, url):
            Pages.fetched.append(url)
            return FetchedDoc.from_content(url=url, content="<p>April 14, Ann Arbor</p>",
                                           content_type="text/html")

    doc = FetchedDoc.from_content(url="https://reuse.example.org/workshop",
                                  content='<a href="/workshop/venue">Venue</a>',
                                  content_type="text/html")
    stats = {"pages_fetched": 0}
    budget = FollowupBudget(remaining=1)
    found = phase2._event_followup(
        _official_event(website=None), doc.url, doc, budget=budget, source=Pages(),
        run_log=InMemoryRunLog(), raw_store=RawContentStore(tmp_path), run_id=str(uuid.uuid4()),
        rubric_extractor=AgendaExtractor(), sector_codes=["WATER"], hub_names=[],
        run_date=date(2026, 10, 23), stats=stats, cost_meter=CostMeter(max_usd=1))
    assert found is not None and found[1].record["city"] == "Ann Arbor"
    assert Pages.fetched == ["https://reuse.example.org/workshop/venue"]
    assert stats["followups_attempted"] == 1 and stats["followup_pages_fetched"] == 1
    # The allowance is spent: a second candidate is not followed up.
    assert phase2._event_followup(
        _official_event(website=None), doc.url, doc, budget=budget, source=Pages(),
        run_log=InMemoryRunLog(), raw_store=RawContentStore(tmp_path), run_id="r",
        rubric_extractor=AgendaExtractor(), sector_codes=["WATER"], hub_names=[],
        run_date=date(2026, 10, 23), stats=stats, cost_meter=CostMeter(max_usd=1)) is None
    assert AgendaExtractor.calls == 1


def test_reading_what_waits_in_review_never_breaks_a_session_without_the_queue():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    with Session(create_engine("sqlite://")) as session:
        session.execute(text("CREATE TABLE kept (x int)"))
        session.execute(text("INSERT INTO kept VALUES (1)"))
        assert pending_review_events(session) == []
        assert session.execute(text("SELECT count(*) FROM kept")).scalar() == 1


# ------------------------------------------------- everything goes to Review

def test_a_confident_new_person_is_proposed_in_review_never_created():
    from agents.discovery.stage import InMemoryStageStore
    from agents.discovery.normalize import normalize_person_record
    from agents.discovery.run import _extract_stage_route_promote
    from agents.discovery.search.person_scoring import PreExtractedPersonExtractor
    from agents.discovery.search.run import _empty_stats

    record = normalize_person_record({
        "name": "Dr. Amina Example", "affiliation": "Example Water Lab",
        "role": "Principal Investigator", "public_profile_url": "https://example.edu/amina",
        "research_area": "Membrane desalination"})
    stats = {**_empty_stats(), "records_extracted": 0, "records_staged": 0,
             "records_promoted": 0, "records_in_sector": 0, "records_out_of_sector": 0,
             "records_relevant": 0}
    audit: list[dict] = []
    stage_store = InMemoryStageStore()
    _extract_stage_route_promote(
        doc=FetchedDoc.from_content(url="https://example.edu/amina", content="<p>Amina</p>",
                                    content_type="text/html"),
        raw_document_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()),
        source_name="open_web_search", entity_type="person",
        extractor=PreExtractedPersonExtractor(record), stage_store=stage_store,
        session=None, live=False, candidates=[], root=ROOT, stats=stats, audit_rows=audit,
        people_enabled=True,
        person_affiliation_candidates=[{"actor_id": str(uuid.uuid4()),
                                        "affiliation": "Example Water Lab"}],
        person_review_metadata={"score_band": "auto_high", "rubric_score": 0.9,
                                "review_kind": "identity"})
    staged = next(iter(stage_store.rows.values()))
    assert staged.route["zone"] == "review"
    assert staged.route["metadata"]["proposed_zone"] == "create"
    assert staged.route["metadata"]["review_kind"] == "rubric_band"
    assert audit[-1]["status"] == "would_review"


def test_an_on_request_event_run_records_its_trigger_and_excludes_out_of_scope(
        monkeypatch, tmp_path):
    from agents.common.cost import CostMeter
    from agents.common.raw_storage import RawContentStore
    from agents.common.run_log import InMemoryRunLog
    from agents.discovery.search import run as search_run
    from agents.discovery.search.phase2 import InMemoryDiscoveredDomainStore
    from agents.discovery.stage import InMemoryStageStore
    from tests.agent.test_agents_open_web_phase2 import (
        AcceptingTriageClient,
        StaticEventExtractor,
        StaticFetchSource,
        StaticSearchProvider,
        _config,
        _search_result,
        _seeded_sector_code,
    )

    class RequestQueries:
        def generate(self, entity_type, *, session=None, project_root=None, request=None):
            from agents.discovery.search.query_generation import QueryBundle

            assert request is not None and request.entity == "event"
            return QueryBundle(entity_type=entity_type, queries=["water reuse workshop 2027"],
                               deterministic_queries=["water reuse workshop 2027"],
                               llm_queries=[], reference_count=0)

    config = _config(max_pages_fetched=30, max_new_domains=10)
    monkeypatch.setattr(search_run, "load_sources_config", lambda _root: config)
    sector = _seeded_sector_code()

    def run(date_to):
        request = DiscoveryRequest(subscription_id="r1", title="Reuse events",
                                   sector_codes=(sector,), entity="event",
                                   date_from=date(2027, 1, 1), date_to=date_to)
        stage_store = InMemoryStageStore()
        result = search_run.run_search_triage(
            Namespace(entity="event", live=False, offline=True, discovery_request=request,
                      report_out=str(tmp_path / "r.md"), audit_out=str(tmp_path / "a.csv")),
            root=ROOT, run_log=InMemoryRunLog(), store=search_run.InMemorySearchCandidateStore(),
            search_provider=StaticSearchProvider(
                [_search_result(f"https://events.example/reuse-{date_to.month}")]),
            query_generator=RequestQueries(), triage_client=AcceptingTriageClient(),
            cost_meter=CostMeter(max_usd=5), fetch_source=StaticFetchSource(),
            extractor=StaticEventExtractor(sector), raw_store=RawContentStore(tmp_path / "raw"),
            stage_store=stage_store, domain_store=InMemoryDiscoveredDomainStore(),
            event_candidates=[])
        return result, stage_store

    # The page's event is on 2027-03-10.
    outside, staged_outside = run(date(2027, 2, 1))
    assert outside["stats"]["run_trigger"] == "on_request"
    assert outside["stats"]["discovery_request_scope"]["entity"] == "event"
    assert not staged_outside.rows
    assert any("outside the request" in (c.triage_reason or "") for c in outside["candidates"])

    inside, staged_inside = run(date(2027, 6, 30))
    assert len(staged_inside.rows) == 1
    assert next(iter(staged_inside.rows.values())).route["zone"] == "review"
    assert inside["stats"]["records_promoted"] == 0      # nothing created on the map


def test_a_page_read_by_a_failed_run_is_read_again_not_skipped_as_unchanged():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from agents.discovery.search.phase2 import _read_by_failed_run

    with Session(create_engine("sqlite://")) as session:
        session.execute(text(
            "CREATE TABLE scrape_run (run_id text, status text, status_reason text)"))
        session.execute(text(
            "INSERT INTO scrape_run VALUES ('r-failed', 'failed', 'Connection error.'), "
            "('r-ok', 'succeeded', NULL), "
            "('r-capped', 'attention', 'max_usd_per_run cap hit: agent run cost $3.01')"))
        assert _read_by_failed_run(session, {"run_id": "r-failed"}) is True
        assert _read_by_failed_run(session, {"run_id": "r-capped"}) is True
        assert _read_by_failed_run(session, {"run_id": "r-ok"}) is False
        assert _read_by_failed_run(None, {"run_id": "r-failed"}) is False
    with Session(create_engine("sqlite://")) as session:           # no run ledger at all
        assert _read_by_failed_run(session, {"run_id": "r-failed"}) is False



def test_a_repeated_search_is_answered_from_disk_within_the_ttl_only(tmp_path):
    from datetime import timedelta

    from agents.discovery.search.models import SearchResult
    from agents.discovery.search.search_cache import CachedSearchProvider

    class Paid:
        name = "claude_web_search"
        calls = 0

        def search(self, query, count=10):
            Paid.calls += 1
            return [SearchResult(url=f"https://e.example/{Paid.calls}", title="t", snippet="s",
                                 provider="claude", query=query)]

    clock = {"now": datetime(2026, 10, 23, 12, tzinfo=UTC)}
    stats: dict = {}
    cached = CachedSearchProvider(Paid(), tmp_path, ttl_hours=72, stats=stats,
                                  now=lambda: clock["now"])
    first = cached.search("water reuse conference 2027", count=10)
    again = cached.search("Water  reuse conference 2027", count=10)      # same query
    assert again == first and Paid.calls == 1 and stats["searches_from_cache"] == 1
    cached.search("water reuse conference 2027", count=5)                # another count
    assert Paid.calls == 2
    clock["now"] += timedelta(days=7)                                     # the next weekly run
    fresh = cached.search("water reuse conference 2027", count=10)
    assert Paid.calls == 3 and fresh[0].url == "https://e.example/3"


def test_the_analysis_cache_is_keyed_by_address_and_readable_text(tmp_path):
    from agents.common.raw_storage import RawContentStore
    from agents.discovery.search.phase2 import _text_cache_path

    store = RawContentStore(tmp_path)
    page = "<main><h1>Reuse Summit 2027</h1><p>April 14, Ann Arbor</p></main>"
    a = FetchedDoc.from_content(url="https://r.example/summit", content_type="text/html",
                                content=f"<html><script>n='a1'</script>{page}</html>")
    b = FetchedDoc.from_content(url="https://r.example/summit", content_type="text/html",
                                content=f"<html><script>n='zz'</script>{page}</html>")
    other = FetchedDoc.from_content(url="https://r.example/other", content_type="text/html",
                                    content=a.content)
    assert a.content_hash != b.content_hash                    # the HTML changed ...
    assert _text_cache_path(store, "event_analysis", a, "v5") == \
        _text_cache_path(store, "event_analysis", b, "v5")    # ... the model's input did not
    assert _text_cache_path(store, "event_analysis", a, "v5") != \
        _text_cache_path(store, "event_analysis", other, "v5")


def test_the_automatic_event_run_has_its_own_lower_ceiling():
    from agents.common.config import load_sources_config

    config = load_sources_config(ROOT)["open_web_discovery"]
    assert config["event_max_usd_per_run"] == 3.00
    assert config["max_usd_per_run"] == 5.00                   # actors and people unchanged
    assert config["request_max_usd_per_run"] == 3.00           # a requested run finishes
    assert config["search_cache_ttl_hours"] < 7 * 24           # never spans a weekly run


def test_an_unsure_affiliation_never_writes_an_organization_as_the_matched_person(monkeypatch):
    """First live people run, 2026-10-23: the organization id reached
    person_review_queue.candidate_person_id and the foreign key refused the run."""
    from agents.common.resolve_route import RouteDecision
    from agents.discovery import run as discovery_run
    from agents.discovery.normalize import normalize_person_record
    from agents.discovery.search.person_scoring import PreExtractedPersonExtractor
    from agents.discovery.search.run import _empty_stats
    from agents.discovery.stage import InMemoryStageStore

    monkeypatch.setattr(discovery_run, "route_person", lambda *a, **k: RouteDecision(
        zone="review", score=0.85, target_entity_id="actor-ut-austin",
        candidate_ids=["actor-ut-austin", "actor-ut-arlington"],
        metadata={"identity_outcome": "ambiguous_affiliation"}))
    stage_store = InMemoryStageStore()
    stats = {**_empty_stats(), "records_extracted": 0, "records_staged": 0,
             "records_promoted": 0, "records_in_sector": 0, "records_out_of_sector": 0,
             "records_relevant": 0}
    discovery_run._extract_stage_route_promote(
        doc=FetchedDoc.from_content(url="https://uta.example.edu/madani", content="<p>x</p>",
                                    content_type="text/html"),
        raw_document_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()),
        source_name="open_web_search", entity_type="person",
        extractor=PreExtractedPersonExtractor(normalize_person_record({
            "name": "Ramtin Madani", "affiliation": "The University of Texas at Arlington",
            "role": "Professor", "public_profile_url": "https://uta.example.edu/madani",
            "research_area": "power systems"})),
        stage_store=stage_store, session=None, live=False,
        candidates=[{"person_id": "p-held", "full_name": "Someone Else"}], root=ROOT,
        stats=stats, audit_rows=[], people_enabled=True,
        person_review_metadata={"score_band": "auto_high", "rubric_score": 0.85,
                                "review_kind": "identity"})
    route = next(iter(stage_store.rows.values())).route
    assert route["zone"] == "review" and route["target_entity_id"] is None
    assert route["metadata"]["affiliation_candidate_actor_id"] == "actor-ut-austin"


# ------------------------------------------------------- United States only

def test_searches_and_results_outside_the_united_states_are_dropped_before_any_spend():
    from agents.discovery.search.us_scope import result_outside_us, us_places, us_queries

    # The automatic run of 2026-10-23 searched for these.
    kept, dropped = us_queries([
        "World Food Forum Rome 2026", "mining investment conference Southeast Asia 2026",
        "Global Framework on Chemicals conference Geneva 2026",
        "water reuse conference United States 2027", "Haiti Tech Summit UNGA Week 2026"])
    assert kept == ["water reuse conference United States 2027",
                    "Haiti Tech Summit UNGA Week 2026"]
    assert len(dropped) == 3
    assert us_places(["Rome, Italy", "New York, NY", "Online"]) == ["New York, NY", "Online"]

    assert "Rome" in result_outside_us("https://fao.org/wff", "World Food Forum Rome 2026", "")
    assert ".uk" in result_outside_us("https://water.co.uk/summit", "Water Summit 2027", "")
    assert result_outside_us("https://latam.org", "Latin American water conference",
                             "in Bogota") is not None
    # A US place wins; an online event has no place to be abroad.
    assert result_outside_us("https://aef.com", "Africa Energy Forum", "Houston, Texas") is None
    assert result_outside_us("https://x.org", "Paris Agreement summit", "Denver utilities") is None
    assert result_outside_us("https://nm.org", "New Mexico water summit", "") is None
    assert result_outside_us("https://w.org", "Reuse webinar from London", "online") is None


def test_the_automatic_event_queries_never_name_a_foreign_place():
    from agents.discovery.search.query_generation import _event_seed_queries

    queries = _event_seed_queries([{"code": "WATER", "name": "Water"}], [], date(2026, 10, 24),
                                  {"forward_window_days": 365})
    assert not any("global" in q for q in queries)
    assert any("United States" in q for q in queries)


# ------------------------------------------------- people: complete profiles only

def test_people_searches_are_limited_to_the_official_sites_of_held_institutions():
    from agents.discovery.search.people_targets import profile_queries

    domains = ["tamu.edu", "rice.edu", "utexas.edu", "uh.edu", "lbl.gov", "ornl.gov", "ercot.com"]
    queries, where = profile_queries(["battery storage", "grid energy storage"], domains,
                                     role="professor", max_queries=6)
    assert len(queries) == 4 and len(set(queries)) == 4          # every search is distinct
    assert where[queries[0]] == domains[:6] and where[queries[-1]] == ["ercot.com"]
    # Five sites fit in one search per topic.
    assert len(profile_queries(["battery storage"], domains[:5], role=None)[0]) == 1
    assert all("linkedin" not in q for q in queries)


def test_only_a_persons_own_profile_page_is_read():
    from agents.discovery.search.people_targets import profile_page_kind

    for url in ("https://www.ece.utexas.edu/people/faculty/hao-zhu",
                "https://che.utexas.edu/faculty/delia-milliron/",
                "https://engineering.tamu.edu/mechanical/profiles/jsmith.html",
                "https://vivo.library.tamu.edu/vivo/display/n123", "https://www.rice.edu/~jdoe"):
        assert profile_page_kind(url) == "profile", url
    for url in ("https://batteries.engr.utexas.edu/people", "https://energystoragera.org/leadership"):
        assert profile_page_kind(url) == "directory", url
    for url in ("https://news.utdallas.edu/faculty-staff/babu-chalamala-2026",
                "https://stories.tamu.edu/expert/jodie-lutkenhaus",
                "https://sites.utexas.edu/energy-week/archive/utew-2017/2017-speakers",
                "https://www.epa.gov/system/files/documents/report.pdf",
                "https://energy.utexas.edu/news/battery-breakthrough"):
        assert profile_page_kind(url) == "other", url


def test_a_directory_yields_the_profiles_of_the_people_listed_on_the_topic():
    from agents.discovery.search.people_targets import directory_leads

    html = """<ul>
      <li><a href="/people/jane-doe">Jane Doe</a> Professor. Battery storage and grid energy.</li>
      <li><a href="/people/omar-haddad">Omar Haddad</a> Professor. Fluid mechanics.</li>
      <li><a href="/news">News</a> <a href="https://other.edu/people/x-y">Xavier Young</a> battery</li>
      <li><a href="/people/ana-lee">Ana Lee</a> Associate Professor. Lithium battery materials.</li>
    </ul>"""
    leads = directory_leads(html, "https://batteries.engr.utexas.edu/people",
                            ["battery storage"], limit=5)
    assert [l["name"] for l in leads] == ["Jane Doe", "Ana Lee"]
    assert leads[0]["url"] == "https://batteries.engr.utexas.edu/people/jane-doe"


def test_a_linkedin_profile_is_taken_from_a_search_result_only_when_it_matches():
    from agents.discovery.search.models import SearchResult
    from agents.discovery.search.people_targets import linkedin_match

    def r(url, title):
        return SearchResult(url=url, title=title, snippet="", provider="claude", query="q")

    good = r("https://www.linkedin.com/in/donald-siegel-1a2b?trk=x",
             "Donald Siegel - Professor - The University of Texas at Austin | LinkedIn")
    assert linkedin_match([good], "Donald Siegel", "The University of Texas at Austin") == {
        "url": "https://www.linkedin.com/in/donald-siegel-1a2b", "title": good.title}
    other_org = r("https://www.linkedin.com/in/donald-siegel-99", "Donald Siegel - Dentist - Smile Co")
    assert linkedin_match([other_org], "Donald Siegel", "The University of Texas at Austin") is None
    company = r("https://www.linkedin.com/company/utaustin", "Donald Siegel at UT Austin")
    assert linkedin_match([company], "Donald Siegel", "University of Texas at Austin") is None
    twin = r("https://www.linkedin.com/in/donald-siegel-2",
             "Donald Siegel - Researcher - University of Texas at Austin")
    assert linkedin_match([good, twin], "Donald Siegel", "University of Texas at Austin") is None


def test_a_person_needs_a_bio_or_a_linkedin_to_be_complete():
    from agents.discovery.quality_gates import person_gate

    record = {"name": "Jane Doe", "affiliation": "Example University", "role": "Professor",
              "research_area": "battery storage", "public_profile_url": "https://ex.edu/jane"}
    page = "Jane Doe, Professor, Example University. Jane Doe studies battery storage."
    rubric = {"institution_or_self_published": {"present": True},
              "sector_intersection": {"present": True}}
    without = person_gate(record, facts={}, page_url="https://ex.edu/people/jane-doe",
                          page_text=page, rubric=rubric)
    assert without.decision == "research" and without.missing_mandatory == ["bio or LinkedIn"] \
        or tuple(without.missing_mandatory) == ("bio or LinkedIn",)
    with_bio = person_gate(record, facts={"bio": "Jane Doe studies battery storage."},
                           page_url="https://ex.edu/people/jane-doe", page_text=page, rubric=rubric)
    assert with_bio.decision == "accept" and with_bio.completeness == "complete"
    with_linkedin = person_gate(record, facts={"linkedin_url": "https://www.linkedin.com/in/jane"},
                                page_url="https://ex.edu/people/jane-doe", page_text=page,
                                rubric=rubric)
    assert with_linkedin.decision == "accept"


def test_a_bio_is_kept_only_when_its_text_is_on_the_page():
    from agents.discovery.page_facts import PERSON_FACT_FIELDS, verify_facts

    html = "<main><p>Jane Doe leads the grid storage lab and studies sodium-ion batteries.</p></main>"
    kept = verify_facts({"bio": "Jane Doe leads the grid storage lab and studies sodium-ion batteries."},
                        html=html, source_url="https://ex.edu/jane",
                        read_at=datetime(2026, 10, 25, tzinfo=UTC), fields=PERSON_FACT_FIELDS)
    assert kept["bio"].startswith("Jane Doe leads") and "dropped" not in kept
    invented = verify_facts({"bio": "Jane Doe won the Nobel Prize in chemistry in 2019 for her work."},
                            html=html, source_url="https://ex.edu/jane",
                            read_at=datetime(2026, 10, 25, tzinfo=UTC), fields=PERSON_FACT_FIELDS)
    assert "bio" not in invented and invented["dropped"] == ["bio"]




def test_view_bio_links_institutions_and_own_sites_are_understood():
    """The Battery Research Group lists 30 people behind "View Bio" links (2026-10-25)."""
    from agents.discovery.search.followup import person_followup_urls
    from agents.discovery.search.people_targets import directory_leads, institution_of

    card = """<div class="row">
      <div class="card"><h3>Arumugam Manthiram</h3><p>Professor, Mechanical Engineering</p>
        <p>Battery research area: new materials development</p>
        <a href="https://www.me.utexas.edu/people/faculty-directory/manthiram">View Bio</a></div>
      <div class="card"><h3>Omar Haddad</h3><p>Professor</p><p>Fluid mechanics</p>
        <a href="https://www.me.utexas.edu/people/faculty-directory/haddad">View Bio</a></div>
    </div>"""
    leads = directory_leads(card, "https://batteries.engr.utexas.edu/people", ["battery storage"])
    assert [(l["name"], l["url"]) for l in leads] == [
        ("Arumugam Manthiram", "https://www.me.utexas.edu/people/faculty-directory/manthiram")]
    assert institution_of("University of Houston Department of Electrical and Computer Engineering") \
        == "University of Houston"
    assert institution_of("Office of Energy Storage, Example Department of Energy") \
        == "Example Department of Energy"
    assert person_followup_urls(
        {}, "https://www.ece.uh.edu/faculty/canepa-pieremanuele",
        '<a href="https://twitter.com/x">Website</a><a href="https://caneparesearch.org">Website</a>'
    ) == ["https://caneparesearch.org"]


def test_an_unchanged_page_is_skipped_only_when_it_was_staged_before():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from agents.discovery.search.phase2 import _staged_before

    with Session(create_engine("sqlite://")) as session:
        session.execute(text("CREATE TABLE scrape_run (run_id text, status text, status_reason text)"))
        session.execute(text("CREATE TABLE staged_record (source_url text)"))
        session.execute(text("INSERT INTO scrape_run VALUES ('r1', 'attention', NULL)"))
        session.execute(text("INSERT INTO staged_record VALUES ('https://ex.edu/people/staged')"))
        assert _staged_before(session, {"run_id": "r1", "url": "https://ex.edu/people/staged"})
        # Read before, excluded under older rules: decided again today.
        assert not _staged_before(session, {"run_id": "r1", "url": "https://ex.edu/people/excluded"})
    assert _staged_before(None, {"run_id": "r1", "url": "https://ex.edu/x"})   # no database


def test_a_persons_own_scholar_link_is_not_another_person_and_their_lab_is_kept():
    from agents.discovery.search.followup import person_key
    from agents.discovery.search.people_targets import directory_leads

    html = """<div class="list">
      <div class="faculty-info"><a href="/faculty/shan">Dr. Xiaonan Shan</a> Associate Professor.
        Research: battery materials. <a href="https://scholar.google.com/citations?user=x">Scholar</a></div>
      <div class="faculty-info"><a href="/faculty/pan">Dr. Mia Pan</a> Professor. Optics.</div>
      <div class="faculty-info"><a href="/faculty/zhao">Dr. Lihong Zhao</a> Battery storage.
        <a href="https://sites.example.edu/zhao-lab/">View Research Group</a></div>
    </div>"""
    leads = directory_leads(html, "https://www.ece.uh.edu/faculty", ["battery storage"])
    assert [l["name"] for l in leads] == ["Dr. Lihong Zhao", "Dr. Xiaonan Shan"]
    assert leads[0]["own_site"] == "https://sites.example.edu/zhao-lab/"
    assert person_key("Dr. Donald J. Siegel") == person_key("Donald Siegel") == "name:donald siegel"


def test_every_theme_and_event_type_pair_is_searched():
    request = DiscoveryRequest(subscription_id="r", title="t", sector_codes=("WATER",),
                               focus_terms=("water reuse", "desalination"), entity="event",
                               event_types=("conference", "summit"))
    queries, _ = request_event_queries(request, SECTORS, today=date(2026, 10, 25), max_queries=16)
    grid = [q for q in queries if "official site" not in q]
    assert {(t, k) for t in ("water reuse", "desalination") for k in ("conference", "summit")} == {
        (t, k) for q in grid for t in ("water reuse", "desalination") for k in ("conference", "summit")
        if q.startswith(f"{t} {k} ")}


def test_a_website_with_text_after_it_still_gives_a_clean_search_domain():
    """Live run, 2026-10-30: "arizona.edu College of ..." stopped the whole search."""
    from agents.discovery.search.people_targets import registrable

    assert registrable("arizona.edu College of Engineering") == "arizona.edu"
    assert registrable("//arizona.edu College of Engineering") == "arizona.edu"
    assert registrable("https://www.nrel.gov DOE National Laboratories: https://x.gov") == "nrel.gov"
    assert registrable("https://www.asu.edu/research") == "asu.edu"
    assert registrable("") == ""
