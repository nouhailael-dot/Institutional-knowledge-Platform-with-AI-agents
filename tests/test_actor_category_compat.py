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


if __name__ == "__main__":
    unittest.main()
