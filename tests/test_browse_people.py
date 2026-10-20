"""Browse -> People: database people only, filtered in memory, no contact details."""
import inspect
import unittest

from src import browse

PEOPLE = [
    {"name": "Ana Silva", "title": "Professor", "organizations": ["FIPR Institute"],
     "states": ["Florida"], "topics": ["Mining"], "research_areas": ["phosphogypsum reuse"]},
    {"name": "Ben Ode", "title": "Director", "organizations": ["ORNL", "FIPR Institute"],
     "states": ["Tennessee", "Florida"], "topics": ["Energy Transition"], "research_areas": []},
    {"name": "Cy Ray", "title": None, "organizations": [], "states": [], "topics": [],
     "research_areas": []},
]


class PeopleTests(unittest.TestCase):
    def names(self, **filters):
        return [p["name"] for p in browse.filter_people(PEOPLE, **filters)]

    def test_each_filter_matches_exact_values(self):
        self.assertEqual(self.names(organization="FIPR Institute"), ["Ana Silva", "Ben Ode"])
        self.assertEqual(self.names(state="Tennessee"), ["Ben Ode"])
        self.assertEqual(self.names(topic="Mining"), ["Ana Silva"])
        self.assertEqual(self.names(organization="FIPR Institute", topic="Energy Transition"), ["Ben Ode"])

    def test_text_searches_name_title_and_expertise(self):
        self.assertEqual(self.names(text="PHOSPHOGYPSUM"), ["Ana Silva"])
        self.assertEqual(self.names(text="director"), ["Ben Ode"])
        self.assertEqual(self.names(text="cy"), ["Cy Ray"])

    def test_options_list_every_value_once(self):
        options = browse.people_filter_options(PEOPLE)
        self.assertEqual(options["organizations"], ["FIPR Institute", "ORNL"])
        self.assertEqual(options["states"], ["Florida", "Tennessee"])
        self.assertEqual(options["topics"], ["Energy Transition", "Mining"])

    def test_contact_details_are_never_read(self):
        sql = inspect.getsource(browse.load_people)
        self.assertNotIn("email", sql)
        self.assertNotIn("tel_num", sql)
        self.assertIn("<> 'rejected'", sql)


if __name__ == "__main__":
    unittest.main()
