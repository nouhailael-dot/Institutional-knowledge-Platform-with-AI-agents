"""2026-10-15: cheaper reading, more actors, current organisations only.

Each test is tied to something measured on the October 14 run.
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from agents.common.cost import CostMeter
from agents.common.raw_storage import RawContentStore
from agents.common.run_log import InMemoryRunLog
from agents.discovery.search.actor_currency import (
    DEFUNCT,
    MERGED,
    OUTDATED_SOURCE,
    STALE_OWN_SITE,
    assess_currency,
    defunct_statement,
    newest_year,
)
from agents.discovery.search.actor_official import (
    about_link,
    harvest_leads,
    official_bundle,
    site_is_official,
)
from agents.discovery.search.actor_quality import (
    ACCEPT,
    REJECT,
    REVIEW,
    QualityConfig,
    assess_actor,
)
from agents.discovery.search.actor_scoring import (
    ActorPageAnalysis,
    coerce_rubric_payload,
    score_actor_rubric,
)
from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.phase2 import InMemoryDiscoveredDomainStore, fetch_score_stage_actors
from agents.discovery.search.run import _empty_stats, load_open_web_config
from agents.discovery.search.triage import actor_document_rejection
from agents.discovery.sources.base import FetchedDoc
from tests.agent.test_agents_actor_rubric_pipeline import (
    _canonical_record,
    _empty_rubric,
    _rubric_with_all_evidence,
)

TODAY = date(2026, 10, 14)
CONFIG = load_open_web_config()


# ------------------------------------------------------------ currency (free)

def test_a_site_that_now_redirects_elsewhere_marks_a_merger():
    finding = assess_currency(
        name="Central Vermont Public Service", page_text="", page_url="https://cvps.com",
        stated_website="https://cvps.com", official_final_url="https://greenmountainpower.com/",
        on_own_site=True, today=TODAY)
    assert finding.code == MERGED and finding.rejects
    assert "cvps.com now redirects to greenmountainpower.com" in finding.reason


def test_old_evidence_on_someone_elses_page_is_not_a_current_organisation():
    """CVPS reached Review on 2026-10-14 from a 2009 SEC filing."""
    finding = assess_currency(
        name="Central Vermont Public Service",
        page_text="Pilot projects in Rutland beginning in 2011. Filed 2009.",
        page_url="https://www.sec.gov/Archives/x.htm", stated_website=None,
        official_final_url=None, on_own_site=False, today=TODAY)
    assert finding.code == OUTDATED_SOURCE and finding.rejects
    assert "2011" in finding.reason


def test_a_stale_own_site_is_held_for_a_person_not_rejected():
    finding = assess_currency(
        name="Quiet Lab", page_text="Quiet Lab research. (c) 2019", page_url="https://quiet.example",
        stated_website="https://quiet.example", official_final_url=None, on_own_site=True,
        today=TODAY)
    assert finding.code == STALE_OWN_SITE and not finding.rejects


def test_a_defunct_statement_must_be_about_this_organisation():
    assert defunct_statement("Our client Acme was acquired by Siemens in 2020.", "CPower Energy") is None
    sentence = defunct_statement("In 2012 CVPS merged with Green Mountain Power.",
                                 "Central Vermont Public Service")
    assert sentence and "CVPS" in sentence
    finding = assess_currency(
        name="Northwind Grid", page_text="Northwind Grid has ceased operations as of May.",
        page_url="https://northwind.example", stated_website="https://northwind.example",
        official_final_url=None, on_own_site=True, today=TODAY)
    assert finding.code == DEFUNCT and finding.rejects


def test_a_current_page_raises_nothing():
    assert assess_currency(
        name="Urban Future Lab", page_text="Urban Future Lab programs. (c) 2026",
        page_url="https://ufl.nyc", stated_website="https://ufl.nyc",
        official_final_url="https://www.ufl.nyc/", on_own_site=True, today=TODAY) is None


def test_years_are_read_safely():
    assert newest_year("began in 2011. Filed 2009.", today=TODAY) == 2011
    assert newest_year("version 2025.1 and 12020 and 2031", today=TODAY) is None


# ----------------------------------------- relevance and priority are separate

def _scored(rubric, record=None):
    return score_actor_rubric(rubric, existing_actor_count=0, config=CONFIG,
                              record=record or {"website": "https://x.example", "state": "VT"})


def test_relevance_rewards_activity_not_engagement_signals():
    """A hobby club with field trips (use cases, open programmes) but no research
    or partnerships is not an innovation actor - replayed, the first relevance
    draft scored it like a research lab."""
    club = copy.deepcopy(_rubric_with_all_evidence())
    for key in ("research_development_or_programmes", "partnerships_or_tech_transfer"):
        club[key] = {"present": False, "evidence": None}
    lab = _rubric_with_all_evidence()
    assert _scored(club).total == pytest.approx(0.60)
    assert _scored(lab).total == pytest.approx(1.0)
    assert _scored(club).priority > 0.5        # engaging, but not relevant enough to verify


def test_priority_never_excludes_but_unseen_verification_needs_it():
    lab = _rubric_with_all_evidence()
    record = {**_canonical_record("Grid Lab"), "website": "https://grid-lab.example",
              "state": "VT",
              "description": "Grid Lab is a research centre in Vermont. It tests battery storage."}
    verdict = assess_actor(score=0.95, page_url="https://grid-lab.example/about", record=record,
                           rubric=lab, config=QualityConfig(), priority=0.40)
    assert verdict.band == REVIEW
    assert "below_auto_verify_priority" in verdict.gates_failed
    verdict = assess_actor(score=0.95, page_url="https://grid-lab.example/about", record=record,
                           rubric=lab, config=QualityConfig(), priority=0.80)
    assert verdict.band == ACCEPT
    low = assess_actor(score=0.50, page_url="https://grid-lab.example/about", record=record,
                       rubric=lab, config=QualityConfig(), priority=0.0)
    assert low.band == REVIEW               # relevant, low priority: kept, not rejected


def test_use_cases_count_as_concrete_work():
    """CPower was held for 'no concrete programmes' with two evidenced use cases."""
    rubric = _empty_rubric()
    rubric["use_cases"]["corporate_engagement"] = {"present": True, "evidence": "Works with C&I owners."}
    verdict = assess_actor(score=0.5, page_url="https://c.example", record={"name": "C"},
                           rubric=rubric, config=QualityConfig())
    assert "no_substantive_work" not in verdict.gates_failed


def test_a_merged_organisation_is_rejected_whatever_it_scores():
    finding = assess_currency(name="CVPS", page_text="", page_url="https://cvps.com",
                              stated_website="https://cvps.com",
                              official_final_url="https://greenmountainpower.com",
                              on_own_site=True, today=TODAY)
    verdict = assess_actor(score=0.99, page_url="https://cvps.com", record={"name": "CVPS"},
                           rubric=_rubric_with_all_evidence(), config=QualityConfig(),
                           currency=finding, priority=0.9)
    assert verdict.band == REJECT and MERGED in verdict.gates_failed


# --------------------------------------------- retrieval fixes from the audit

def test_a_4xx_robots_file_is_unavailable_not_a_refusal(monkeypatch):
    """RFC 9309: NYSERDA, UMass, Eversource... answered robots.txt with 403."""
    from agents.discovery.sources.http_utils import RobotsAwareHttp

    class Response:
        def __init__(self, code):
            self.status_code, self.text = code, ""

        def raise_for_status(self):
            raise RuntimeError(f"HTTP {self.status_code}")

    http = RobotsAwareHttp({"contact_email": "x@example.org"})
    monkeypatch.setattr(http, "_robots_response", lambda url: Response(403))
    assert http.robots_allowed("https://www.nyserda.ny.gov/programs") is True
    http2 = RobotsAwareHttp({"contact_email": "x@example.org"})
    monkeypatch.setattr(http2, "_robots_response", lambda url: Response(429))
    with pytest.raises(RuntimeError, match="429"):
        http2.robots_allowed("https://busy.example/")


def test_a_rubric_returned_as_json_strings_is_recovered():
    payload = {"rubric": '{"own_organisational_page": {"present": true}}', "record": '{"name": "X"}'}
    fixed = coerce_rubric_payload(payload)
    assert fixed["rubric"]["own_organisational_page"]["present"] is True
    assert fixed["record"]["name"] == "X"
    assert coerce_rubric_payload({"rubric": "not json", "record": {}})["rubric"] == "not json"


@pytest.mark.parametrize(("url", "rejected"), [
    ("https://ripuc.ri.gov/sites/g/files/x/testimony.pdf", True),
    ("https://www.puc.nh.gov/VirtualFileRoom/ShowDocument.aspx", True),
    ("https://catalog.data.gov/dataset/energy-storage", True),
    ("https://www.sec.gov/Archives/edgar/data/18808/x.htm", True),
    ("https://cpowerenergy.com/connecticuts-energy-storage-solutions-program", False),
    ("https://smartgrid.ccny.cuny.edu/research/", False),
])
def test_documents_are_not_read_as_organisation_pages(url, rejected):
    reason = actor_document_rejection(url)
    assert bool(reason) is rejected
    if reason:
        assert "leads" in reason.reason


# ------------------------------------------------------- official-site tools

HOME = ('<html><head><title>Acme Storage | Home</title></head><body>'
        '<a href="/news">News</a><a href="/about-us">About us</a>'
        '<p>Acme Storage builds grid batteries.</p></body></html>')


class Source:
    def __init__(self, pages, redirects=None):
        self.pages, self.redirects, self.fetched = pages, redirects or {}, []

    def fetch(self, url):
        self.fetched.append(url)
        final = self.redirects.get(url, url)
        if final not in self.pages:
            raise RuntimeError(f"404 {final}")
        return FetchedDoc.from_content(url=final, content=self.pages[final])


def test_the_official_bundle_reads_about_first_then_home():
    source = Source({"https://acme.example/": HOME,
                     "https://acme.example/about-us": "<p>Acme Storage is a Vermont company.</p>"})
    doc = official_bundle(source, "https://acme.example/products/x")
    assert doc.url == "https://acme.example/"
    assert doc.content.index("About page") < doc.content.index("Home page")
    assert "Acme Storage | Home" in doc.content
    assert site_is_official("Acme Storage", doc)
    assert not site_is_official("Beta Grid Partners", doc)
    assert about_link(FetchedDoc.from_content(url="https://acme.example/", content=HOME)) \
        == "https://acme.example/about-us"


def test_leads_are_names_never_inventions():
    class Model:
        def extract_with_tool(self, **kwargs):
            return {"organisations": [
                {"name": "NineDot Energy", "website": "ninedotenergy.com",
                 "source_url": "https://canarymedia.com/x", "why": "NYC storage developer"},
                {"name": "NineDot  Energy", "website": None, "source_url": "x", "why": "dup"},
                {"name": "", "website": None, "source_url": "x", "why": "empty"},
            ]}
    leads = harvest_leads(Model(), [{"url": "https://canarymedia.com/x", "title": "t", "snippet": "s"}],
                          topic="Energy", area="New York")
    assert [lead.name for lead in leads] == ["NineDot Energy"]
    assert leads[0].website == "https://ninedotenergy.com/"


# ------------------------------- the whole stage: re-reads, leads, budget, reasons

def _no_promotion(monkeypatch):
    """These tests stop at banding; promotion is covered by the DB integration tests."""
    from agents.discovery.search import phase2

    monkeypatch.setattr(phase2, "_extract_stage_route_promote", lambda **kwargs: None)


def _candidate(cid, url, *, verdict="accepted", reason="fetch", title="t", snippet="s"):
    return CandidateRecord(candidate_id=cid, run_id="run-1", entity_type="actor", query="q",
                           provider="stub", url=url, title=title, snippet=snippet,
                           domain=url.split("/")[2], triage_verdict=verdict,
                           triage_reason=reason, fit_score=None)


def _strong(name, website, state="VT"):
    return ActorPageAnalysis(
        rubric=_rubric_with_all_evidence(),
        record={**_canonical_record(name), "website": website, "state": state,
                "description": f"{name} is an energy storage company in Vermont. "
                               "It builds and operates grid batteries."})


def test_official_reads_and_leads_find_more_actors_and_say_why_for_the_rest(tmp_path, monkeypatch):
    _no_promotion(monkeypatch)
    third_party = ActorPageAnalysis(
        rubric=_rubric_with_all_evidence(),
        record={**_canonical_record("Beta Grid"), "website": "https://betagrid.example",
                "state": "VT", "description": "Beta Grid builds microgrids in Vermont. It runs pilots."})
    analyses = {
        "profiles.example": third_party,
        "betagrid.example": _strong("Beta Grid", "https://betagrid.example"),
        "acme.example": _strong("Acme Storage", "https://acme.example"),
    }

    class Extractor:
        classification_enabled = False
        llm_client = None

        def extract(self, doc, **_kwargs):
            return analyses[doc.url.split("/")[2]]

    class LeadModel:
        def extract_with_tool(self, **kwargs):
            return {"organisations": [
                {"name": "Acme Storage", "website": "acme.example", "source_url": "https://news.example/a", "why": "named"},
                {"name": "Gone Corp", "website": "gone.example", "source_url": "https://news.example/a", "why": "named"},
                {"name": "NoSite Org", "website": None, "source_url": "https://news.example/a", "why": "named"},
                {"name": "Mapped Org", "website": "mapped.example", "source_url": "https://news.example/a", "why": "named"},
            ]}

    source = Source(
        {
            "https://profiles.example/beta": "<p>Beta Grid profile</p>",
            "https://betagrid.example/": "<title>Beta Grid</title><p>Beta Grid microgrids</p>",
            "https://acme.example/": HOME,
            "https://acme.example/about-us": "<p>Acme Storage is a Vermont company.</p>",
            "https://other.example/": "<title>Other Power Co</title><p>Welcome</p>",
        },
        redirects={"https://gone.example/": "https://other.example/"},
    )
    config = {**CONFIG, "max_pages_fetched": 10, "max_new_domains": 10,
              "actor_lazy_classification": False}
    candidates = [
        _candidate("direct", "https://profiles.example/beta"),
        _candidate("news", "https://news.example/a", verdict="rejected",
                   reason="news article, a third-party publication",
                   title="Acme Storage and Gone Corp expand in Vermont"),
    ]
    stats = _empty_stats()
    outcome = fetch_score_stage_actors(
        run_id="run-1", candidates=candidates, config=config, root=None, session=None,
        live=False, run_log=InMemoryRunLog(), cost_meter=CostMeter(max_usd=5), stats=stats,
        audit_rows=[], actor_types=["company"], sector_codes=["WATER"],
        hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}, "lead_client": LeadModel(),
                       "existing_actor_names": ["mapped org"], "existing_actor_domains": []},
        source=source, rubric_extractor=Extractor(), reranker=None,
        raw_store=RawContentStore(tmp_path / "raw"), domain_store=InMemoryDiscoveredDomainStore(),
    )
    by_title = {}
    for c in outcome.candidates:
        by_title.setdefault(c.title, []).append(c)
    reasons = {c.title: c.triage_reason for c in outcome.candidates}

    # The third-party profile was superseded by a read of Beta Grid's own site.
    direct = next(c for c in outcome.candidates if c.candidate_id == "direct")
    assert direct.triage_verdict == "superseded" and direct.score_band is None
    beta = next(c for c in by_title["Beta Grid"] if c.provider == "official_site")
    assert beta.url == "https://betagrid.example/" and beta.score_band in {"auto_high", "review"}
    # A lead read on its confirmed official site became a candidate.
    acme = by_title["Acme Storage"][0]
    assert acme.provider == "official_site" and acme.rubric is not None
    # Every lead that was not read says exactly why.
    assert "merged, acquired or renamed" in reasons["Gone Corp"]
    assert "no official website is known" in reasons["NoSite Org"]
    assert "already on the map" in reasons["Mapped Org"]
    # Nothing excluded is left without a reason.
    excluded = [c for c in outcome.candidates if c.score_band in {None, "auto_low", "analysis_failed"}]
    assert all((c.triage_reason or "").strip() for c in excluded)
    # Two leads checked on their sites: Acme read and scored; Gone Corp rejected
    # for free as merged, before any model call (the stub extractor has no page
    # for other.example and would have failed had it been asked).
    assert stats["actor_official_followups"] == 1 and stats["actor_leads_read"] == 2


def test_the_budget_stops_reading_but_keeps_what_was_paid_for(tmp_path, monkeypatch):
    _no_promotion(monkeypatch)
    class Extractor:
        classification_enabled = False
        llm_client = None

        def __init__(self, meter):
            self.meter = meter

        def extract(self, doc, **_kwargs):
            self.meter.add(0.40, "page")
            return _strong("Acme Storage", "https://acme.example")

    # Each page really costs $0.40; the configured estimate says $0.03. After
    # the first page the budget uses what pages actually cost.
    meter = CostMeter(max_usd=0.50)
    source = Source({"https://acme.example/a": "<p>a</p>", "https://acme2.example/b": "<p>b</p>"})
    config = {**CONFIG, "max_pages_fetched": 10, "max_new_domains": 10, "actor_est_page_usd": 0.03,
              "actor_budget_reserve_usd": 0.05, "actor_lazy_classification": False,
              "actor_max_official_followups": 0, "actor_direct_budget_share": 1.0}
    stats = _empty_stats()
    outcome = fetch_score_stage_actors(
        run_id="run-1",
        candidates=[_candidate("one", "https://acme.example/a"),
                    _candidate("two", "https://acme2.example/b")],
        config=config, root=None, session=None, live=False, run_log=InMemoryRunLog(),
        cost_meter=meter, stats=stats, audit_rows=[], actor_types=["company"],
        sector_codes=["WATER"], hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}}, source=source, rubric_extractor=Extractor(meter),
        reranker=None, raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )
    one, two = sorted(outcome.candidates, key=lambda c: c.candidate_id)
    assert one.rubric is not None and one.score_band in {"auto_high", "review"}
    assert two.triage_verdict == "not_read" and "budget of $0.50" in two.triage_reason
    assert stats["actor_budget_stop"] == 1


def test_only_the_gated_deep_pull_module_writes_layer_2_facts():
    """The fact writer does not check verification itself; the Deep Pull gate
    does. So no other module may write Layer 2 facts, or an auto-Verified actor
    could be deep-pulled without a person's topic decision."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"\blayer\s*=\s*2\b|[\"']layer[\"']\s*:\s*2\b")
    writers = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for folder in ("agents", "src", "scripts")
        for path in (root / folder).rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    )
    assert writers == ["agents/collection/deep_pull.py"]



