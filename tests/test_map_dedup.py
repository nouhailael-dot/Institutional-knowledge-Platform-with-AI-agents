"""Duplicate rules for organizations, using cases seen in saved maps."""
import unittest

from src.map_agent.dedup import deduplicate


def org(name, website=None, other_names=None):
    return {"_entity_type": "actor", "name": name, "website": website, "other_names": other_names}


class OrganizationDuplicateTests(unittest.TestCase):
    def test_bracketed_short_name_matching_an_alternate_name_merges(self):
        out = deduplicate([
            org("Florida Industrial and Phosphate Research Institute (FIPR Institute), "
                "Florida Polytechnic University", other_names="FIPR Institute"),
            org("Florida Industrial & Phosphate Research Institute (FIPR Institute)",
                "https://floridapoly.edu/research/institutes/fipr/", "FIPR")])
        self.assertEqual(len(out), 1)
        self.assertIn("Florida Industrial & Phosphate Research Institute (FIPR Institute)",
                      out[0]["other_names"])
        self.assertEqual(out[0]["website"], "https://floridapoly.edu/research/institutes/fipr/")

    def test_the_same_words_in_another_order_merge(self):
        out = deduplicate([
            org("University of Florida Department of Environmental Engineering Sciences"),
            org("Department of Environmental Engineering Sciences, University of Florida")])
        self.assertEqual(len(out), 1)

    def test_a_short_bracketed_abbreviation_merges(self):
        self.assertEqual(len(deduplicate([org("University of Florida"),
                                          org("University of Florida (UF)")])), 1)

    def test_organizations_found_on_the_same_page_stay_separate(self):
        page = "https://engineering.nyu.edu/research/labs-and-groups"
        out = deduplicate([org("Brooklyn Application, Architecture, and Hardware Lab (BAAHL)", page),
                           org("Sustainable Energy Transitions (SET) Group", page)])
        self.assertEqual(len(out), 2)
        self.assertFalse(any(o.get("_possible_duplicates") for o in out))

    def test_similar_names_are_marked_not_merged(self):
        out = deduplicate([org("Oak Ridge National Laboratory"), org("Oak Ridge National Lab")])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["_possible_duplicates"], ["Oak Ridge National Lab"])
        self.assertEqual(out[1]["_possible_duplicates"], ["Oak Ridge National Laboratory"])

    def test_similar_names_on_the_same_homepage_merge(self):
        out = deduplicate([org("Oak Ridge National Laboratory", "https://www.ornl.gov/"),
                           org("Oak Ridge National Lab", "https://ornl.gov")])
        self.assertEqual(len(out), 1)

    def test_an_alternate_name_equal_to_another_record_is_only_marked(self):
        out = deduplicate([
            org("Department of Environmental Engineering Sciences, University of Florida",
                other_names="Engineering School of Sustainable Infrastructure & Environment (ESSIE)"),
            org("Engineering School of Sustainable Infrastructure & Environment (ESSIE)")])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(o.get("_possible_duplicates") for o in out))

    def test_a_long_bracket_describes_a_unit_and_is_only_marked(self):
        out = deduplicate([
            org("New Mexico State University (NM Water Resources Research Institute / "
                "Dept. of Civil Engineering - Pei Xu lab)"),
            org("New Mexico State University")])
        self.assertEqual(len(out), 2)

    def test_units_sharing_a_parent_in_brackets_stay_separate(self):
        out = deduplicate([org("The Water Institute (University of Florida)"),
                           org("Transportation Institute (University of Florida)")])
        self.assertEqual(len(out), 2)

    def test_marks_are_recomputed_not_accumulated(self):
        first = deduplicate([org("Oak Ridge National Laboratory"), org("Oak Ridge National Lab")])
        again = deduplicate(first)
        self.assertEqual(again[0]["_possible_duplicates"], ["Oak Ridge National Lab"])

    def test_people_keep_the_fuzzy_name_rule(self):
        people = [{"_entity_type": "person", "full_name": "Timothy Townsend"},
                  {"_entity_type": "person", "full_name": "Timothy Townsend Jr"}]
        self.assertEqual(len(deduplicate(people)), 1)


if __name__ == "__main__":
    unittest.main()
