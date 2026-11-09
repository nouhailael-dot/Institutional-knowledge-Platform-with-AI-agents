"""The hosted trial: login protection and the Linux launcher (9 Nov 2026)."""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import access
from scripts import run_hosted_server


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(access.require_login)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/data")
    def data():
        return {"secret": "rows"}

    @app.get("/")
    def home():
        return {"page": "home"}

    return app


def _basic(name: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{name}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("GHUS_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("GHUS_ACCESS_USERS", "amina:first-pass, ismail:pa:ss")
    return TestClient(_app())


def test_accounts_are_read_from_one_variable():
    assert access.accounts("a:1, b:x:y ,broken,:nope,c:") == {"a": "1", "b": "x:y"}


def test_every_page_and_api_call_asks_for_a_login(hosted):
    for path in ("/", "/api/data", "/index.html"):
        response = hosted.get(path)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"].startswith("Basic")
        assert "rows" not in response.text


def test_a_valid_login_opens_it_and_a_wrong_one_does_not(hosted):
    assert hosted.get("/api/data", headers=_basic("amina", "first-pass")).json() == {"secret": "rows"}
    assert hosted.get("/api/data", headers=_basic("ismail", "pa:ss")).status_code == 200
    assert hosted.get("/api/data", headers=_basic("amina", "wrong")).status_code == 401
    assert hosted.get("/api/data", headers=_basic("nobody", "first-pass")).status_code == 401
    assert hosted.get("/api/data", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert hosted.get("/api/data", headers={"Authorization": "Bearer x"}).status_code == 401


def test_the_health_check_is_the_only_open_path(hosted):
    assert hosted.get("/api/health").json() == {"ok": True}


def test_login_required_without_accounts_fails_closed(monkeypatch):
    monkeypatch.setenv("GHUS_REQUIRE_LOGIN", "1")
    monkeypatch.delenv("GHUS_ACCESS_USERS", raising=False)
    response = TestClient(_app()).get("/api/data")
    assert response.status_code == 503
    assert "rows" not in response.text


def test_locally_nothing_changes(monkeypatch):
    monkeypatch.delenv("GHUS_REQUIRE_LOGIN", raising=False)
    monkeypatch.delenv("GHUS_ACCESS_USERS", raising=False)
    assert TestClient(_app()).get("/api/data").status_code == 200


def test_the_real_app_asks_for_a_login(monkeypatch):
    monkeypatch.setenv("GHUS_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("GHUS_ACCESS_USERS", "amina:first-pass")
    from backend.app import app

    client = TestClient(app)
    assert client.get("/").status_code == 401
    assert client.get("/api/health").status_code == 200


# ------------------------------------------------------------- the launcher

def test_launcher_refuses_without_the_disk(tmp_path):
    with pytest.raises(SystemExit, match="not a mounted directory"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path / "missing"),
                                   "DATABASE_URL": "postgresql://u@h/db",
                                   "GHUS_ACCESS_USERS": "a:b"})


def test_launcher_refuses_without_a_login(tmp_path):
    with pytest.raises(SystemExit, match="GHUS_ACCESS_USERS"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path),
                                   "DATABASE_URL": "postgresql://u@h/db"})


def test_launcher_refuses_without_a_database(tmp_path):
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path), "GHUS_ACCESS_USERS": "a:b"})


def test_launcher_keeps_durable_state_on_the_disk(tmp_path):
    settings = run_hosted_server.prepare({
        "GHUS_DATA_DIR": str(tmp_path),
        "DATABASE_URL": "postgresql+psycopg2://user:pw@pooler.example.com:5432/postgres",
        "GHUS_ACCESS_USERS": "a:b"})
    for key in ("REVIEW_STORE_DB", "GHUS_DATAFEED_ORIGINALS", "MAP_RUN_DB"):
        assert settings[key].startswith(str(tmp_path)), key
    assert settings["GHUS_REQUIRE_LOGIN"] == "1"
    assert settings["DISCOVERY_REQUESTS_DATABASE_URL"].startswith("postgresql+psycopg://")
    assert settings["BROWSE_DATABASE_URL"].startswith("postgresql://user:pw@pooler")


def test_agent_folders_are_linked_to_the_disk(tmp_path):
    link = tmp_path / "image" / "runs"
    link.mkdir(parents=True)
    (link / "blocked_sites.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "disk" / "agent-runs"
    try:
        run_hosted_server._on_disk(link, target)
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"symlinks unavailable here: {exc}")
    assert link.is_symlink() and (target / "blocked_sites.json").is_file()
    run_hosted_server._on_disk(link, target)  # a restart changes nothing
    assert link.is_symlink()