def test_direct_results_cannot_spend_the_share_kept_for_official_reads_and_leads(tmp_path, monkeypatch):
    _no_promotion(monkeypatch)

    class Extractor:
        classification_enabled = False
        llm_client = None

        def __init__(self, meter):
            self.meter = meter

        def extract(self, doc, **_kwargs):
            self.meter.add(0.30, "page")
            return _strong("Acme Storage", "https://acme.example")

    meter = CostMeter(max_usd=1.00)
    # Distinct pages: identical content would be served from the analysis cache.
    source = Source({f"https://site{i}.example/a": f"<p>page {i}</p>" for i in range(3)})
    config = {**CONFIG, "max_pages_fetched": 10, "max_new_domains": 10,
              "actor_lazy_classification": False, "actor_max_official_followups": 0,
              "actor_direct_budget_share": 0.45}
    stats = _empty_stats()
    outcome = fetch_score_stage_actors(
        run_id="run-1", candidates=[_candidate(f"c{i}", f"https://site{i}.example/a") for i in range(3)],
        config=config, root=None, session=None, live=False, run_log=InMemoryRunLog(),
        cost_meter=meter, stats=stats, audit_rows=[], actor_types=["company"],
        sector_codes=["WATER"], hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}}, source=source, rubric_extractor=Extractor(meter),
        reranker=None, raw_store=RawContentStore(tmp_path / "raw"),
        domain_store=InMemoryDiscoveredDomainStore(),
    )
    verdicts = {c.candidate_id: c for c in outcome.candidates}
    assert verdicts["c0"].rubric is not None and verdicts["c1"].rubric is not None
    assert verdicts["c2"].triage_verdict == "not_read"
    assert "kept for official-site reads and named leads" in verdicts["c2"].triage_reason
    assert stats["actor_direct_share_stop"] == 1


