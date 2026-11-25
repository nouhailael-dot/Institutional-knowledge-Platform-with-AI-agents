"""Verify or reject from the Ecosystem Directory (re-review, 25 Nov 2026): the platform
asks the backend's approved writer; it never writes a status itself. No database: the
bridge is a stand-in."""
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import backend.app as app
from src.accounts.permissions import ROUTE_POLICY

RECORD = "11111111-2222-3333-4444-555555555555"


class FakeBridge:
    configured = True

    def __init__(self, error=None):
        self.sent, self.error = [], error

    def apply(self, decision):
        self.sent.append(decision)
        if self.error:
            raise app.AdmissionBridgeError(self.error)
        return {"status": "applied",
                "current_status": "verified" if decision["verified"] else "rejected"}


def decide(kind="actors", bridge=None, **body):
    payload = app.DirectoryVerification(**{"verified": True, "confirm": True, **body})
    with patch.object(app, "review_admission_bridge", return_value=bridge or FakeBridge()):
        return app.directory_verify(kind, RECORD, payload)


class DirectoryVerifyTests(unittest.TestCase):
    def test_organizations_events_and_people_go_to_the_backend_writer(self):
        for kind, entity in (("actors", "actor"), ("events", "event"), ("people", "person")):
            bridge = FakeBridge()
            out = decide(kind, bridge=bridge)
            sent = bridge.sent[0]
            self.assertEqual((sent["decision_kind"], sent["entity_type"], sent["entity_id"], sent["verified"]),
                             ("verify_directory_record", entity, RECORD, True))
            self.assertEqual(out["current_status"], "verified")

    def test_hubs_are_not_verified_here(self):
        with self.assertRaises(HTTPException) as raised:
            decide("hubs")
        self.assertEqual(raised.exception.status_code, 404)

    def test_a_rejection_needs_a_reason_and_carries_it(self):
        with self.assertRaises(HTTPException) as raised:
            decide(verified=False, rejection_reason="   ")
        self.assertEqual(raised.exception.status_code, 400)
        bridge = FakeBridge()
        decide(bridge=bridge, verified=False, rejection_reason="  Not in   scope ")
        self.assertEqual(bridge.sent[0]["rejection_reason"], "Not in scope")

    def test_nothing_is_sent_without_confirmation(self):
        bridge = FakeBridge()
        with self.assertRaises(HTTPException):
            decide(bridge=bridge, confirm=False)
        self.assertEqual(bridge.sent, [])

    def test_a_refusal_comes_back_as_a_readable_error(self):
        with self.assertRaises(HTTPException) as raised:
            decide(bridge=FakeBridge("AdmissionValidationError: that record is waiting for deletion"))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("waiting for deletion", raised.exception.detail)

    def test_only_people_who_may_decide_can_call_it(self):
        rule = next(r for r in ROUTE_POLICY if r.template == "/api/browse/{kind}/{record_id}/verify")
        self.assertEqual((rule.method, rule.permission), ("POST", "review.decide"))

    def test_the_record_page_offers_verify_and_reject(self):
        page = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function VerifyPanel", page)
        self.assertIn('data-needs="review.decide" onClick=${()=>{setSaved(null);setDeciding("verify");}}', page)
        self.assertIn("/verify`", page)


if __name__ == "__main__":
    unittest.main()
