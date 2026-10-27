"""Errors in plain words, on every page: the messages people actually saw."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.plain_errors import GENERIC, explain, explain_payload, is_technical  # noqa: E402


@pytest.mark.parametrize(("raw", "plain"), [
    # The Actor Updates screen, 2026-10-21.
    ("University of Arizona Mining & Geological Engineering's website could not be read, so "
     "nothing was compared or written. site could not be read: HTTPStatusError: Client error "
     "'403 Forbidden' for url 'https://mge.engineering.arizona.edu/' For more information "
     "check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
     "University of Arizona Mining & Geological Engineering's website could not be read, so "
     "nothing was compared or written. site could not be read: the website refused automated "
     "access, so it could not be read."),
    # Browse, when the database stalled.
    ("psycopg.errors.ConnectionTimeout: connection timeout expired",
     "The database is not answering right now; please try again in a minute."),
    ("UndefinedColumn: column a.location_city does not exist",
     "The database is missing a part this feature needs (an update to the database has not "
     "been applied yet)."),
    ("httpx.ReadTimeout: timed out", "The service took too long to answer; please try again."),
    ("anthropic.RateLimitError: Error code: 429", "The service asked us to slow down; please try "
                                                 "again in a few minutes."),
    ("RuntimeError: robots.txt disallows fetching https://x.example/",
     "The website asks automated tools not to read this page, and we respect that."),
    ("KeyError: 'topic_id'", GENERIC),
])
def test_technical_messages_become_plain(raw, plain):
    assert explain(raw) == plain
    assert not is_technical(explain(raw))


@pytest.mark.parametrize("message", [
    "Choose at least one box, or a type of information, to update.",
    "Nothing could be read about X. Its website refuses automated access (it blocks tools like "
    "ours). Nothing was compared or written.",
    "This change has already been decided, or is no longer pending.",
])
def test_plain_messages_are_left_as_they_are(message):
    assert explain(message) == message


def test_a_runs_reasons_are_translated_and_the_original_kept():
    payload = {"runs": [{"status_reason": "ConnectError: [Errno 11001] getaddrinfo failed",
                         "actor_results": [{"error": "Shell: not updated"}]}]}
    out = explain_payload(payload)
    run = out["runs"][0]
    assert run["status_reason"] == ("The service could not be reached; check the address or "
                                    "try again later.")
    assert run["status_reason_technical"].startswith("ConnectError")
    assert run["actor_results"][0]["error"] == "Shell: not updated"


def test_the_api_answers_every_failure_in_plain_words(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.app as app_module

    class Bridge:
        configured = True

        def list_requests(self):
            from src.discovery.bridge import DiscoveryBridgeError

            raise DiscoveryBridgeError(
                "Traceback (most recent call last): psycopg.OperationalError: could not connect "
                "to server")

    monkeypatch.setattr(app_module, "discovery_bridge", lambda: Bridge())
    client = TestClient(app_module.app, raise_server_exceptions=False)
    failed = client.get("/api/discovery/requests").json()
    assert failed["detail"] == ("The database is not answering right now; please try again in "
                                "a minute.")
    assert "psycopg" in failed["technical"]
    # A request with a field missing: said in words, not as a list of objects.
    invalid = client.post("/api/review/candidates/x/changes/y", json={"choice": "use_new"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"].startswith("Some information is missing or not valid: ")