# ------------------------------------ found by the live Water run, 2026-10-15

def test_tech_meets_technology_in_the_sub_topic_check():
    """The Water Council was held for 'not mentioning water technology'."""
    from agents.discovery.search.actor_quality import mentions_focus

    assert mentions_focus(("water technology",), {"description": "A water tech hub."}, {})
    assert mentions_focus(("battery storage",), {"description": "Batteries and storage."}, {})
    assert not mentions_focus(("water reuse",), {"description": "Drinking water."}, {})


def test_a_sites_footer_year_counts_even_when_the_visible_text_is_old():
    """An active association was called 'nothing newer than 1974'."""
    source = Source({"https://ndrw.example/": (
        "<title>North Dakota Rural Water</title><p>Founded in 1974.</p>"
        "<footer>&copy; 2026 North Dakota Rural Water</footer>")})
    doc = official_bundle(source, "https://ndrw.example/")
    assert "[Years on the site: 1974 2026]" in doc.content
    assert assess_currency(
        name="North Dakota Rural Water", page_text="Founded in 1974.", page_url=doc.url,
        stated_website=doc.url, official_final_url=doc.url, on_own_site=True, today=TODAY,
        year_text=doc.content) is None


def test_admission_keeps_the_reviewers_sector_and_the_pages_sectors():
    """A reviewed discovery candidate used to become an actor with NO sector."""
    from agents.review.admission import _source_sector_codes

    source = {"rubric": {"sector_codes": [{"code": "water", "evidence": "x"},
                                           {"code": "SUSTAIN", "evidence": "y"}]}}
    assert _source_sector_codes(source, {"primary_sector": "WATER_TECH"}) == [
        "WATER_TECH", "WATER", "SUSTAIN"]
    assert _source_sector_codes(source, {}) == ["WATER", "SUSTAIN"]
    assert _source_sector_codes({"rubric": None}, {}) == []


