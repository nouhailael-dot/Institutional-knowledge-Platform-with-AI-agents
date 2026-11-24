"""One form for the country (GHUS, 24 Nov 2026): every stored US spelling is "USA"."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from agents.common.geography import STORED_US, normalize_country, stored_country


@pytest.mark.parametrize("spelling", ["USA", "US", "us", "U.S.", "U.S.A.", "United States",
                                      "united states of america", "  United States "])
def test_every_us_spelling_is_saved_as_usa(spelling):
    assert stored_country(spelling) == STORED_US == "USA"


def test_the_gazetteer_keeps_its_own_two_letter_code():
    assert normalize_country("USA") == normalize_country("United States") == "US"


def test_other_countries_and_empty_values_are_kept():
    assert stored_country("Morocco") == "Morocco"
    assert stored_country("San Francisco") == "San Francisco"   # never guessed into a country
    assert stored_country("") is None and stored_country(None) is None


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
def test_the_correction_changes_us_spellings_only_and_is_a_dry_run_by_default(session):
    from agents.enrichment.decisions import standardize_countries

    tag = uuid.uuid4().hex[:8]
    made = {}
    # A production-shaped database requires where a record came from and its status;
    # older test copies have no such columns.
    present = {r[0] for r in session.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'actor' "
        "AND column_name IN ('source_origin', 'status')")).all()}
    wanted = [(c, v) for c, v in (("source_origin", "'ghus_manual'"), ("status", "'parked'")) if c in present]
    extra_col = "".join(f", {c}" for c, _ in wanted)
    extra_val = "".join(f", {v}" for _, v in wanted)
    for country in ("United States", "US", "USA", "Morocco"):
        actor_id = str(uuid.uuid4())
        session.execute(text(
            f"INSERT INTO actor (actor_id, name, slug, country, actor_category{extra_col}) "
            f"VALUES (CAST(:id AS uuid), :name, :slug, :country, 'company'{extra_val})"),
            {"id": actor_id, "name": f"Country {country} {tag}", "slug": f"country-{tag}-{len(made)}",
             "country": country})
        made[country] = actor_id

    def country(actor_id):
        return session.execute(text("SELECT country FROM actor WHERE actor_id = CAST(:id AS uuid)"),
                               {"id": actor_id}).scalar()

    dry = standardize_countries(session)
    assert dry["live"] is False and dry["actor"]["change"] >= 2
    assert {"United States", "US"} <= set(dry["actor"]["from"])
    assert country(made["United States"]) == "United States"            # a dry run writes nothing
    standardize_countries(session, live=True)
    assert [country(made[c]) for c in ("United States", "US", "USA", "Morocco")] == \
        ["USA", "USA", "USA", "Morocco"]
    assert standardize_countries(session)["actor"]["change"] == 0         # nothing left to do
