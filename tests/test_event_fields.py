"""Event fields asked for on 20 Oct 2026: frequency, format, scale, audience,
sector from the shared list, and a one-sentence "why it matched"."""
import unittest
from unittest.mock import patch

from src.map_agent import export, research
from src.map_agent.entity_schemas import EVENT_FORMATS, FREQUENCIES, submit_entities_tool

SECTORS = ["Mining", "Water"]


def event_props(sectors=None):
    return submit_entities_tool("event", sectors)["input_schema"]["properties"]["entities"]["items"]["properties"]


class SchemaTests(unittest.TestCase):
    def test_new_fields_use_the_database_names(self):
        props = event_props()
        for field in ("recurring_pattern", "expected_attendance", "audience", "event_format"):
            self.assertIn(field, props)
        self.assertEqual(props["recurring_pattern"]["enum"], FREQUENCIES)
        self.assertEqual(props["event_format"]["enum"], EVENT_FORMATS)

    def test_the_sector_list_applies_only_when_given(self):
        self.assertEqual(event_props(SECTORS)["sector"]["enum"], ["Mining", "Water", "Not found"])
        self.assertNotIn("enum", event_props()["sector"])
        actor = submit_entities_tool("actor", SECTORS)["input_schema"]["properties"]["entities"]["items"]
        self.assertNotIn("enum", actor["properties"].get("sector", {}))  # organizations unchanged

    def test_why_it_matched_is_one_sentence_and_the_role_is_named(self):
        props = event_props()
        self.assertIn("one short sentence", props["match_explanation"]["description"])
        self.assertIn("sponsor, speaker", props["um6p_ocp_detail"]["description"])


class NormalizationTests(unittest.TestCase):
    def test_synonyms_map_and_anything_else_is_not_found(self):
        cases = [({"recurring_pattern": "yearly", "event_format": "online"}, ("Annual", "Virtual")),
                 ({"recurring_pattern": "ANNUAL", "event_format": "In person"}, ("Annual", "In-person")),
                 ({"recurring_pattern": "biannual", "event_format": "sometimes"}, ("Not found", "Not found"))]
        for event, expected in cases:
            with self.subTest(event=dict(event)):
                research._event_fields(event)
                self.assertEqual((event["recurring_pattern"], event["event_format"]), expected)

    def test_an_off_list_sector_moves_to_the_topic(self):
        event = {"sector": "critical minerals / national security", "thematic_focus": "mine waste"}
        research._event_fields(event, SECTORS)
        self.assertEqual(event["sector"], "Not found")
        self.assertEqual(event["thematic_focus"], "mine waste; critical minerals / national security")
        listed = {"sector": "mining", "thematic_focus": "phosphogypsum"}
        research._event_fields(listed, SECTORS)
        self.assertEqual((listed["sector"], listed["thematic_focus"]), ("Mining", "phosphogypsum"))

    def test_without_the_list_the_sector_is_left_alone(self):
        event = {"sector": "critical minerals"}
        research._event_fields(event, None)
        self.assertEqual(event["sector"], "critical minerals")

    def test_the_list_comes_from_discovery_and_survives_a_database_failure(self):
        with patch("src.map_agent.discovery_brief.sectors", return_value={"Mining": "MINING"}):
            self.assertEqual(research.event_sectors(), ["Mining"])
        with patch("src.map_agent.discovery_brief.sectors", side_effect=RuntimeError("db down")):
            self.assertIsNone(research.event_sectors())


class ExportTests(unittest.TestCase):
    def test_export_names_the_new_columns(self):
        labels = dict(export.FIELDS["event"])
        self.assertEqual(labels["recurring_pattern"], "Frequency")
        self.assertEqual((labels["expected_attendance"], labels["audience"], labels["event_format"]),
                         ("Scale", "Audience", "Format"))
        self.assertNotIn("Recurs", labels.values())

if __name__ == "__main__":
    unittest.main()
