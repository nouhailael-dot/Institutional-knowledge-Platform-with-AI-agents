"""Edit in the Ecosystem Directory (10 Nov 2026): the platform asks the backend's
approved writer to save; it never writes a record itself. No database: the
bridge is a stand-in."""
import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import backend.app as app

RECORD = "11111111-2222-3333-4444-555555555555"


class FakeBridge:
    configured = True

    def __init__(self, error=None):
        self.sent, self.error = [], error

    def apply(self, decision):
        self.sent.append(decision)
        if self.error:
            raise app.AdmissionBridgeError(self.error)
        return {"status": "applied", "changed": sorted(decision["changes"])}


def save(kind="actors", bridge=None, **body):
    payload = app.DirectoryEdit(**{"changes": {"name": "Prairie Water Lab"}, **body})
    with patch.object(app, "review_admission_bridge", return_value=bridge or FakeBridge()):
        return app.directory_edit(kind, RECORD, payload)


class DirectoryEditTests(unittest.TestCase):
    def test_each_tab_sends_its_record_type_to_the_backend_writer(self):
        for kind, entity in (("actors", "actor"), ("events", "event"),
                             ("people", "person"), ("hubs", "hub")):
            bridge = FakeBridge()
            save(kind, bridge=bridge, ghus_notes="Met at CES")
            sent = bridge.sent[0]
            self.assertEqual((sent["decision_kind"], sent["entity_type"], sent["entity_id"]),
                             ("edit_directory_record", entity, RECORD))
            self.assertEqual(sent["changes"], {"name": "Prairie Water Lab"})
            self.assertEqual(sent["ghus_notes"], "Met at CES")
            self.assertEqual(sent["reviewer"], "Not recorded (no sign-in yet)")

    def test_every_list_is_read_again_after_a_save(self):
        caches = [app._actors, app._hubs, app._events, app._people]
        with patch.object(app._actors, "cache_clear") as a, patch.object(app._hubs, "cache_clear") as h, \
                patch.object(app._events, "cache_clear") as e, patch.object(app._people, "cache_clear") as p:
            save()
        for cleared in (a, h, e, p):
            cleared.assert_called_once()
        self.assertEqual(len(caches), 4)

    def test_a_refusal_comes_back_as_a_readable_error(self):
        with self.assertRaises(HTTPException) as raised:
            save(bridge=FakeBridge("AdmissionValidationError: unknown US state: Atlantis"))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("unknown US state", raised.exception.detail)

    def test_unknown_types_and_empty_saves_are_refused(self):
        with self.assertRaises(HTTPException) as raised:
            save("sectors")
        self.assertEqual(raised.exception.status_code, 404)
        with self.assertRaises(HTTPException) as raised:
            save(changes={}, ghus_notes=None)
        self.assertEqual(raised.exception.status_code, 400)

    def test_people_s_notes_are_read_for_the_directory(self):
        # Migration 625 put person.ghus_notes on Supabase; read through to_jsonb so
        # a database without it still loads.
        from src import browse
        source = inspect.getsource(browse.load_people)
        self.assertIn("NULLIF(to_jsonb(p)->>'ghus_notes', '') AS ghus_notes", source)
        self.assertIn('"ghus_notes": r["ghus_notes"]', source)

    def test_the_route_never_writes_the_database_itself(self):
        source = inspect.getsource(app.directory_edit)
        self.assertIn("bridge.apply", source)
        for word in ("UPDATE ", "INSERT ", "execute("):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
