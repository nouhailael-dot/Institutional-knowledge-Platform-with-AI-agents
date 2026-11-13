"""The Ecosystem Directory reads its lists again after a short while (13 Nov 2026).

They were kept until the server restarted: people deleted in the database still
showed, and the people just stored from a Data Feed import did not.
"""


def test_a_directory_list_is_read_again_once_it_is_stale(monkeypatch):
    import backend.app as app_module

    reads = []
    monkeypatch.setattr(app_module.browse, "load_people", lambda: reads.append(1) or [f"read {len(reads)}"])
    clock = [1000.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: clock[0])
    app_module._people.cache_clear()
    assert app_module._people() == ["read 1"]
    clock[0] += 5
    assert app_module._people() == ["read 1"]                    # still fresh: not read again
    clock[0] += app_module.DIRECTORY_FRESH_SECONDS
    assert app_module._people() == ["read 2"]                    # stale: read again
    app_module._people.cache_clear()
    assert app_module._people() == ["read 3"]                    # an edit clears it at once
    app_module._people.cache_clear()
