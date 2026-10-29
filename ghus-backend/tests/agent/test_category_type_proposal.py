"""An actor update proposes a Category Type for an actor that has none (GHUS, 2026-10-29)."""

from __future__ import annotations

from types import SimpleNamespace

from agents.collection.actor_updates import _proposal_count, type_proposal
from agents.common.actor_classification import needs_category_type
from agents.common.llm import FixtureToolClient

ANSWER = {"category_type": "professional_network", "doubt": False, "category_note": None,
          "main_job_evidence": "The commission convenes water managers from both countries."}


def _read(**sources):
    pages = list(sources)
    return SimpleNamespace(pages=pages, sources=sources,
                           texts={url: f"Text of {url}\nabout boundary waters." for url in pages})


def _actor(**changes):
    return {"actor_id": "a", "name": "International Joint Commission",
            "actor_category": "association_network", "category_type": None, **changes}


def test_an_untyped_actor_gets_a_type_from_its_own_official_pages():
    read = _read(**{"https://ijc.org/en/about": "official", "https://news.example/ijc": "third_party"})
    proposal = type_proposal(FixtureToolClient(ANSWER), _actor(), read)
    assert proposal == {
        "actor_category": "association_network", "category_type": "professional_network",
        "type_label": "Professional Network", "category_note": None,
        "main_job": ANSWER["main_job_evidence"], "source_url": "https://ijc.org/en/about"}
    assert _proposal_count([], {}, proposal) == 1


def test_nothing_is_proposed_for_a_typed_actor_or_from_third_party_pages_only():
    client = FixtureToolClient(ANSWER)
    official = _read(**{"https://ijc.org": "official"})
    assert type_proposal(client, _actor(category_type="trade_association"), official) is None
    assert type_proposal(client, _actor(), _read(**{"https://news.example": "third_party"})) is None
    assert type_proposal(client, _actor(actor_category=None), official) is None
    assert type_proposal(None, _actor(), official) is None
    assert client.usage.calls == 0                  # no model call was paid for
    # The retired catch-all counts as untyped; Not Applicable is a decision.
    assert needs_category_type(None) and needs_category_type("other")
    assert not needs_category_type("not_applicable")
