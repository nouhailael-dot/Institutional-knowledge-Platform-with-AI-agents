"""An update request's default ceiling is one the database accepts (27 Nov 2026).

The run ceiling was raised to 10.00 on 25 Nov, but the database bounds a request at
5.00 (migration 570, ck_actor_update_subscription_max_usd), so every new
organization update request was refused when it was saved.
"""

from __future__ import annotations

from pathlib import Path

from agents.collection.actor_updates import DEFAULT_SETTINGS, request_options, settings
from agents.collection.subscriptions import MAX_USD_PER_RUN
from agents.common.config import load_sources_config

ROOT = Path(__file__).resolve().parents[2]
ACTOR = "24ed7d2a-2392-4a3f-a177-5c74f5d57c40"


def test_the_configured_and_default_ceilings_fit_the_database_bound():
    config = dict(load_sources_config(ROOT).get("open_web_discovery") or {})
    assert float(settings(config)["max_usd_per_request_run"]) <= MAX_USD_PER_RUN
    assert float(DEFAULT_SETTINGS["max_usd_per_request_run"]) <= MAX_USD_PER_RUN


def test_a_request_with_the_default_ceiling_is_accepted():
    config = dict(load_sources_config(ROOT).get("open_web_discovery") or {})
    prepared = request_options({"actor_ids": [ACTOR]}, config=config)
    assert 0 < prepared["max_usd_per_run"] <= MAX_USD_PER_RUN
