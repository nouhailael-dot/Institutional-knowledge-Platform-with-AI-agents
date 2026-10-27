"""An actor's location: found on its own pages, never a placeholder, fills an empty record."""

from __future__ import annotations

from agents.collection.actor_updates import location_parts
from agents.collection.light_pull_reader import _page_text
from agents.review.admission import _location_from_light_pull


def test_a_country_and_a_placeholder_are_not_a_location():
    """{"region": "Not Provided", "country": "US"} was stored as found (2026-10-15)."""
    from agents.collection.light_pull import _payload_evidence

    def location(payload):
        return _payload_evidence({"name": "X", **payload}, "company", None)["location"]

    assert location({"region": "Not Provided", "country": "US", "multi_location": False}) is None
    assert location({"city": "Unknown", "state": "n/a", "country": "US"}) is None
    found = location({"location_city": "Montpelier", "state": "VT", "region": "Not Provided"})
    assert found is not None and "region" not in str(found)


def test_the_footer_with_the_address_reaches_the_reader():
    html = ("<html><body><main><p>" + "word " * 3000 + "</p></main><footer><p>50 State Street"
            "</p><p>Montpelier, VT 05602</p><script>x()</script></footer></body></html>")
    text = _page_text(html)
    assert text.endswith("Footer: 50 State Street Montpelier, VT 05602")
    assert len(text) <= 7000 + 20


def test_location_values_in_every_shape_the_reader_gives():
    assert location_parts({"city": "Montpelier", "state": "VT"}) == ("Montpelier", "VT", None)
    assert location_parts('{"city": "Baltimore", "state": "MD"}') == ("Baltimore", "MD", None)
    assert location_parts("Montpelier, VT 05602") == ("Montpelier", "VT", None)
    assert location_parts("Baltimore, Maryland, USA") == ("Baltimore", "Maryland", "USA")
    assert location_parts({"region": "Not Provided", "country": "US"})[:2] == (None, None)
    assert location_parts("United States") == (None, None, None)


def test_admission_fills_an_empty_record_location_from_the_light_pull_read_only():
    evidence = {"location": {"collection_state": "found",
                             "value": {"city": "Montpelier", "state": "VT"}}}
    payload = {"name": "Clean Energy Group", "light_pull_evidence": evidence}
    _location_from_light_pull(payload)
    assert (payload["location_city"], payload["state"], payload["country"]) == (
        "Montpelier", "VT", "US")
    # A reviewer's value always wins.
    reviewed = {"name": "X", "location_city": "Burlington", "state": "VT",
                "light_pull_evidence": evidence}
    _location_from_light_pull(reviewed)
    assert reviewed["location_city"] == "Burlington"
    # The request's area gave the state: the city is filled when the read agrees...
    texas = {"name": "Base Power", "state": "Texas", "light_pull_evidence": {"location": {
        "collection_state": "found", "value": {"city": "Austin", "state": "TX"}}}}
    _location_from_light_pull(texas)
    assert (texas["location_city"], texas["state"]) == ("Austin", "Texas")
    # ...and left for the reviewer when it names another state.
    elsewhere = {"name": "EticaAG", "state": "Texas", "light_pull_evidence": {"location": {
        "collection_state": "found", "value": {"city": "Greensburg", "state": "PA"}}}}
    _location_from_light_pull(elsewhere)
    assert "location_city" not in elsewhere
    # Not found, or no city: nothing is filled.
    silent = {"name": "Y", "light_pull_evidence": {"location": {"collection_state": "not_found"}}}
    _location_from_light_pull(silent)
    assert "location_city" not in silent


def test_a_live_discovery_request_is_followed_by_the_light_pull_read(monkeypatch):
    from datetime import date

    from agents.collection import light_pull_candidates, subscription_runner as runner

    calls = []
    monkeypatch.setattr(light_pull_candidates, "main", lambda argv: calls.append(argv) or 0)
    report = runner.RunnerReport(live=True, today=date(2026, 10, 19), outcomes=[
        runner.RequestOutcome("r1", "Water", [], status="succeeded"),
        runner.RequestOutcome("r2", "Failed one", [], status="failed"),
        runner.RequestOutcome("r3", "An update", [], status="succeeded", kind="actor_update"),
    ])
    runner._light_pull_after(report, everything=True)       # the operator's --light-pull
    # Only the discovery run that ran; a second pass picks up any unread candidate.
    assert calls == [["--request-id", "r1", "--live"]] * 2
    assert "Light Pull" in report.outcomes[0].status_reason

    def refuse(argv):
        raise SystemExit("light_pull_candidates: DATABASE_URL is not a local *_test database")

    monkeypatch.setattr(light_pull_candidates, "main", refuse)
    shared = runner.RunnerReport(live=True, today=date(2026, 10, 19), outcomes=[
        runner.RequestOutcome("r4", "Prod", [], status="succeeded")])
    runner._light_pull_after(shared, everything=True)
    assert shared.outcomes[0].status == "succeeded"  # the discovery run itself stands
    assert "Light Pull not run" in shared.outcomes[0].status_reason


def test_a_request_reads_what_it_keeps_by_its_own_choice(monkeypatch):
    """New requests carry pull_depth=light: every run reads, scheduled or not."""
    from datetime import date

    from agents.collection import light_pull_candidates, subscription_runner as runner

    calls = []
    monkeypatch.setattr(light_pull_candidates, "main", lambda argv: calls.append(argv[1]) or 0)
    report = runner.RunnerReport(live=True, today=date(2026, 10, 26), outcomes=[
        runner.RequestOutcome("light", "New", [], status="succeeded", pull_depth="light"),
        runner.RequestOutcome("none", "Opted out", [], status="succeeded", pull_depth="none"),
        runner.RequestOutcome("legacy", "Saved before", [], status="succeeded"),
    ])
    runner._light_pull_after(report)                         # a scheduled run: no flag
    assert calls == ["light", "light"]
    calls.clear()
    runner._light_pull_after(report, everything=True)        # Run now passes --light-pull
    assert calls == ["light", "light", "legacy", "legacy"]
