"""Monitor and Update requests (GHUS, 2026-10-29): People descriptions, Daily,
the requester's email, end-date changes and the findings email."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from agents.collection import discovery_requests, notify, subscription_store
from agents.collection.people_brief import BriefError, apply_brief, read_brief
from agents.collection.subscriptions import CADENCE_DAYS, SubscriptionError
from agents.common.llm import FixtureToolClient


# ----------------------------------------------------------- People description

def test_a_people_description_is_read_into_themes_role_and_a_name():
    client = FixtureToolClient({"title": "Groundwater researchers in Arizona.",
                                "themes": ["groundwater recharge", "Groundwater Recharge",
                                           "water reuse agriculture"],
                                "role": "professor", "institution": None})
    read = read_brief("Researchers in Arizona working on groundwater recharge and water reuse.",
                      client=client)
    assert read == {"title": "Groundwater researchers in Arizona",
                    "themes": ["groundwater recharge", "water reuse agriculture"],
                    "role": "professor", "institution": None}
    with pytest.raises(BriefError):
        read_brief("hi", client=client)
    with pytest.raises(BriefError):
        read_brief("Someone useful, please find them.",
                   client=FixtureToolClient({"title": "x", "themes": [" "], "role": None,
                                             "institution": None}))


def test_only_a_people_draft_without_themes_is_read_and_what_was_set_wins():
    client = FixtureToolClient({"title": "Battery storage directors", "themes": ["battery storage"],
                                "role": "program director", "institution": "UT Austin"})
    brief = "Program directors leading battery storage centers at UT Austin."
    fields = {"discovery_entity": "person", "title": "", "focus_terms": [],
              "discovery_options": {"brief": brief, "role": "dean"}}
    read = apply_brief(fields, client=client)
    assert read["focus_terms"] == ["battery storage"]
    assert read["title"] == "Battery storage directors"
    assert read["discovery_options"] == {"brief": brief, "role": "dean", "institution": "UT Austin"}
    # An event, or a person with themes already, is left exactly as it is.
    event = {"discovery_entity": "event", "focus_terms": [], "discovery_options": {"brief": brief}}
    assert apply_brief(event, client=client) is event
    named = {**fields, "focus_terms": ["grid storage"]}
    assert apply_brief(named, client=client) is named


# ----------------------------------------------------------- Daily and the form

class _Constraint:
    def __init__(self, definition):
        self.definition = definition

    def execute(self, *_args, **_kwargs):
        return SimpleNamespace(scalar=lambda: self.definition)


def test_daily_is_offered_only_where_the_database_accepts_it():
    assert CADENCE_DAYS["daily"] == 1
    before = "CHECK ((cadence = ANY (ARRAY['once'::text, 'weekly'::text, 'monthly'::text])))"
    after = "CHECK ((cadence = ANY (ARRAY['once'::text, 'daily'::text, 'weekly'::text])))"
    assert "daily" not in discovery_requests._db_cadences(_Constraint(before))
    assert discovery_requests._db_cadences(_Constraint(after))[:2] == ["once", "daily"]
    assert discovery_requests._db_cadences(_Constraint(None)) == list(CADENCE_DAYS)


def _payload(**changes):
    today = date.today().isoformat()
    return {"title": "Water", "sector_codes": ["WATER"], "focus_terms": ["reuse"],
            "start_date": today, "end_date": today, "cadence": "once", **changes}


def test_the_requester_is_an_email_address_or_nothing():
    fields = discovery_requests._draft_fields(_payload(requested_by=" analyst@um6p.ma "))
    assert fields["requested_by"] == "analyst@um6p.ma"
    assert discovery_requests._draft_fields(_payload())["requested_by"] is None
    with pytest.raises(SubscriptionError):
        discovery_requests._draft_fields(_payload(requested_by="not an email"))


# ----------------------------------------------------------- end-date changes

class _Rows:
    def __init__(self, row):
        self.row = row
        self.statements = []

    def execute(self, statement, values=None):
        self.statements.append((str(statement), values))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))


def _request(**changes):
    today = date.today()
    return {"status": "active", "requested_via": "discovery_page", "cadence": "weekly",
            "start_date": today, "end_date": today + timedelta(days=30), **changes}


def test_an_end_date_is_changed_only_on_a_running_recurring_request():
    today = date.today()
    later = today + timedelta(days=90)
    written = subscription_store.set_end_date(_Rows(_request()), "id", later, max_days=365)
    assert written.live is False and written.values["end_date"] == later
    for row, end in ((_request(status="expired"), later), (_request(status="cancelled"), later),
                     (_request(cadence="once"), later),
                     (_request(), today - timedelta(days=1)),
                     (_request(), today + timedelta(days=400))):
        with pytest.raises(SubscriptionError):
            subscription_store.set_end_date(_Rows(row), "id", end, max_days=365)


# ----------------------------------------------------------- the findings email

class _SMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, message):
        _SMTP.sent.append(message)


def _outcome(**counts):
    return SimpleNamespace(title="Water reuse researchers", entity="person",
                           counts={"staged": 0, "review": 0, **counts})


def test_a_run_with_findings_emails_whoever_asked_when_mail_is_configured():
    env = {"GHUS_SMTP_HOST": "smtp.example.org", "GHUS_NOTIFY_FROM": "compass@example.org",
           "GHUS_APP_URL": "https://compass.example.org"}
    _SMTP.sent = []
    result = notify.notify_findings(_outcome(review=3), "analyst@um6p.ma", environ=env,
                                    smtp_factory=_SMTP)
    assert result == {"sent": True, "to": "analyst@um6p.ma"}
    message = _SMTP.sent[0]
    assert message["Subject"] == "Compass found 3 people: Water reuse researchers"
    assert "https://compass.example.org/#review" in message.get_content()
    # Nothing found, nobody to tell, or no mail server: nothing is sent, and it says why.
    assert notify.notify_findings(_outcome(), "analyst@um6p.ma", environ=env)["reason"] == "nothing found"
    assert notify.notify_findings(_outcome(review=1), None, environ=env)["sent"] is False
    no_server = notify.notify_findings(_outcome(review=1), "analyst@um6p.ma", environ={})
    assert no_server == {"sent": False, "reason": "no mail server configured (GHUS_SMTP_HOST)"}


def test_the_runner_tells_only_discovery_runs_that_found_something():
    from agents.collection.subscription_runner import RequestOutcome, RunnerReport, _notify_after

    report = RunnerReport(live=True, today=date.today())
    found = RequestOutcome("a", "Found", [], status="succeeded", counts={"review": 2},
                           notify_to="analyst@um6p.ma")
    empty = RequestOutcome("b", "Empty", [], status="succeeded", counts={},
                           notify_to="analyst@um6p.ma")
    failed = RequestOutcome("c", "Failed", [], status="failed", counts={"review": 2},
                            notify_to="analyst@um6p.ma")
    report.outcomes = [found, empty, failed]
    _notify_after(report, environ={})
    assert found.notified == {"sent": False, "reason": "no mail server configured (GHUS_SMTP_HOST)"}
    assert empty.notified is None and failed.notified is None
