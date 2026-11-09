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

    @app.post("/api/change")
    def change():
        return {"changed": True}

    return app


def _basic(name: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{name}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("GHUS_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("GHUS_ACCESS_USERS", "amina:first-pass, ismail:pa:ss")
    monkeypatch.setattr(access, "FAILURES", access.FailedSignIns())
    return TestClient(_app())


def test_accounts_are_read_from_one_variable():
    assert access.accounts("a:1, b:x:y ,broken,:nope,c:") == {"a": "1", "b": "x:y"}
    assert access.accounts("Amina@GHUS.org:pw") == {"amina@ghus.org": "pw"}


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


def test_an_email_name_signs_in_whatever_its_case(hosted, monkeypatch):
    monkeypatch.setenv("GHUS_ACCESS_USERS", "amina@ghus.org:first-pass")
    assert hosted.get("/api/data", headers=_basic("Amina@GHUS.org", "first-pass")).status_code == 200
    assert hosted.get("/api/data", headers=_basic("amina@ghus.org", "First-pass")).status_code == 401


def test_wrong_passwords_lock_the_name_for_a_while(hosted):
    for n in range(access.MAX_FAILURES_PER_NAME):
        assert hosted.get("/api/data", headers=_basic("amina", f"guess-{n}")).status_code == 401
    locked = hosted.get("/api/data", headers=_basic("amina", "first-pass"))
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert "rows" not in locked.text
    # Another account is not locked by it.
    assert hosted.get("/api/data", headers=_basic("ismail", "pa:ss")).status_code == 200


def test_one_stale_password_repeated_is_one_failure(hosted):
    for _ in range(3 * access.MAX_FAILURES_PER_NAME):
        assert hosted.get("/api/data", headers=_basic("amina", "old-pass")).status_code == 401
    assert hosted.get("/api/data", headers=_basic("amina", "first-pass")).status_code == 200


def test_the_lock_ends_when_the_window_passes():
    now = [1000.0]
    limits = access.FailedSignIns(window=60, per_name=2, per_client=10, clock=lambda: now[0])
    limits.failed("amina", "1.2.3.4", "a")
    limits.failed("amina", "1.2.3.4", "b")
    assert limits.retry_after("amina", "1.2.3.4") > 0
    assert limits.retry_after("ismail", "5.6.7.8") == 0
    now[0] += 61
    assert limits.retry_after("amina", "1.2.3.4") == 0


def test_many_names_from_one_address_lock_the_address():
    limits = access.FailedSignIns(window=60, per_name=5, per_client=3)
    for n in range(3):
        limits.failed(f"name-{n}", "1.2.3.4", "x")
    assert limits.retry_after("someone-else", "1.2.3.4") > 0
    assert limits.retry_after("someone-else", "9.9.9.9") == 0


def test_a_change_sent_from_another_site_is_refused(hosted):
    login = _basic("amina", "first-pass")
    assert hosted.post("/api/change", headers=login).status_code == 200            # a script
    assert hosted.post("/api/change", headers={**login, "Origin": "http://testserver"}).status_code == 200
    for origin in ("https://evil.example", "null", "http://testserver.evil.example"):
        refused = hosted.post("/api/change", headers={**login, "Origin": origin})
        assert refused.status_code == 403, origin
        assert "changed" not in refused.text
    # Reading is not affected.
    assert hosted.get("/api/data", headers={**login, "Origin": "https://evil.example"}).status_code == 200


def test_pages_cannot_be_framed_by_another_site(hosted):
    response = hosted.get("/api/data", headers=_basic("amina", "first-pass"))
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "private"


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

def _env(tmp_path, **extra):
    return {"GHUS_DATA_DIR": str(tmp_path), "DATABASE_URL": "postgresql://u@h/db",
            "GHUS_ACCESS_USERS": "a:long-enough-password-1", **extra}


def test_launcher_refuses_a_short_password(tmp_path):
    with pytest.raises(SystemExit, match="shorter than 12 characters for: bob") as refused:
        run_hosted_server.prepare(_env(tmp_path, GHUS_ACCESS_USERS="amina:long-enough-password-1,bob:short"))
    assert "long-enough" not in str(refused.value)                 # names only, never a password


def _store(path, decisions=1):
    import sqlite3
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE review_candidate (candidate_id TEXT)")
        db.execute("CREATE TABLE review_decision (decision_id TEXT)")
        db.executemany("INSERT INTO review_decision VALUES (?)", [(str(n),) for n in range(decisions)])
    db.close()


def _decisions(path):
    import sqlite3
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT count(*) FROM review_decision").fetchone()[0]
    finally:
        db.close()


def test_an_uploaded_store_replaces_the_store_at_start_and_the_old_one_is_kept(tmp_path):
    store = tmp_path / "review-store" / "review-shared.sqlite3"
    store.parent.mkdir(parents=True)
    _store(store, decisions=0)
    _store(store.with_name(store.name + ".incoming"), decisions=7)
    run_hosted_server.prepare(_env(tmp_path))
    assert _decisions(store) == 7
    assert not store.with_name(store.name + ".incoming").exists()
    kept = list((store.parent / "replaced").glob("*/review-shared.sqlite3"))
    assert len(kept) == 1 and _decisions(kept[0]) == 0


def test_a_broken_upload_is_not_used(tmp_path):
    store = tmp_path / "review-store" / "review-shared.sqlite3"
    store.parent.mkdir(parents=True)
    _store(store, decisions=3)
    store.with_name(store.name + ".incoming").write_bytes(b"not a database")
    run_hosted_server.prepare(_env(tmp_path))
    assert _decisions(store) == 3
    assert store.with_name(store.name + ".incoming.rejected").exists()

def test_launcher_refuses_without_the_disk(tmp_path):
    with pytest.raises(SystemExit, match="not a mounted directory"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path / "missing"),
                                   "DATABASE_URL": "postgresql://u@h/db",
                                   "GHUS_ACCESS_USERS": "a:long-enough-password-1"})


