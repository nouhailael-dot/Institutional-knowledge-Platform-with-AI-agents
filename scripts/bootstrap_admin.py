"""Invite the first Compass administrator. Dry run unless --live.

    python -m scripts.bootstrap_admin --email ana@um6p.ma --name "Ana Example"
    python -m scripts.bootstrap_admin --email ana@um6p.ma --name "Ana Example" \
        --live --confirm-email ana@um6p.ma

Reads Supabase Auth and the database from the environment (the host's
secrets). Refuses when an administrator exists or a first invitation is open.
See docs/ACCOUNTS_ACTIVATION.md. Prints no secret.
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invite the first Compass administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--days", type=float, default=3, help="invitation lifetime (default 3)")
    parser.add_argument("--site", default=os.environ.get("GHUS_PUBLIC_URL", ""),
                        help="the public address of Compass (default GHUS_PUBLIC_URL)")
    parser.add_argument("--live", action="store_true", help="send the invitation (default: dry run)")
    parser.add_argument("--confirm-email", default=None, help="repeat the address (required with --live)")
    args = parser.parse_args(argv)
    if not args.site.startswith("https://") and not args.site.startswith("http://127.0.0.1"):
        parser.error("--site (or GHUS_PUBLIC_URL) must be the https:// address of Compass")

    from src.accounts.bootstrap import bootstrap_admin
    from src.accounts.store import AccountsStore
    from src.accounts.supabase_auth import AuthSettings, SupabaseAuth

    result = bootstrap_admin(AccountsStore(), SupabaseAuth(AuthSettings.from_env()),
                             email=args.email, full_name=args.name, confirm_email=args.confirm_email,
                             site_url=args.site.rstrip("/"), days=max(1 / 24, min(args.days, 14)),
                             live=args.live)
    for line in result.lines:
        print(line)
    return 0 if result.ready else 1


if __name__ == "__main__":
    sys.exit(main())