def test_sector_codes_are_made_from_names():
    from agents.enrichment.decisions import sector_code_for

    assert sector_code_for("Water Technology") == "WATER_TECHNOLOGY"
    assert sector_code_for("Circular Economy and Recycling") == "CIRCULAR_ECONOMY"
    assert sector_code_for("!!") == ""


# ------------------- 2026-10-15 false positives / negatives on the stored candidates

@pytest.mark.parametrize("description", [
    "A regional web portal profiling the Greater Seattle AI ecosystem, its companies "
    "and research institutions.",
    "Overview of NYU student involvement in sustainability through majors and clubs.",
])
def test_a_description_of_a_web_page_is_never_auto_verified(description):
    """Both were accepted on the stored candidates; neither is an organisation profile."""
    verdict = assess_actor(
        score=0.85, priority=0.78, page_url="https://greater-seattle.com/ai",
        record={**_canonical_record("Greater Seattle AI Ecosystem"),
                "website": "https://greater-seattle.com/ai", "state": "WA",
                "description": description},
        rubric=_rubric_with_all_evidence(), config=QualityConfig(),
    )
    assert verdict.band == REVIEW
    assert "describes_a_page" in verdict.gates_failed


def test_an_unreadable_page_is_named_as_such_not_as_no_organisation():
    """guardianchem.com and coenergycrossroads.org read as empty, not as non-actors."""
    verdict = assess_actor(score=0.075, page_url="https://guardianchem.com/",
                           record={"name": None}, rubric=_empty_rubric(),
                           config=QualityConfig())
    assert verdict.band == REJECT
    assert "unreadable_page" in verdict.gates_failed
    assert "no_name" not in verdict.gates_failed