def test_launcher_refuses_without_a_login(tmp_path):
    with pytest.raises(SystemExit, match="GHUS_ACCESS_USERS"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path),
                                   "DATABASE_URL": "postgresql://u@h/db"})


def test_launcher_refuses_without_a_database(tmp_path):
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        run_hosted_server.prepare({"GHUS_DATA_DIR": str(tmp_path), "GHUS_ACCESS_USERS": "a:long-enough-password-1"})


def test_launcher_keeps_durable_state_on_the_disk(tmp_path):
    settings = run_hosted_server.prepare({
        "GHUS_DATA_DIR": str(tmp_path),
        "DATABASE_URL": "postgresql+psycopg2://user:pw@pooler.example.com:5432/postgres",
        "GHUS_ACCESS_USERS": "a:long-enough-password-1"})
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


def test_the_dashboard_start_comes_from_the_host(monkeypatch):
    from backend.app import app

    monkeypatch.delenv("GHUS_REQUIRE_LOGIN", raising=False)
    monkeypatch.delenv("GHUS_ACCESS_USERS", raising=False)
    client = TestClient(app)
    monkeypatch.delenv("GHUS_DASHBOARD_SINCE", raising=False)
    assert client.get("/api/dashboard/start").json() == {"since": None}
    monkeypatch.setenv("GHUS_DASHBOARD_SINCE", "2026-11-10")
    assert client.get("/api/dashboard/start").json() == {"since": "2026-11-10T00:00:00Z"}
    monkeypatch.setenv("GHUS_DASHBOARD_SINCE", "2026-11-10T09:30:00+01:00")
    assert client.get("/api/dashboard/start").json() == {"since": "2026-11-10T08:30:00Z"}
    monkeypatch.setenv("GHUS_DASHBOARD_SINCE", "next week")
    assert client.get("/api/dashboard/start").json() == {"since": None}
