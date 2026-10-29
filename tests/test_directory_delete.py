"""Delete in the Ecosystem Directory (29 Oct 2026): the platform asks the
backend's decision writer; it never writes or wipes a record itself.
No database: the bridge is a stand-in."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import backend.app as app
from src import browse

ACTOR = "11111111-2222-3333-4444-555555555555"


class FakeBridge:
    configured = True

    def __init__(self):
        self.sent = []

    def apply(self, decision):
        self.sent.append(decision)
        return {"status": "applied", "current_status": "rejected"}


def call(kind="remove_from_directory", bridge=None, **body):
    payload = app.DirectoryDecision(**{"reason": "Duplicate", "confirm": True, **body})
    with patch.object(app, "review_admission_bridge", return_value=bridge or FakeBridge()):
        return app._directory_decision(kind, ACTOR, payload)


class DirectoryDeleteTests(unittest.TestCase):
    def test_a_removal_goes_to_the_backend_with_its_reason_and_the_current_user(self):
        bridge = FakeBridge()
        with patch.object(app._actors, "cache_clear") as cleared:
            call(bridge=bridge)
        sent = bridge.sent[0]
        self.assertEqual((sent["decision_kind"], sent["entity_type"], sent["entity_id"]),
                         ("remove_from_directory", "actor", ACTOR))
        # Nobody types a name: no accounts yet, so the placeholder; later the signed-in user.
        self.assertEqual((sent["reviewer"], sent["reason"]), ("Not recorded (no sign-in yet)", "Duplicate"))
        cleared.assert_called_once()   # the Directory list is read again

    def test_reason_and_confirmation_are_required(self):
        for body, word in (({"reason": ""}, "reason"), ({"confirm": False}, "Confirm")):
            with self.subTest(body=body), self.assertRaises(HTTPException) as raised:
                call(**body)
            self.assertIn(word, raised.exception.detail)

    def test_restoring_needs_no_reason(self):
        bridge = FakeBridge()
        call("restore_to_directory", bridge=bridge, reason="")
        self.assertEqual(bridge.sent[0]["decision_kind"], "restore_to_directory")

    def test_it_says_when_this_computer_cannot_delete(self):
        unconfigured = SimpleNamespace(configured=False)
        with self.assertRaises(HTTPException) as raised:
            call(bridge=unconfigured)
        self.assertEqual(raised.exception.status_code, 503)

    def test_the_removed_list_only_reads(self):
        sql = inspect.getsource(browse.load_removed_actors)
        self.assertIn("status = 'rejected'", sql)
        self.assertIn("REMOVED_REASON_PREFIX", sql)


if __name__ == "__main__":
    unittest.main()
