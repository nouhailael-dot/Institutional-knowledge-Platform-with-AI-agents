"""Offline contracts for the simplified map entry point and shared schemas."""
import inspect
import unittest
from unittest.mock import patch

from src.map_agent.pipeline import build_map
from src.map_agent.entity_schemas import submit_entities_tool


class EntryPointTests(unittest.TestCase):
    def test_delegates_plan_and_tracked_context_without_changes(self):
        plan, run, result = {"tasks": []}, object(), {"entities": {}}
        with patch("src.map_agent.pipeline.build_controlled_map", return_value=result) as workflow:
            self.assertIs(build_map("Topic", plan=plan, run=run), result)
        workflow.assert_called_once_with("Topic", plan, run)

    def test_entrypoint_has_no_ignored_legacy_arguments(self):
        self.assertEqual(list(inspect.signature(build_map).parameters),
                         ["description", "plan", "run"])

    def test_shared_schemas_preserve_entity_limits_and_sources(self):
        for kind, limit in [("actor", 10), ("person", 8), ("event", 8)]:
            tool = submit_entities_tool(kind)
            self.assertEqual(tool["name"], "submit_entities")
            rows = tool["input_schema"]["properties"]["entities"]
            self.assertEqual(rows["maxItems"], limit)
            self.assertIn("sources", rows["items"]["properties"])
        actor = submit_entities_tool("actor")["input_schema"]["properties"]["entities"]["items"]
        self.assertIn("location_city", actor["properties"])
        self.assertIn("people", actor["properties"])
        person = submit_entities_tool("person")["input_schema"]["properties"]["entities"]["items"]
        self.assertIn("organization_name", person["required"])
