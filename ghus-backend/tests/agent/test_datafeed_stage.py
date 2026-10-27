"""Data Feed staging: the backend's checks, and staging into the Review queues.

The checks run everywhere. The staging tests need a disposable local database
(``V2_DATAFEED_TEST_DATABASE_URL`` ending in ``_datafeed_test``) and roll every
test back, so the database is left as it was.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.datafeed import stage_import as feed

NOW = "2026-10-26T10:00:00+00:00"


def actor_row(n=2, **payload):
    base = {"name": "Prairie Water Lab Inc.", "website": "https://prairiewaterlab-test.org",
            "actor_category": "company", "category_type": "small_mid_size",
            "description": "A company that builds water sensors.", "country": "United States",
            "state": "KS", "state_code": "KS", "city": "Wichita", "location_city": "Wichita",
            "primary_sector": "WATER", "sector_codes": ["WATER"],
            "source_url": "https://prairiewaterlab-test.org/about"}
    base.update(payload)
    return {"row_number": n, "payload": base, "original": {"Official name": base["name"]},
            "match": {"kind": "new"}}


def batch(record_type="actor", rows=None, **extra):
    data = {"contract": feed.CONTRACT, "template_version": "2026-10-26.1",
            "record_type": record_type, "method": "upload", "import_name": "Test import",
            "file_name": "GHUS_Actors_Template.xlsx", "file_sha256": "a" * 64,
            "uploaded_by": "Test Uploader", "attestation": {"source": True},
            "submitted_at": NOW,
            "rows": [actor_row()] if rows is None else rows}
    data.update(extra)
    return data


# ------------------------------------------------------------------ checks
def test_batch_key_is_the_file_for_uploads_and_the_records_for_manual_entry():
    assert feed.batch_key(batch()) == feed.batch_key(batch(import_name="Renamed"))
    assert feed.batch_key(batch()) != feed.batch_key(batch(file_sha256="b" * 64))
    manual = batch(method="manual", file_sha256=None, file_name=None)
    assert feed.batch_key(manual) == feed.batch_key(dict(manual))
    changed = batch(method="manual", file_sha256=None, rows=[actor_row(name="Other Org Inc.")])
    assert feed.batch_key(manual) != feed.batch_key(changed)


def test_natural_keys():
    assert feed.natural_key("actor", {"website": "https://www.x-test.org/a"}) == "actor|x-test.org"
    assert feed.natural_key("actor", {"name": "No Site Co", "state_code": "tx"}) == \
        "actor|no-site-co|TX"
    assert feed.natural_key("event", {"name": "AgTech Summit", "start_date": "2027-03-04"}) == \
        "agtech-summit|2027-03-04"
    assert feed.natural_key("person", {"name": "Ana Ruiz", "affiliation": "Univ. of X"}) == \
        "ana-ruiz|univ-of-x"


@pytest.mark.parametrize("change, message", [
    ({"contract": "other/1"}, "unsupported batch contract"),
    ({"record_type": "hub"}, "record_type"),
    ({"method": "email"}, "method"),
    ({"import_name": ""}, "import name"),
    ({"file_sha256": "short"}, "SHA-256"),
    ({"rows": []}, "no records"),
])
def test_header_refusals(change, message):
    with pytest.raises(feed.DataFeedRefused, match=message):
        feed.check_header(batch(**change))


def test_actor_checks_use_the_catalog_and_the_light_pull_rules():
    ok = actor_row()["payload"]
    assert feed.check_actor(ok, method="upload", submitted_at=NOW) == []
    wrong_pair = {**ok, "actor_category": "university_academic"}
    assert any("is not a type of" in p
               for p in feed.check_actor(wrong_pair, method="upload", submitted_at=NOW))
    no_note = {**ok, "category_type": "not_applicable"}
    assert any("one-line note" in p for p in feed.check_actor(no_note, method="upload",
                                                               submitted_at=NOW))
    no_link = {**ok, "website": "", "source_url": ""}
    assert any("Website or a Source URL" in p
               for p in feed.check_actor(no_link, method="upload", submitted_at=NOW))
    undated = {**ok, "light_pull_values": {"recent_activity": {"description": "Opened a lab"}}}
    assert any("date" in p for p in feed.check_actor(undated, method="upload", submitted_at=NOW))
    ranked = {**ok, "light_pull_values": {"rankings": "QS 2026 #12"}}
    assert any("cannot be supplied" in p
               for p in feed.check_actor(ranked, method="upload", submitted_at=NOW))
    dated = {**ok, "light_pull_values": {"recent_activity": {"description": "Opened a lab",
                                                             "date": "2026-05-01"}}}
    assert feed.check_actor(dated, method="upload", submitted_at=NOW) == []


def test_classification_evidence_is_what_the_person_supplied_and_is_checked_now():
    ok = actor_row()["payload"]
    assert feed.classification_evidence(ok) == {"main_job": ok["description"]}
    startup = {**ok, "actor_category": "startup", "category_type": "university_spinout"}
    assert any("startup requires development-stage evidence" in p
               for p in feed.check_actor(startup, method="upload", submitted_at=NOW))
    staged = {**startup, "development_stage": "Pilot deployments with two utilities"}
    assert feed.check_actor(staged, method="upload", submitted_at=NOW) == []
    assert feed.classification_evidence(staged)["startup_origin"] == "university_spinout"
    lab = {**ok, "actor_category": "national_laboratory", "category_type": "government_direct"}
    assert any("requires formal designation evidence" in p
               for p in feed.check_actor(lab, method="upload", submitted_at=NOW))
    designated = {**lab, "light_pull_values": {"formal_national_designation":
                                               "DOE national laboratory"}}
    assert feed.check_actor(designated, method="upload", submitted_at=NOW) == []
    assert any("Description is required" in p
               for p in feed.check_actor({**ok, "description": ""}, method="upload",
                                         submitted_at=NOW))
    # Without a type the record waits for one in Review; nothing is classified here.
    assert feed.check_actor({**ok, "category_type": None}, method="upload", submitted_at=NOW) == []


def test_pipeline_keys_cannot_be_supplied():
    with pytest.raises(feed.DataFeedRefused, match="cannot be supplied"):
        feed._text_fields({"_auto_accept_reasons": ["x"]})


def test_person_checks():
    ok = {"name": "Ana Ruiz", "affiliation": "University of Arizona",
          "source_url": "https://www.arizona.edu/people/ana"}
    assert feed.check_person(ok) == []
    assert any("institution" in p for p in feed.check_person({**ok, "affiliation": "Professor"}))
    assert any("linkedin.com" in p
               for p in feed.check_person({**ok, "linkedin_url": "https://example.org/ana"}))
    assert any("required" in p for p in feed.check_person({**ok, "source_url": ""}))


def test_event_checks():
    ok = {"name": "Water Summit", "start_date": "2027-04-02", "end_date": "2027-04-03",
          "website": "https://watersummit-test.org"}
    assert feed.check_event(ok) == []
    assert any("before the start" in p for p in feed.check_event({**ok, "end_date": "2027-04-01"}))
    assert any("not a date" in p for p in feed.check_event({**ok, "start_date": "04/02/2027"}))
    assert any("Start date is required" in p for p in feed.check_event({**ok, "start_date": ""}))


# ------------------------------------------------------------------ staging (database)
URL = os.environ.get("V2_DATAFEED_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(
    not URL or "127.0.0.1:55432" not in URL or not URL.endswith("_datafeed_test"),
    reason="V2_DATAFEED_TEST_DATABASE_URL (a disposable *_datafeed_test database) is required",
)


@pytest.fixture
def session():
    engine = create_engine(URL)
    connection = engine.connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db
    finally:
        db.close()
        outer.rollback()
        connection.close()
        engine.dispose()


@needs_db
def test_actor_is_staged_for_review_with_its_origin_and_provenance(session):
    boxes = {"funding_signal": "USDA grant of $1.2M (2025)"}
    result = feed.stage_batch(session, batch(rows=[actor_row(light_pull_values=boxes)]))
    assert result["status"] == "staged" and result["staged"] == 1
    row = session.execute(text(
        "SELECT c.score_band, c.review_status, c.provider, c.record_preview, sr.status, "
        "sr.source_name, sr.stats FROM search_candidate c JOIN scrape_run sr USING (run_id) "
        "WHERE c.candidate_id = CAST(:id AS uuid)"), {"id": result["rows"][0]["source_id"]}
    ).mappings().one()
    preview = row["record_preview"]
    assert (row["score_band"], row["review_status"], row["status"]) == ("review", "pending",
                                                                       "succeeded")
    assert row["source_name"] == "ghus_data_feed"
    assert preview["_record_origin"] == "ghus_uploaded_doc"
    assert preview["data_feed"]["file_name"] == "GHUS_Actors_Template.xlsx"
    assert preview["data_feed"]["uploaded_by"] == "Test Uploader"
    assert preview["data_feed"]["admission"] == "review"
    assert preview["data_feed"]["attestation"]["source"] is True
    assert preview["data_feed"]["original_values"] == {"Official name": "Prairie Water Lab Inc."}
    evidence = preview["light_pull_evidence"]["funding_signal"]
    assert evidence["source_origin"] == "uploaded_document"
    assert evidence["value"] == "USDA grant of $1.2M (2025)"
    assert row["stats"]["datafeed"]["staged"] == 1


@needs_db
def test_the_same_batch_twice_is_staged_once(session):
    first = feed.stage_batch(session, batch())
    again = feed.stage_batch(session, batch())
    assert again["status"] == "already_imported" and again["run_id"] == first["run_id"]
    count = session.execute(text(
        "SELECT count(*) FROM search_candidate WHERE provider = 'ghus_data_feed' "
        "AND record_preview->'data_feed'->>'batch_key' = :key"), {"key": first["batch_key"]}
    ).scalar()
    assert count == 1


@needs_db
def test_a_record_already_waiting_in_review_is_not_staged_again(session):
    feed.stage_batch(session, batch())
    second = feed.stage_batch(session, batch(file_sha256="c" * 64, import_name="Second file",
                                             rows=[actor_row(), actor_row(3, name="New Org Inc.",
                                                   website="https://neworg-test.org")]))
    outcomes = [r["outcome"] for r in second["rows"]]
    assert outcomes == ["already_awaiting_review", "staged"]
    assert "Test import" in second["rows"][0]["warnings"][0]


@needs_db
def test_a_failing_row_stages_nothing(session):
    before = session.execute(text("SELECT count(*) FROM scrape_run")).scalar()
    bad = actor_row(3, actor_category="not_a_category")
    with pytest.raises(feed.DataFeedRefused, match="failed the checks"):
        feed.stage_batch(session, batch(rows=[actor_row(), bad]))
    assert session.execute(text("SELECT count(*) FROM scrape_run")).scalar() == before


@needs_db
def test_duplicate_rows_inside_one_batch_are_refused(session):
    checked = feed.check_batch(session, batch(rows=[actor_row(2), actor_row(5)]))
    assert checked["rows"][1]["errors"] == ["Same record as row 2."]


@needs_db
def test_event_is_staged_with_its_dates_and_suggested_match(session):
    existing = session.execute(text("SELECT event_id::text, name FROM event LIMIT 1")).one()
    row = {"row_number": 2, "payload": {
        "name": "Great Plains Water Summit", "start_date": "2027-04-02",
        "end_date": "2027-04-03", "event_type": "summit", "website": "https://gpws-test.org",
        "sector_codes": ["WATER"], "recurring_pattern": "annual", "event_format": "hybrid"},
        "original": {}, "match": {"kind": "possible", "entity_id": existing[0],
                                  "name": existing[1], "score": 0.91}}
    result = feed.stage_batch(session, batch("event", rows=[row], file_name="ev.csv"))
    queue = session.execute(text(
        "SELECT q.status, q.review_kind, q.candidate_event_id::text, q.shared_start_date::text, "
        "s.normalized_payload FROM event_review_queue q JOIN staged_record s USING "
        "(staged_record_id) WHERE q.event_review_id = CAST(:id AS uuid)"),
        {"id": result["rows"][0]["source_id"]}).one()
    assert queue[:4] == ("pending", "fuzzy_match", existing[0], "2027-04-02")
    assert queue[4]["end_date"] == "2027-04-03" and queue[4]["_record_origin"] == \
        "ghus_uploaded_doc"


@needs_db
def test_person_is_staged_with_a_candidate_source(session):
    row = {"row_number": 2, "payload": {
        "name": "Ana Ruiz Test", "role": "Professor of Hydrology",
        "affiliation": "University of Arizona", "linkedin_url": "https://www.linkedin.com/in/ana-test",
        "department": "Department of Hydrology", "expertise": ["groundwater"],
        "research_area": "groundwater", "source_url": "https://www.arizona.edu/ana-test",
        "sector_codes": ["WATER"]}, "original": {}, "match": {"kind": "new"}}
    result = feed.stage_batch(session, batch("person", rows=[row], method="manual",
                                             file_sha256=None, file_name=None))
    queue = session.execute(text(
        "SELECT q.status, q.public_profile_url, src.trust_tier, src.source_type, "
        "s.normalized_payload FROM person_review_queue q JOIN source src USING (source_id) "
        "JOIN staged_record s ON s.staged_record_id = q.staged_record_id "
        "WHERE q.person_review_id = CAST(:id AS uuid)"), {"id": result["rows"][0]["source_id"]}
    ).one()
    assert queue[:4] == ("pending", "https://www.linkedin.com/in/ana-test", "candidate",
                         "ghus_manual_entry")
    facts = queue[4]["facts"]
    assert facts["department"] == "Department of Hydrology"
    assert facts["evidence"]["department"]["source_origin"] == "ghus_manual"
    assert queue[4]["_record_origin"] == "ghus_manual"


@needs_db
def test_check_mode_writes_nothing(tmp_path):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch(file_sha256=uuid.uuid4().hex * 2)), encoding="utf-8")
    engine = create_engine(URL)
    with engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM search_candidate")).scalar()
    os.environ["DATABASE_URL"] = URL
    try:
        assert feed.main(["--batch", str(path)]) == 0
        os.environ.pop("DATAFEED_WRITES_ENABLED", None)
        assert feed.main(["--batch", str(path), "--live"]) == 2
    finally:
        os.environ.pop("DATABASE_URL", None)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM search_candidate")).scalar() == before
    engine.dispose()


# ------------------------------------------------------------------ uploader and Verified
def test_a_verified_import_needs_an_actor_batch_a_named_uploader_and_both_attestations():
    ok = batch(admission="verified", attestation={"source": True, "authorized": True})
    feed.check_header(ok)
    for change, message in [
        ({"record_type": "event"}, "only organizations"),
        ({"uploaded_by": " "}, "uploader's name"),
        ({"attestation": {"source": True}}, "attestation"),
        ({"admission": "auto"}, "review or verified"),
    ]:
        with pytest.raises(feed.DataFeedRefused, match=message):
            feed.check_header({**ok, **change})


def test_every_live_import_names_its_uploader_and_confirms_the_source():
    feed.check_uploader(batch())
    with pytest.raises(feed.DataFeedRefused, match="uploader's name"):
        feed.check_uploader(batch(uploaded_by=None))
    with pytest.raises(feed.DataFeedRefused, match="GHUS source"):
        feed.check_uploader(batch(attestation={}))


def test_only_new_typed_actors_are_admitted_as_verified(monkeypatch):
    from agents.review import admission

    calls = []

    def fake(session, decision, *, import_verification=None):
        calls.append((decision, import_verification))
        if decision["source_ref"]["id"] == "c4":
            raise admission.AdmissionConflict("frozen entity resolution found a match")
        return {"canonical_entity_id": "a-" + decision["source_ref"]["id"],
                "promotion_action": "created"}

    monkeypatch.setattr(admission, "apply_review_decision", fake)

    class _Session:
        def rollback(self):
            pass

    b = batch(admission="verified", attestation={"source": True, "authorized": True}, rows=[
        actor_row(2), actor_row(3, category_type=None), actor_row(4), actor_row(5)])
    b["rows"][2]["match"] = {"kind": "existing", "entity_id": "x"}
    result = {"batch_key": "k", "rows": [
        {"row_number": n, "outcome": "staged", "source_table": "search_candidate",
         "source_id": f"c{i}"} for i, n in ((1, 2), (2, 3), (3, 4), (4, 5))]}
    result["rows"][3]["source_id"] = "c4"
    out = {o["row_number"]: o for o in feed.admit_verified(_Session(), b, result)}
    assert out[2]["outcome"] == "approved_verified" and out[2]["entity_id"] == "a-c1"
    assert out[3]["outcome"] == "awaiting_review" and "Category Type" in out[3]["reason"]
    assert out[4]["outcome"] == "awaiting_review" and "already be on the map" in out[4]["reason"]
    assert out[5]["outcome"] == "awaiting_review" and "Admission refused" in out[5]["reason"]
    decision, verification = calls[0]
    assert decision["reviewer"] == "Test Uploader" and decision["decision_kind"] == "new"
    assert decision["idempotency_key"] == "datafeed-import:k:2"
    assert verification["by"] == "Test Uploader"
    assert "GHUS_Actors_Template.xlsx, row 2" in verification["reason"]
    assert "authorized GHUS staff" in verification["reason"]
