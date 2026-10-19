import unittest
from pathlib import Path

from src.browse import actor_filter_options, filter_actors


class ActorCategoryCompatibilityTests(unittest.TestCase):
    def test_browse_prefers_category_but_accepts_temporary_type_alias(self):
        actors = [
            {
                "name": "V2 Actor",
                "actor_category": "research_center",
                "actor_type": "legacy_wrong_value",
                "hubs": [],
                "country": None,
                "state": None,
                "trl": None,
                "has_profile": False,
                "description": "",
            },
            {
                "name": "Legacy Actor",
                "actor_type": "company",
                "hubs": [],
                "country": None,
                "state": None,
                "trl": None,
                "has_profile": False,
                "description": "",
            },
        ]
        self.assertEqual(
            [row["name"] for row in filter_actors(actors, types=["research_center"])],
            ["V2 Actor"],
        )
        self.assertEqual(
            [row["name"] for row in filter_actors(actors, types=["company"])],
            ["Legacy Actor"],
        )
        self.assertEqual(
            actor_filter_options(actors)["types"], ["company", "research_center"]
        )

    def test_rag_assembly_uses_category_first_dual_read(self):
        source = Path("src/assemble.py").read_text(encoding="utf-8")
        self.assertIn("to_jsonb(a)->>'actor_category'", source)
        self.assertIn("to_jsonb(a)->>'actor_type'", source)
        self.assertIn('_section("Actor category", r["actor_category"])', source)
        self.assertIn('_section("Category type", r["category_type"])', source)

    def test_browse_reads_columns_migration_500_drops_or_renames_through_to_jsonb(self):
        """Browse raised UndefinedColumn on production after 500 and showed no actors."""
        import re

        source = Path("src/browse.py").read_text(encoding="utf-8")
        sql = source[source.index("def load_actors"):source.index("def load_hubs")]
        for column in ("verification_status", "location_city", "estimated_trl"):
            self.assertNotRegex(sql, rf"\ba\.{column}\b")
        self.assertIsNone(re.search(r"\ba\.state\b", sql))
        for column in ("verification_status", "status", "location_city", "city",
                       "state", "state_code", "estimated_trl"):
            self.assertIn(f"to_jsonb(a)->>'{column}'", sql)


if __name__ == "__main__":
    unittest.main()
