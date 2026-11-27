"""Organization updates read wider, and may propose a better description (25 Nov 2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.collection import description_upgrade
from agents.collection.light_pull_reader import LightPullReader, choose_pages
from agents.collection.update_reader import UpdateReader

HOME = "https://lab.example.org/"
PAGES = {
    "https://lab.example.org/about": "<p>The Example Lab is a research center in Tucson, Arizona.</p>",
    "https://lab.example.org/research": "<p>It studies critical minerals recovery.</p>",
    "https://lab.example.org/programs": "<p>It runs a mining workforce program with local colleges.</p>",
    "https://lab.example.org/projects": "<p>Projects on tailings reuse.</p>",
    "https://lab.example.org/news": "<p>News.</p>",
    "https://lab.example.org/funding": "<p>Funded by the state.</p>",
    "https://lab.example.org/partners": "<p>Partners.</p>",
}


def _fetch(url):
    if url.rstrip("/") == HOME.rstrip("/"):
        links = "".join(f'<a href="{u}">{u.rsplit("/", 1)[1]}</a>' for u in PAGES)
        return SimpleNamespace(url=HOME, content=f"<title>Example Lab</title>{links}")
    return SimpleNamespace(url=url, content=PAGES[url])


# ------------------------------------------------------------------- reading

def test_the_update_reader_reads_more_than_the_light_pull():
    assert UpdateReader.max_pages > LightPullReader.max_pages
    assert UpdateReader.topic_pages > LightPullReader.topic_pages
    assert UpdateReader.page_chars > LightPullReader.page_chars
    assert UpdateReader.followup_pages > LightPullReader.followup_pages
    assert UpdateReader(client=None, fetch=_fetch).max_tokens > LightPullReader(None, _fetch).max_tokens


def test_choose_pages_keeps_the_light_bound_and_reads_wider_when_asked():
    light = choose_pages(_fetch, HOME, topic_terms=["mining research"], actor_category="research")
    assert len(light) <= LightPullReader.max_pages
    wide = choose_pages(_fetch, HOME, topic_terms=["mining research programs"],
                        actor_category="research", max_pages=UpdateReader.max_pages,
                        topic_pages=UpdateReader.topic_pages)
    assert len(wide) > len(light)
    assert len({d.url for d in wide}) == len(wide)        # no page twice


# --------------------------------------------------------------- description

@pytest.mark.parametrize("text, weak", [
    (None, True), ("", True), ("N/A", True), ("A research lab.", True),
    ("The Example Lab is a university research center in Tucson, Arizona, that studies how "
     "critical minerals can be recovered from mine tailings and runs a workforce program with "
     "local community colleges to train technicians for the mining industry.", False),
])
def test_only_a_weak_description_is_rewritten(text, weak):
    assert (description_upgrade.weakness(text) is not None) is weak


class _Client:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def extract_with_tool(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        return self.answer


TEXTS = {u: t.replace("<p>", "").replace("</p>", "") for u, t in PAGES.items()}
GOOD = ("The Example Lab is a research center in Tucson, Arizona. It studies critical minerals "
        "recovery, including projects on tailings reuse, and runs a mining workforce program "
        "with local colleges.")


def test_a_proposal_rests_on_quotes_found_on_the_pages():
    client = _Client({"enough": True, "description": GOOD, "quotes": [
        {"url": "https://lab.example.org/about", "quote": "a research center in Tucson, Arizona"},
        {"url": "https://lab.example.org/programs", "quote": "runs a mining workforce program"}]})
    out = description_upgrade.propose(client, name="Example Lab", current="A lab.", texts=TEXTS)
    assert out["text"] == GOOD and len(out["quotes"]) == 2
    assert out["source_url"] == "https://lab.example.org/about"
    assert out["weakness"].startswith("The description is only")


def test_unchecked_quotes_propose_nothing():
    client = _Client({"enough": True, "description": GOOD, "quotes": [
        {"url": "https://lab.example.org/about", "quote": "the largest lab in the world"},
        {"url": "https://lab.example.org/news", "quote": "won a Nobel prize"}]})
    out = description_upgrade.propose(client, name="Example Lab", current="", texts=TEXTS)
    assert "text" not in out and "checked" in out["skipped"]


def test_a_good_description_is_never_sent_to_the_model():
    client = _Client({})
    good = ("The Example Lab is a university research center in Tucson, Arizona, that studies "
            "how critical minerals can be recovered from tailings and trains technicians with "
            "local colleges for the mining industry in the region.")
    out = description_upgrade.propose(client, name="Example Lab", current=good, texts=TEXTS)
    assert client.calls == 0 and "skipped" in out


def test_the_model_saying_not_enough_proposes_nothing():
    client = _Client({"enough": False, "description": "", "quotes": []})
    out = description_upgrade.propose(client, name="Example Lab", current="", texts=TEXTS)
    assert "skipped" in out


# ------------------------------------------------------------------ requests

def test_every_request_improves_weak_descriptions():
    """27 Nov 2026: part of every update run, not an option on the form."""
    import inspect

    from agents.collection.actor_updates import check_update, request_options

    for payload in ({}, {"improve_description": False}, {"improve_description": True}):
        prepared = request_options({"actor_ids": ["24ed7d2a-2392-4a3f-a177-5c74f5d57c40"], **payload})
        assert prepared["options"]["improve_description"] is True
    assert inspect.signature(check_update).parameters["improve_description"].default is True


def test_requests_saved_before_the_change_improve_descriptions_too():
    from agents.collection.actor_updates import _prepared_from

    for options in ({"scope": "general"}, {"scope": "general", "improve_description": False}):
        subscription = SimpleNamespace(
            update_options=options, title="t",
            actor_ids=["a"], sector_codes=None, state_code=None, start_date=None, end_date=None,
            cadence="once", max_usd_per_run=1.0)
        assert _prepared_from(subscription)["options"]["improve_description"] is True
