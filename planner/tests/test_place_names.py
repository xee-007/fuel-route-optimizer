from django.test import SimpleTestCase

from planner.services.place_names import US_STATES, normalize_place_name, state_code


class NormalizePlaceNameTests(SimpleTestCase):
    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(normalize_place_name("  Big   Cabin "), "big cabin")

    def test_expands_saint_abbreviation_anywhere_in_name(self):
        self.assertEqual(normalize_place_name("St. Louis"), "saint louis")
        self.assertEqual(normalize_place_name("East St Louis"), "east saint louis")
        self.assertEqual(normalize_place_name("Ste. Genevieve"), "sainte genevieve")

    def test_expands_fort_and_mount_abbreviations(self):
        self.assertEqual(normalize_place_name("Ft. Worth"), "fort worth")
        self.assertEqual(normalize_place_name("Mt. Jackson"), normalize_place_name("Mount Jackson"))

    def test_does_not_expand_abbreviation_letters_inside_words(self):
        self.assertEqual(normalize_place_name("West Stanton"), "west stanton")

    def test_joins_common_name_prefixes(self):
        self.assertEqual(normalize_place_name("Mc Calla"), normalize_place_name("McCalla"))
        self.assertEqual(normalize_place_name("De Forest"), normalize_place_name("DeForest"))
        self.assertEqual(normalize_place_name("La Salle"), normalize_place_name("LaSalle"))

    def test_hyphens_and_slashes_become_spaces(self):
        self.assertEqual(normalize_place_name("Winston-Salem"), "winston salem")

    def test_drops_punctuation_and_parenthesized_text(self):
        self.assertEqual(normalize_place_name("O'Fallon"), "ofallon")
        self.assertEqual(normalize_place_name("Nashville (balance)"), "nashville")

    def test_strips_accents(self):
        self.assertEqual(normalize_place_name("Cañon City"), normalize_place_name("Canon City"))


class StateCodeTests(SimpleTestCase):
    def test_accepts_code_in_any_case(self):
        self.assertEqual(state_code("il"), "IL")
        self.assertEqual(state_code(" TX "), "TX")

    def test_accepts_full_state_name(self):
        self.assertEqual(state_code("Illinois"), "IL")
        self.assertEqual(state_code("new york"), "NY")
        self.assertEqual(state_code("District of Columbia"), "DC")

    def test_rejects_non_us_regions(self):
        self.assertIsNone(state_code("ON"))  # Ontario, Canada
        self.assertIsNone(state_code("PR"))  # Puerto Rico is not reachable by road
        self.assertIsNone(state_code("Atlantis"))

    def test_covers_fifty_states_and_dc(self):
        self.assertEqual(len(US_STATES), 51)
