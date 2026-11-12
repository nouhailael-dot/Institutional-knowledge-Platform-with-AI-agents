"""scripts.mark_verified: the one-time Verified correction, run by hand (13 Nov 2026)."""


def test_it_runs_the_approved_writer_with_the_hosted_database_address(monkeypatch):
    from scripts import mark_verified

    calls = []
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@db.example:5432/postgres")
    run = lambda command, **kw: calls.append((command, kw)) or type("D", (), {"returncode": 0})()
    assert mark_verified.main([], run=run) == 0
    command, kw = calls[0]
    assert command[1:] == ["-m", "agents.enrichment.decisions"]          # a dry run by default
    assert kw["env"]["DATABASE_URL"] == "postgresql+psycopg://u:p@db.example:5432/postgres"
    assert kw["cwd"].name == "ghus-backend"
    assert mark_verified.main(["--live"], run=run) == 0 and calls[1][0][-1] == "--live"
    assert mark_verified.main(["--everything"], run=run) == 2 and len(calls) == 2
