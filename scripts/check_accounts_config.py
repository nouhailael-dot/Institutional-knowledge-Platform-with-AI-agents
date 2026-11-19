"""Check the individual-accounts settings without printing any secret. Read-only.

    python -m scripts.check_accounts_config

Reports which settings are present and well formed, whether the email
templates link to Compass's own pages with a single-use code, and whether the
accounts tables and an administrator exist. Exit code 1 when something blocks
activation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {"invite.html": "/accept?token_hash={{ .TokenHash }}&type=invite",
             "recovery.html": "/reset?token_hash={{ .TokenHash }}&type=recovery"}


def checks(environ=None) -> list[tuple[bool, str]]:
    env = os.environ if environ is None else environ
    out: list[tuple[bool, str]] = []
    url = env.get("SUPABASE_URL", "")
    out.append((url.startswith("https://") and url.endswith(".supabase.co"),
                "SUPABASE_URL is the project's https://<project>.supabase.co address"))
    for key in ("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        out.append((len(env.get(key, "")) >= 32, f"{key} is set"))
    # Optional: a project on asymmetric signing keys has no JWT secret; Compass then asks
    # Supabase Auth to confirm each token (cached briefly).
    secret = env.get("SUPABASE_JWT_SECRET", "")
    out.append((not secret or len(secret) >= 32,
                "SUPABASE_JWT_SECRET " + ("is set: tokens verified locally (HS256)" if secret
                                          else "is not set: Supabase Auth confirms each token")))
    out.append((len(env.get("GHUS_SESSION_KEY", "")) >= 32, "GHUS_SESSION_KEY is set (32+ characters)"))
    public = env.get("GHUS_PUBLIC_URL", "")
    out.append((public.startswith("https://"), "GHUS_PUBLIC_URL is the https:// address of Compass"))
    for name, link in TEMPLATES.items():
        text = (ROOT / "docs" / "supabase-auth" / name).read_text(encoding="utf-8")
        out.append((link in text and "ConfirmationURL }}\"" not in text and "href=\"{{ .ConfirmationURL" not in text,
                    f"template {name} links to Compass with a single-use code"))
    return out


def main() -> int:
    results = checks()
    for ok, text in results:
        print(f"{'ok ' if ok else 'NO '} {text}")
    try:
        from src.accounts.store import AccountsStore
        store = AccountsStore()
        managers = store.active_manager_count()
        print(f"ok  accounts tables reachable; active administrators: {managers}")
    except Exception as exc:
        print(f"NO  accounts tables not reachable ({type(exc).__name__}); is migration 700 applied?")
        results.append((False, "tables"))
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if url:
        try:
            import httpx
            answer = httpx.get(f"{url}/auth/v1/health", timeout=10,
                               headers={"apikey": os.environ.get("SUPABASE_ANON_KEY", "")})
            print(f"{'ok ' if answer.status_code == 200 else 'NO '} Supabase Auth answers (HTTP {answer.status_code})")
            if answer.status_code != 200:
                results.append((False, "auth"))
        except Exception as exc:
            print(f"NO  Supabase Auth not reachable ({type(exc).__name__})")
            results.append((False, "auth"))
    try:
        from src.accounts.store import AccountsStore
        with AccountsStore().connect() as conn:
            found = conn.execute("SELECT to_regclass('compass.deleted_record') IS NOT NULL").fetchone()[0]
        print(f"{'ok ' if found else '-- '} record deletion (migration 710) {'applied' if found else 'not applied'}")
    except Exception:
        pass
    purge = os.environ.get("GHUS_PURGE_MODE", "off") or "off"
    print(f"--  GHUS_PURGE_MODE is {purge} (permanent removal {'ON' if purge == 'live' else 'off'})")
    mode = os.environ.get("GHUS_AUTH_MODE", "")
    print(f"--  GHUS_AUTH_MODE is {'supabase (accounts ON)' if mode == 'supabase' else 'unset (shared login)'}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
