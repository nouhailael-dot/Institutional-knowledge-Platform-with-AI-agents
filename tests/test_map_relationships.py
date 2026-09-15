import unittest

from src.map_agent.dedup import deduplicate
from src.map_agent.export import _selected
from src.map_agent.planner import _bounded_tasks
from src.map_agent.relationships import link_people_to_actors


class MapRelationshipTests(unittest.TestCase):
    def test_controlled_plan_keeps_four_distinct_angles(self):
        tasks = [
            {"entity_type": "actor", "query": "a"},
            {"entity_type": "person", "query": "p1"},
            {"entity_type": "person", "query": "p2"},
            {"entity_type": "actor", "query": "b"},
            {"entity_type": "actor", "query": "c"},
            {"entity_type": "actor", "query": "d"},
            {"entity_type": "actor", "query": "e"},
        ]
        bounded = _bounded_tasks(tasks)
        self.assertEqual(len(bounded), 4)
        self.assertEqual(
            sum(t["entity_type"] == "person" for t in bounded), 2)

    def test_plan_deduplicates_queries_and_does_not_mutate_input(self):
        bounded = _bounded_tasks([
            {"entity_type": "person", "query": "p1"},
            {"entity_type": "person", "query": " P1 "},
            {"entity_type": "bad", "query": "p2"},
        ])
        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded[0]["entity_type"], "person")

    def test_actor_dedup_preserves_people_from_multiple_searches(self):
        actors = deduplicate([
            {"_entity_type": "actor", "name": "Example Laboratory",
             "people": [{"full_name": "Ada One", "title": "Director"}]},
            {"_entity_type": "actor", "name": "Example Laboratory",
             "people": [{"full_name": "Ben Two", "title": "Researcher"}]},
        ])
        self.assertEqual(len(actors), 1)
        self.assertEqual(len(actors[0]["people"]), 2)

    def test_same_person_is_attached_to_multiple_organizations(self):
        linked = link_people_to_actors([
            {"_entity_type": "actor", "name": "Alpha University",
             "people": [{"full_name": "Sam Researcher", "title": "Professor"}]},
            {"_entity_type": "actor", "name": "Beta Institute",
             "people": [{"full_name": "Sam Researcher", "title": "Fellow"}]},
        ])
        actors = [e for e in linked if e["_entity_type"] == "actor"]
        people = [e for e in linked if e["_entity_type"] == "person"]
        self.assertEqual(len(people), 1)
        self.assertEqual(len(people[0]["organizations"]), 2)
        self.assertEqual([len(a["people"]) for a in actors], [1, 1])

    def test_legacy_standalone_person_links_from_title(self):
        linked = link_people_to_actors([
            {"_entity_type": "actor", "name": "Gamma Research Center"},
            {"_entity_type": "person", "full_name": "Jo Example",
             "title": "Director, Gamma Research Center"},
        ])
        actor = next(e for e in linked if e["_entity_type"] == "actor")
        self.assertEqual(actor["people"][0]["full_name"], "Jo Example")

    def test_export_keeps_only_people_attached_to_selected_actors(self):
        result = {"entities": {"person": [
            {"full_name": "Selected Person", "_selected": True},
            {"full_name": "Other Person", "_selected": False},
        ]}}
        self.assertEqual(
            [p["full_name"] for p in _selected(result)["person"]],
            ["Selected Person"],
        )


if __name__ == "__main__":
    unittest.main()
