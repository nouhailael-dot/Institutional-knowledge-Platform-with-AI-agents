"""Review shows every Light Pull box the backend read collected, never as editable fields."""

from src.review.postgres_source import _attach_page_facts

PAGES = ["https://thewatercouncil.com/", "https://thewatercouncil.com/about-us/"]


def _payload():
    return {
        "name": "The Water Council", "website": "https://thewatercouncil.com/",
        "description": "The Water Council is a nonprofit membership hub in Milwaukee.",
        "actor_category": "association_network", "state": "Wisconsin",
        "current_activities": "Ongoing member activities.",
        "light_pull_evidence": {
            "recent_activity": {"collection_state": "found", "confidence": "high",
                                "value": {"date": "March 2026", "description": "Launched BREW 2.0."},
                                "source_url": PAGES[1], "date_read": "2026-10-15T10:00:00+00:00"},
            "um6p_ocp_connection": {"collection_state": "not_found", "value": None},
            "linked_members": {"collection_state": "found", "value": "Badger Meter, Veolia",
                               "source_url": PAGES[0]},
            "description": {"collection_state": "found", "value": "Agent text."},
            "location": {"collection_state": "found", "value": {"city": "Elsewhere"}},
        },
        "light_pull_read": {"pages_read": PAGES, "read_at": "2026-10-15T10:00:00+00:00"},
    }


def test_collected_boxes_are_shown_with_the_pages_read():
    payload, metadata = _payload(), {"rubric": {}}
    _attach_page_facts(payload, metadata, url=PAGES[0], read_at="2026-10-15")
    facts = {f["fact_key"]: f for f in metadata["facts"]}
    # A checked, dated activity replaces the page's undated "current activities".
    assert facts["recent_activity"]["value"]["date"] == "March 2026"
    assert facts["linked_members"]["source_url"] == PAGES[0]
    # Not stated: shown as not found, with the pages that were read.
    assert facts["um6p_ocp_connection"]["collection_state"] == "not_found"
    assert facts["um6p_ocp_connection"]["pages_read"] == PAGES
    # The reviewer-editable record keeps its own description and location.
    assert facts["description"]["value"].startswith("The Water Council is")
    assert facts["location"]["value"]["state"] == "Wisconsin"
    assert metadata["light_pull_read"]["pages_read"] == PAGES


def test_collected_evidence_is_not_an_editable_record_field():
    payload, metadata = _payload(), {"rubric": {}}
    _attach_page_facts(payload, metadata, url=PAGES[0], read_at="2026-10-15")
    assert "light_pull_evidence" not in payload and "light_pull_read" not in payload


def test_the_bridge_runs_the_backend_with_this_app_s_interpreter(monkeypatch, tmp_path):
    """A bare "python" ran an interpreter without the backend's dependencies,
    so every decision failed with "admission process exited with code 1"."""
    import subprocess
    import sys
    import types

    from src.review.admission import AdmissionBridge

    monkeypatch.delenv("GHUS_ADMISSION_PYTHON", raising=False)
    root = tmp_path / "backend"
    (root / "agents" / "review").mkdir(parents=True)
    (root / "agents" / "review" / "admission.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"], seen["timeout"] = command, kwargs.get("timeout")
        return types.SimpleNamespace(returncode=0, stdout='{"status": "approved"}', stderr="")

    bridge = AdmissionBridge(project_root=root, database_url="postgresql://x/y_test",
                             run_command=fake_run)
    assert bridge.apply({"decision_kind": "new"}) == {"status": "approved"}
    assert seen["command"][0] == sys.executable
    assert seen["timeout"] >= 600          # the resolver model load needs minutes
    assert subprocess  # the real default is still subprocess.run


def test_an_over_long_field_says_which_field_and_by_how_much():
    """A 48-character lifecycle role from the agent blocked two candidates
    behind "A text value exceeds the 30-character limit." - naming no field."""
    import pytest

    from src.review.store import ReviewStore, ReviewValidationError

    store = ReviewStore(":memory:")
    with pytest.raises(ReviewValidationError, match=r"Lifecycle role is 48 characters; the limit is 30"):
        store.validate_payload("actor", {
            "name": "California Department of Water Resources",
            "primary_lifecycle_role": "Government agency managing state water resources",
        })


def test_a_refusal_says_why_instead_of_an_exit_code():
    from src.review.admission import refusal_reason

    stderr = (
        "Traceback (most recent call last):\n  ...\n"
        "AdmissionConflict: frozen entity resolution found an existing or ambiguous match "
        "(website_domain: North Dakota Water Users Association "
        "fdee588b-625d-4974-89bc-28add40e58c0); choose same existing or defer\n")
    said = refusal_reason(stderr, 1)
    assert "already in the directory" in said and "North Dakota Water Users Association" in said
    assert "same website" in said and "fdee588b" not in said
    close = refusal_reason("AdmissionConflict: frozen entity resolution found an existing "
                           "or ambiguous match; choose same existing or defer", 1)
    assert "close match" in close
    assert refusal_reason("agents.review.admission.AdmissionValidationError: "
                          "unsupported edited fields: foo", 1) == "unsupported edited fields: foo"
    # Anything that is not a named refusal never reaches the page.
    assert refusal_reason("psycopg.OperationalError: password authentication failed", 1) == \
        "Admission process exited with code 1."


def test_a_coloured_traceback_still_yields_the_reason():
    """Python 3.13 colours tracebacks; the server's environment asks for it."""
    from src.review.admission import refusal_reason

    coloured = ("\x1b[1;35mAdmissionConflict\x1b[0m: \x1b[35mfrozen entity resolution found an "
                "existing or ambiguous match (website_domain: North Dakota Water Users Association "
                "fdee588b-625d-4974-89bc-28add40e58c0)); choose same existing or defer\x1b[0m")
    assert "already in the directory as “North Dakota Water Users Association”" in refusal_reason(coloured, 1)
