"""The first Compass administrator (accounts activation).

Used once, by the person activating accounts, from the server's shell:
``python -m scripts.bootstrap_admin``. It only *invites*: the person still
accepts by email and chooses their own password, so no password ever passes
through a terminal or a log.

Refuses when Compass already has an active administrator (then use the Users
page) or when a first-administrator invitation is still open. Dry run unless
``live`` is set, and live needs the address typed twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.accounts.policy import clean_email, clean_name
from src.accounts.store import AccountError, AccountsStore
from src.accounts.supabase_auth import AuthError, SupabaseAuth


@dataclass
class BootstrapResult:
    ready: bool          # every check passed
    sent: bool           # an invitation was sent (live only)
    lines: list[str]


def bootstrap_admin(store: AccountsStore, auth: SupabaseAuth, *, email: str, full_name: str,
                    confirm_email: str | None, site_url: str, days: float = 3,
                    live: bool = False) -> BootstrapResult:
    lines: list[str] = []
    address, name = clean_email(email), clean_name(full_name)
    if address is None or name is None:
        return BootstrapResult(False, False, ["Refused: give a valid email and a name."])
    managers = store.active_manager_count()
    pending = store.open_bootstrap_invitations()
    lines.append(f"Active administrators now: {managers}")
    lines.append(f"Open first-administrator invitations: {pending}")
    lines.append(f"Supabase Auth: {'configured' if auth.settings.configured else 'NOT configured'}; "
                 f"server key {'present' if auth.settings.service_role_key else 'MISSING'}")
    if managers:
        return BootstrapResult(False, False, lines + [
            "Refused: Compass already has an administrator. Invite people from the Users page."])
    if pending:
        return BootstrapResult(False, False, lines + [
            "Refused: a first-administrator invitation is still open. It must be accepted, or "
            "it expires; then run this again."])
    if not (auth.settings.configured and auth.settings.service_role_key):
        return BootstrapResult(False, False, lines + ["Refused: Supabase Auth settings are missing."])
    try:
        store.check_can_invite(address)
    except AccountError as exc:
        return BootstrapResult(False, False, lines + [f"Refused: {exc.message}"])
    plan = (f"Would invite {name} <{address}> as the first Admin; the link expires in {days:g} days "
            f"and opens {site_url}/accept.")
    if not live:
        return BootstrapResult(True, False, lines + [plan, "Dry run: nothing was sent. Add --live "
                                                           "and --confirm-email to send it."])
    if (confirm_email or "").strip().lower() != address:
        return BootstrapResult(False, False, lines + [
            "Refused: --confirm-email must repeat the same address exactly."])
    try:
        user_id = auth.invite(address, full_name=name, redirect_to=f"{site_url}/accept")
    except AuthError as exc:
        return BootstrapResult(False, False, lines + [f"Refused by Supabase Auth: {exc.message}"])
    try:
        invitation = store.record_invitation(user_id=user_id, email=address, full_name=name,
                                             role_code="admin", invited_by=None, days=days,
                                             bootstrap=True)
    except Exception as exc:
        auth.delete_user(user_id)
        return BootstrapResult(False, False, lines + [f"Not recorded, nothing kept: {exc}"])
    store.audit(action="admin.bootstrap_invited", account=None, label="Compass setup",
                entity_type="user", entity_id=user_id,
                detail={"email": address, "expires_at": invitation["expires_at"]})
    return BootstrapResult(True, True, lines + [
        f"Invitation sent to {address}. It expires {invitation['expires_at']:%Y-%m-%d %H:%M} UTC. "
        "They choose their own password from the email."])
