"""The Discovery page reaches GHUS only through the backend's own command."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from src.discovery.bridge import DiscoveryBridge, DiscoveryBridgeError


def _backend(tmp_path):
    module = tmp_path / "agents" / "collection" / "discovery_requests.py"
    module.parent.mkdir(parents=True)
    module.write_text("# stand-in\n", encoding="utf-8")
    return tmp_path


def _bridge(tmp_path, *, stdout="", returncode=0, calls=None, raises=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        if raises:
            raise raises
        return SimpleNamespace(stdout=stdout, returncode=returncode)

    return DiscoveryBridge(project_root=_backend(tmp_path), python_executable="py",
                           database_url="postgresql://local/x_test", run_command=run)


def test_unconfigured_means_nothing_is_called(tmp_path):
    calls = []
    bridge = DiscoveryBridge(project_root=tmp_path, database_url=None,
                             run_command=lambda *a, **k: calls.append(a))
    assert not bridge.configured
    with pytest.raises(DiscoveryBridgeError, match="not configured"):
        bridge.list_requests()
    assert calls == []


def test_writes_are_explicitly_live_and_reads_are_not(tmp_path):
    calls = []
    bridge = _bridge(tmp_path, stdout=json.dumps({"ok": True, "requests": []}), calls=calls)
    bridge.list_requests()
    bridge.create({"title": "x"})
    bridge.change("00000000-0000-4000-8000-000000000001", "pause")
    assert "--live" not in calls[0][0]
    assert calls[1][0][-1] == "--live" and calls[2][0][-1] == "--live"
    assert all(c[0][1:3] == ["-m", "agents.collection.discovery_requests"] for c in calls)
    # The database the command uses is the bridge's, whatever the app's own is.
    assert calls[0][1]["env"]["DATABASE_URL"] == "postgresql://local/x_test"


def test_a_refusal_carries_ghus_reason(tmp_path):
    bridge = _bridge(tmp_path, returncode=2,
                     stdout=json.dumps({"ok": False, "error": "a discovery request needs a topic"}))
    with pytest.raises(DiscoveryBridgeError, match="needs a topic") as caught:
        bridge.create({"title": "x"})
    assert caught.value.rejected


def test_a_crash_is_not_reported_as_a_refusal(tmp_path):
    bridge = _bridge(tmp_path, returncode=1, stdout="Traceback ...")
    with pytest.raises(DiscoveryBridgeError, match="no readable answer") as caught:
        bridge.options()
    assert not caught.value.rejected


def test_a_timeout_changes_nothing(tmp_path):
    bridge = _bridge(tmp_path, raises=subprocess.TimeoutExpired("py", 120))
    with pytest.raises(DiscoveryBridgeError, match="nothing was changed"):
        bridge.change("00000000-0000-4000-8000-000000000001", "cancel")


def test_only_known_actions_are_sent(tmp_path):
    calls = []
    bridge = _bridge(tmp_path, stdout="{}", calls=calls)
    with pytest.raises(DiscoveryBridgeError):
        bridge.change("00000000-0000-4000-8000-000000000001", "delete")
    assert calls == []


def test_routes_fail_closed_and_validate(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.app as app_module

    class Unconfigured:
        configured = False

        def list_requests(self):
            raise AssertionError("an unconfigured bridge must never be called")

    monkeypatch.setattr(app_module, "discovery_bridge", lambda: Unconfigured())
    client = TestClient(app_module.app)
    assert client.get("/api/discovery/status").json() == {"configured": False}
    assert client.get("/api/discovery/requests").status_code == 503

    class Recording:
        configured = True

        def __init__(self):
            self.changed = []

        def change(self, subscription_id, action):
            self.changed.append((subscription_id, action))
            return {"status": "paused"}

        def create(self, draft):
            raise DiscoveryBridgeError("a discovery request needs a topic", rejected=True)

    bridge = Recording()
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: bridge)
    assert client.post("/api/discovery/requests/not-a-uuid/pause").status_code == 404
    assert client.post(
        "/api/discovery/requests/00000000-0000-4000-8000-000000000001/delete").status_code == 404
    ok = client.post("/api/discovery/requests/00000000-0000-4000-8000-000000000001/pause")
    assert ok.status_code == 200 and bridge.changed[-1][1] == "pause"
    refused = client.post("/api/discovery/requests", json={
        "title": "x", "end_date": "2027-01-01", "cadence": "weekly"})
    assert refused.status_code == 422 and "needs a topic" in refused.json()["detail"]
    too_many = client.post("/api/discovery/requests", json={
        "title": "x", "end_date": "2027-01-01", "cadence": "weekly",
        "max_new_actors_per_run": 500})
    assert too_many.status_code == 422


def test_run_now_starts_a_live_run_of_that_request_only(tmp_path):
    started = []
    bridge = DiscoveryBridge(
        project_root=_backend(tmp_path), python_executable="py",
        database_url="postgresql://local/x_test",
        start_process=lambda command, **kwargs: started.append((command, kwargs)),
    )
    result = bridge.run_now("00000000-0000-4000-8000-000000000001")
    command, kwargs = started[0]
    assert result["started"] is True
    assert command[1:3] == ["-m", "agents.collection.subscription_runner"]
    assert "--live" in command
    assert command[command.index("--request-id") + 1] == "00000000-0000-4000-8000-000000000001"
    assert kwargs["env"]["DATABASE_URL"] == "postgresql://local/x_test"
    with pytest.raises(DiscoveryBridgeError):
        bridge.run_now("../../etc")
    assert len(started) == 1


def _update_bridge(tmp_path, calls, answer=None):
    import types

    root = tmp_path / "backend"
    (root / "agents" / "collection").mkdir(parents=True)
    (root / "agents" / "collection" / "discovery_requests.py").write_text("", encoding="utf-8")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"], kwargs["timeout"]))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(answer or {"ok": True}))

    return DiscoveryBridge(project_root=root, database_url="postgresql://x/y_test",
                           run_command=fake_run)


def test_plan_and_check_never_set_the_write_switch_and_only_apply_does(tmp_path):
    """Plan is free, check reads and writes nothing; only "Write" may write."""
    import sys as _sys

    calls = []
    bridge = _update_bridge(tmp_path, calls)
    actor = "11111111-2222-3333-4444-555555555555"
    options = {"scope": "specific", "depth": "light", "topic": "ENERGY",
               "fields": ["funding_signal", "recent_activity"], "categories": ["funding"],
               "focus": "  new   DOE grants "}
    bridge.plan_update(actor, options)
    bridge.check_update(actor, options)
    bridge.apply_update("a" * 32)

    plan, check, apply = calls
    assert plan[0][:4] == [_sys.executable, "-m", "agents.collection.actor_updates", "plan"]
    assert check[0][3] == "check" and apply[0][3:] == ["apply", "--check-id", "a" * 32]
    for command, env, _ in (plan, check):
        assert "ACTOR_UPDATE_WRITES_ENABLED" not in env
        assert command[command.index("--scope") + 1] == "specific"
        assert command[command.index("--topic") + 1] == "ENERGY"
        assert command[command.index("--fields") + 1] == "funding_signal,recent_activity"
        assert command[command.index("--categories") + 1] == "funding"
        assert command[command.index("--focus") + 1] == "new DOE grants"
    assert apply[1]["ACTOR_UPDATE_WRITES_ENABLED"] == "true"
    assert check[2] >= 300  # reading three pages and calling the model takes time


@pytest.mark.parametrize("actor,options", [
    ("'; drop table actor; --", {}),
    ("11111111-2222-3333-4444-555555555555", {"scope": "everything"}),
    ("11111111-2222-3333-4444-555555555555", {"depth": "deepest"}),
    ("11111111-2222-3333-4444-555555555555", {"topic": "WATER; rm -rf"}),
    ("11111111-2222-3333-4444-555555555555", {"fields": ["funding signal"]}),
    ("11111111-2222-3333-4444-555555555555", {"categories": ["--live"]}),
])
def test_an_actor_update_refuses_what_is_not_a_known_value(tmp_path, actor, options):
    calls = []
    bridge = _update_bridge(tmp_path, calls)
    with pytest.raises(DiscoveryBridgeError):
        bridge.check_update(actor, options)
    assert calls == []


def test_apply_refuses_a_check_id_that_is_not_one(tmp_path):
    calls = []
    with pytest.raises(DiscoveryBridgeError):
        _update_bridge(tmp_path, calls).apply_update("../../.env")
    assert calls == []


def test_actor_update_routes_validate_before_calling_the_backend(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.app as app_module

    class Recording:
        configured = True

        def __init__(self):
            self.calls = []

        def plan_update(self, actor_id, options):
            self.calls.append(("plan", actor_id, options))
            return {"summary": "x"}

        def check_update(self, actor_id, options):
            self.calls.append(("check", actor_id, options))
            return {"check_id": "b" * 32}

        def apply_update(self, check_id):
            self.calls.append(("apply", check_id))
            return {"run_id": "r"}

    bridge = Recording()
    monkeypatch.setattr(app_module, "discovery_bridge", lambda: bridge)
    client = TestClient(app_module.app)
    actor = "11111111-2222-3333-4444-555555555555"
    assert client.post("/api/discovery/actors/not-an-id/plan", json={}).status_code == 404
    assert client.post("/api/discovery/actor-checks/xyz/apply").status_code == 404
    assert client.post(f"/api/discovery/actors/{actor}/check",
                       json={"focus": "x" * 300}).status_code == 422
    assert client.post(f"/api/discovery/actors/{actor}/plan",
                       json={"scope": "missing"}).json() == {"summary": "x"}
    assert client.post(f"/api/discovery/actor-checks/{'b' * 32}/apply").json() == {"run_id": "r"}
    assert [c[0] for c in bridge.calls] == ["plan", "apply"]
    assert bridge.calls[0][2]["scope"] == "missing"
    # The old one-step read-and-write route is gone.
    assert client.post(f"/api/discovery/actors/{actor}/update", json={}).status_code in (404, 405)
