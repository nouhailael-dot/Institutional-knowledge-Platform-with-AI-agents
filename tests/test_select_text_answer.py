"""Selection that the model returned as JSON text (3 Nov 2026 map crash)."""
import json
import unittest

from src.map_agent.select import _selection_lists


class SelectionAsTextTests(unittest.TestCase):
    INNER = {"selected": [{"id": 1, "why": "fits"}], "excluded": [{"id": 7, "reason": "off topic"}]}

    def test_whole_answer_nested_as_text_under_selected(self):
        self.assertEqual(_selection_lists({"selected": json.dumps(self.INNER)}),
                         (self.INNER["selected"], self.INNER["excluded"]))

    def test_text_with_a_stray_tail_is_read_up_to_its_end(self):
        self.assertEqual(_selection_lists({"selected": json.dumps(self.INNER) + "\n</invoke>"})[0],
                         self.INNER["selected"])

    def test_normal_structured_answer_is_unchanged(self):
        self.assertEqual(_selection_lists({"selected": [{"id": 2}], "excluded": []}), ([{"id": 2}], []))

    def test_unreadable_text_is_reported_not_treated_as_nothing_selected(self):
        self.assertEqual(_selection_lists({"selected": "broken"}), (None, None))

    def test_items_that_are_not_records_are_skipped(self):
        self.assertEqual(_selection_lists({"selected": [{"id": 1}, "id 2"], "excluded": ["x"]}), ([{"id": 1}], []))


if __name__ == "__main__":
    unittest.main()