def test_unreadable_pages_get_one_official_reread_and_profiles_become_leads(tmp_path, monkeypatch):
    _no_promotion(monkeypatch)
    reads = {"guardian.example": 0}
    empty = ActorPageAnalysis(rubric=_empty_rubric(), record={"name": None})
    profile = ActorPageAnalysis(
        rubric=_empty_rubric(),
        record={**_canonical_record("Rural Water Association"), "website": None,
                "state": "ND", "description": "A nonprofit in Bismarck, ND."})

    class Extractor:
        classification_enabled = False
        llm_client = None

        def extract(self, doc, **_kwargs):
            domain = doc.url.split("/")[2]
            if domain == "guardian.example":
                reads[domain] += 1
                # The single page could not be read; its homepage + About page can.
                return empty if reads[domain] == 1 else _strong(
                    "Guardian Chemical", "https://guardian.example/")
            return profile

    lead_rows = []

    class LeadModel:
        def extract_with_tool(self, **kwargs):
            import json as _json
            lead_rows.extend(_json.loads(kwargs["user"])["results"])
            return {"organisations": []}

    source = Source({
        "https://guardian.example/": "<title>Guardian Chemical</title><p>Guardian Chemical</p>",
        "https://guardian.example/about-us": "<p>Guardian Chemical makes coatings.</p>",
        "https://registry.example/org/1": "<p>Rural Water Association</p>",
    })
    config = {**CONFIG, "max_pages_fetched": 10, "max_new_domains": 10,
              "actor_lazy_classification": False}
    stats = _empty_stats()
    outcome = fetch_score_stage_actors(
        run_id="run-1",
        candidates=[_candidate("js", "https://guardian.example/", title="Guardian Chemical"),
                    _candidate("profile", "https://registry.example/org/1")],
        config=config, root=None, session=None, live=False, run_log=InMemoryRunLog(),
        cost_meter=CostMeter(max_usd=5), stats=stats, audit_rows=[],
        actor_types=["company"], sector_codes=["WATER"], hub_names=["Texas Water Systems Hub"],
        actor_context={"coverage_counts": {}, "lead_client": LeadModel(),
                       "existing_actor_names": [], "existing_actor_domains": []},
        source=source, rubric_extractor=Extractor(), reranker=None,
        raw_store=RawContentStore(tmp_path / "raw"), domain_store=InMemoryDiscoveredDomainStore(),
    )
    original = next(c for c in outcome.candidates if c.candidate_id == "js")
    reread = next(c for c in outcome.candidates
                  if c.provider == "official_site" and "guardian.example" in c.url)
    # Re-read once; judged on what its own site says, and the unreadable read is superseded.
    assert reads["guardian.example"] == 2
    assert reread.rubric is not None and reread.score_band in {"auto_high", "review"}
    assert original.triage_verdict == "superseded"
    # The low-scoring third-party profile was offered as a lead, by its name.
    assert any(row["title"] == "Rural Water Association" for row in lead_rows)
