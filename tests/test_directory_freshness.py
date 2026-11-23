"""A record verified in Review Results, saved from a map or imported with Data Feed shows
in the Ecosystem Directory at once (GHUS, 23 Nov 2026: Beyond Africa was verified and
did not appear). The server drops its cached lists after every write; the page reads
them again each time the Directory is opened. No database, no network."""

import inspect
from pathlib import Path

from backend import app as app_module
from backend import datafeed_routes

ROOT = Path(__file__).resolve().parents[1]


def test_a_write_drops_every_cached_directory_list(monkeypatch):
    calls = {"n": 0}

    def load():
        calls["n"] += 1
        return [calls["n"]]

    for name in ("_actors", "_hubs", "_events", "_people"):
        cached = app_module._fresh_for(3600)(load)
        monkeypatch.setattr(app_module, name, cached)
        first = cached()
        assert cached() == first                     # served from the cache
        app_module._directory_changed()
        assert cached() != first                     # read again after a write


def test_every_write_path_drops_the_cache():
    for handler in (app_module.review_candidate_decision, app_module.review_item_decision,
                    app_module.review_category_decisions, app_module.map_save_verified):
        assert "_directory_changed()" in inspect.getsource(handler), handler.__name__
    assert datafeed_routes.directory_changed is app_module._directory_changed


def test_a_data_feed_import_drops_the_cache(monkeypatch):
    seen = []

    class Service:
        def confirm(self, preview_id, **kwargs):
            return {"status": "staged", "run_id": "r1"}

    monkeypatch.setattr(datafeed_routes, "datafeed_service", lambda: Service())
    monkeypatch.setattr(datafeed_routes, "directory_changed", lambda: seen.append(True))
    monkeypatch.setattr(datafeed_routes, "current_user", lambda: "Tester")
    body = datafeed_routes.Confirmation(import_name="Test", attest_source=True, admission="directory",
                                        attest_authorized=True, accept_left_out=True)
    assert datafeed_routes.confirm("p1", body)["run_id"] == "r1"
    assert seen == [True]


def test_the_page_reads_the_lists_again_each_time_the_directory_opens():
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'useEffect(()=>{if(tab==="browse") setBrowseVisit(v=>v+1);},[tab]);' in page
    assert "<${Browse} visit=${browseVisit}/>" in page
    assert "<${V} focus=${focus} visit=${visit}/>" in page
    for path in ("actors", "hubs", "events", "people"):
        assert f'useOnce(()=>api("/api/browse/{path}"),[version,visit])' in page, path
