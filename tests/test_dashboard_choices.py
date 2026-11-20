"""What My profile lets each person show or hide on the Dashboard (GHUS, 20 Nov 2026).

The original Dashboard is kept, with Notifications and Pending Deletion added; the
choices follow the role, and preferences saved for the earlier personal Dashboard
still load. No database.
"""

from src.accounts.preferences import DASHBOARD_SECTIONS, dashboard_choices


def test_a_viewer_is_offered_only_what_a_viewer_sees():
    assert dashboard_choices(["records.view", "dashboard.view", "maps.view"]) == [
        "summary", "notifications", "maps", "directory"]


def test_an_editor_or_admin_is_offered_every_part():
    assert dashboard_choices(["requests.view", "records.delete_permanent"]) == [
        "summary", "spending", "notifications", "deletions", "maps", "requests", "directory"]


def test_choices_saved_before_still_load():
    for earlier in ("runs", "activity", "records", "imports", "reviews", "sectors"):
        assert earlier in DASHBOARD_SECTIONS
    assert set(dashboard_choices(["requests.view", "records.delete_permanent"])) <= set(DASHBOARD_SECTIONS)
