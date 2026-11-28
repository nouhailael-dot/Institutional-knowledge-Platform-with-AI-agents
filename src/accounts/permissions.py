"""Who may do what in Compass: the permission catalogue and the route policy.

Roles are configurable in the database (compass.role_permission, migration 700);
this module holds only what the code needs to know:

* PERMISSIONS: every permission the code checks. Each must exist in the
  database catalogue, and a test keeps the two in step.
* DEFAULT_ROLES: the matrix migration 700 seeds. Used by tests and as the
  documented default; at run time the database decides.
* ROUTE_POLICY: the permission every HTTP route needs. The backend checks it
  on every request, so hiding a button is never the only protection. A route
  that is not listed is refused (fail closed), and a test fails when a route
  is added without a policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PUBLIC = "public"          # no sign-in (health check, the sign-in page and call)
SIGNED_IN = "signed_in"    # any active account with a role

PERMISSIONS = {
    "records.view": "Browse the shared organizations, people, events and hubs",
    "ask.use": "Ask Compass questions",
    "maps.view": "Open maps the user may see",
    "dashboard.view": "Open the personal dashboard",
    "usage.view_own": "See one's own usage and costs",
    "maps.create": "Create maps and run paid map research",
    "requests.view": "Open Monitor and Update requests",
    "requests.create": "Create and run Discovery and Update requests (paid agents)",
    "datafeed.import": "Import records through Data Feed",
    "review.view": "Open Review Results",
    "review.decide": "Verify records, and decide in Review Results",
    "records.edit": "Edit shared records",
    "notes.write": "Add and edit GHUS Notes",
    "records.remove": "Remove a record from the Directory, or restore it",
    "records.delete_permanent": "Permanently delete a record (confirmation, dependency checks, audit)",
    "usage.view_all": "See every user's usage, costs and activity",
    "audit.view_all": "Read the full audit history",
    "users.manage": "Invite users, assign roles, activate and deactivate accounts",
    "settings.admin": "Change administrative and security settings",
}

_VIEWER = {"records.view", "ask.use", "maps.view", "dashboard.view", "usage.view_own"}
_EDITOR = _VIEWER | {
    "maps.create", "requests.view", "requests.create", "datafeed.import", "review.view",
    "review.decide", "records.edit", "notes.write", "records.remove", "records.delete_permanent",
}
DEFAULT_ROLES = {
    "admin": frozenset(PERMISSIONS),
    "editor": frozenset(_EDITOR),
    "viewer": frozenset(_VIEWER),
}


@dataclass(frozen=True)
class Rule:
    method: str
    template: str
    permission: str

    @property
    def pattern(self) -> re.Pattern:
        return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(self.template)) + "$")


def _rules(permission: str, *routes: str) -> list[Rule]:
    out = []
    for route in routes:
        method, template = route.split(" ", 1)
        out.append(Rule(method, template.strip(), permission))
    return out


ROUTE_POLICY: list[Rule] = [
    *_rules(PUBLIC, "GET /api/health", "GET /login", "POST /api/auth/login",
            # invitation and password emails: the person is not signed in yet
            "GET /forgot", "GET /accept", "GET /reset",
            "POST /api/auth/recover", "POST /api/auth/accept", "POST /api/auth/reset"),
    *_rules(SIGNED_IN, "GET /", "GET /api/auth/me", "GET /api/me", "POST /api/auth/logout",
            "GET /api/account/profile", "PATCH /api/account/profile", "POST /api/account/password"),
    # My work (one's own records, requests, maps, imports and decisions)
    *_rules("dashboard.view", "GET /api/account/mine", "GET /api/account/review-history",
            "GET /api/account/dashboard"),
    # One's own notifications and preferences (every role)
    *_rules(SIGNED_IN, "GET /api/account/notifications", "POST /api/account/notifications/read-all",
            "POST /api/account/notifications/{notification_id}/read",
            "GET /api/account/preferences", "PUT /api/account/preferences"),
    *_rules("records.view", "GET /api/account/record-trail"),
    # Usage and costs: one's own, and everyone's
    *_rules("usage.view_own", "GET /api/account/usage"),
    *_rules("usage.view_all", "GET /api/admin/usage", "GET /api/admin/usage/export"),
    # The full audit history
    *_rules("audit.view_all", "GET /api/admin/audit"),
    # User management
    *_rules("users.manage",
            "GET /api/admin/users", "POST /api/admin/invitations",
            "POST /api/admin/invitations/{invitation_id}/revoke",
            "POST /api/admin/invitations/{invitation_id}/resend",
            "POST /api/admin/users/{user_id}/role", "POST /api/admin/users/{user_id}/deactivate",
            "POST /api/admin/users/{user_id}/activate"),
    # Ecosystem Directory
    *_rules("records.view",
            "GET /api/browse/actors", "GET /api/browse/actors/removed",
            "GET /api/browse/actors/{actor_id}/profile", "GET /api/browse/events",
            "GET /api/browse/hubs", "GET /api/browse/people",
            # Our US city list for the Directory's City filter (25 Nov 2026).
            "GET /api/reference/cities"),
    *_rules("records.edit", "POST /api/browse/{kind}/{record_id}/edit"),
    # Re-review (25 Nov 2026): verify or reject a record from the Directory.
    *_rules("review.decide", "POST /api/browse/{kind}/{record_id}/verify"),
    *_rules("records.remove", "POST /api/browse/actors/{actor_id}/remove",
            "POST /api/browse/actors/{actor_id}/restore"),
    # Deletion with 30-day retention (Phase 6): delete, list (Pending Deletion), restore.
    # Admins and Editors/Reviewers; kept apart from Review Results' Rejected.
    *_rules("records.delete_permanent", "POST /api/browse/{kind}/{record_id}/delete",
            "GET /api/review/deleted", "POST /api/review/deleted/{deletion_id}/restore"),
    # Ask Compass
    *_rules("ask.use", "GET /api/ask/stream", "POST /api/upload"),
    # Dashboard
    *_rules("dashboard.view", "GET /api/dashboard/start", "GET /api/dashboard/directory-activity"),
    # Everyone's spending by month: admins only (personal pages, 23 Nov 2026).
    *_rules("usage.view_all", "GET /api/dashboard/spending"),
    # Monitor and Update (Discovery and Update requests run paid agents)
    *_rules("requests.view",
            "GET /api/discovery/actors", "GET /api/discovery/options",
            "GET /api/discovery/requests", "GET /api/discovery/status",
            "GET /api/discovery/update-requests"),
    *_rules("requests.create",
            "POST /api/discovery/actor-checks/{check_id}/apply",
            "POST /api/discovery/actors/{actor_id}/check", "POST /api/discovery/actors/{actor_id}/plan",
            "POST /api/discovery/preview", "POST /api/discovery/requests",
            "POST /api/discovery/requests/{subscription_id}/end-date",
            "POST /api/discovery/requests/{subscription_id}/run",
            "POST /api/discovery/requests/{subscription_id}/{action}",
            "POST /api/discovery/update-requests", "POST /api/discovery/update-requests/plan",
            "POST /api/discovery/update-requests/{subscription_id}/{action}",
            "POST /api/map/{job_id}/discovery-brief"),
    # Explore and Map
    *_rules("maps.view", "GET /api/maps", "GET /api/map/{job_id}", "GET /api/map/{job_id}/people",
            "POST /api/map/export"),
    *_rules("maps.create",
            "POST /api/map", "POST /api/map/chat", "POST /api/map/session", "POST /api/map/upload",
            "POST /api/map/verify", "POST /api/ask/handoff",
            "POST /api/map/{job_id}/budget-extension", "POST /api/map/{job_id}/settle-charges",
            "POST /api/map/{job_id}/people",
            "POST /api/map/{job_id}/reopen", "POST /api/map/{job_id}/resume",
            "POST /api/map/{job_id}/stop"),
    # Review Results (and a map's records going to the database)
    *_rules("review.view",
            "GET /api/review/candidates", "GET /api/review/candidates/{candidate_id}",
            "GET /api/review/catalog", "GET /api/review/hub-proposals",
            "GET /api/review/sectors", "GET /api/review/subscriptions"),
    *_rules("review.decide",
            "PATCH /api/review/candidates/{candidate_id}",
            "POST /api/review/candidates/{candidate_id}/approve",
            "POST /api/review/candidates/{candidate_id}/changes/{review_item_id}",
            "POST /api/review/candidates/{candidate_id}/decision",
            "POST /api/review/candidates/{candidate_id}/reject",
            "POST /api/review/candidates/{candidate_id}/review-item-decision",
            "POST /api/review/category-decisions", "POST /api/review/sectors",
            "POST /api/map/{job_id}/review", "POST /api/map/{job_id}/save",
            "POST /api/map/{job_id}/save-check"),
    # Data Feed
    *_rules("datafeed.import",
            "GET /api/datafeed/catalog", "GET /api/datafeed/example-import.xlsx",
            "GET /api/datafeed/history", "GET /api/datafeed/imports/{run_id}",
            "GET /api/datafeed/imports/{run_id}/file", "GET /api/datafeed/previews/{preview_id}",
            "GET /api/datafeed/templates/{record_type}.{extension}",
            "POST /api/datafeed/imports/{run_id}/complete",
            "POST /api/datafeed/imports/{run_id}/estimate",
            "POST /api/datafeed/imports/{run_id}/withdraw",
            "POST /api/datafeed/previews/{preview_id}/confirm",
            "POST /api/datafeed/validate", "POST /api/datafeed/validate-manual"),
]

# The page's own files (scripts, styles, images) need a signed-in account, nothing more.
_STATIC = re.compile(r"^/[A-Za-z0-9_.\-/]+\.(js|css|svg|png|jpg|jpeg|ico|woff2?|webp|map)$")


def rule_for(method: str, path: str) -> tuple[Rule, dict[str, str]] | None:
    """The matching rule and its path values ({candidate_id: ...}), or None."""
    method = "GET" if method.upper() == "HEAD" else method.upper()
    for rule in ROUTE_POLICY:
        if rule.method != method:
            continue
        names = re.findall(r"\{([^}]+)\}", rule.template)
        found = rule.pattern.match(path)
        if found:
            values = re.match("^" + re.sub(r"\\\{[^}]+\\\}", "([^/]+)", re.escape(rule.template)) + "$", path)
            return rule, dict(zip(names, values.groups() if values else ()))
    return None


# What each path value names, for the audit entry's record.
_ENTITY_OF = {"candidate_id": "review_candidate", "job_id": "map", "subscription_id": "request",
              "run_id": "import", "preview_id": "import_preview", "actor_id": "actor",
              "deletion_id": "deletion",
              "check_id": "actor_check", "user_id": "user", "invitation_id": "invitation"}
_KINDS = {"actors": "actor", "events": "event", "people": "person", "hubs": "hub"}


def audit_name(rule: Rule) -> str:
    """'area.verb' for a change: POST /api/review/candidates/{id}/decision ->
    review.candidates_decision; POST /api/map -> map.create."""
    parts = rule.template.split("/")[2:]                 # after "", "api"
    area = parts[0].replace("-", "_")
    words = [p.replace("-", "_").replace(".", "_") for p in parts[1:] if not p.startswith("{")]
    verb = "_".join(words) if words else ("create" if rule.method == "POST" else rule.method.lower())
    return f"{area}.{verb}"


def audit_entity(values: dict[str, str]) -> tuple[str | None, str | None]:
    """(record type, id) named by a route's path values."""
    if "kind" in values and "record_id" in values:
        return _KINDS.get(values["kind"], values["kind"]), values["record_id"]
    for name, kind in _ENTITY_OF.items():
        if name in values:
            return kind, values[name]
    return None, None


def permission_for(method: str, path: str) -> str | None:
    """The permission a request needs, or None when the route has no policy (refuse)."""
    method = method.upper()
    if method == "HEAD":
        method = "GET"
    for rule in ROUTE_POLICY:
        if rule.method == method and rule.pattern.match(path):
            return rule.permission
    if method == "GET" and not path.startswith("/api/") and _STATIC.match(path):
        return SIGNED_IN
    return None
