import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from planner.models import Town

FIXTURES = Path(__file__).parent / "fixtures"


class BuildTownsFileTests(SimpleTestCase):
    def build(self) -> dict[tuple[str, str], tuple[str, str]]:
        """Run the command on the fixtures and return {(name, state): (lat, lng)}."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "towns.csv"
            call_command(
                "build_towns_file",
                places=FIXTURES / "gaz_places.txt",
                cousubs=FIXTURES / "gaz_cousubs.txt",
                usgs=FIXTURES / "usgs_places.txt",
                output=output,
                stdout=StringIO(),
            )
            with output.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
        self.assertEqual(list(rows[0]), ["name", "state", "lat", "lng"])
        return {(row["name"], row["state"]): (row["lat"], row["lng"]) for row in rows}

    def test_strips_census_type_suffixes(self):
        towns = self.build()
        self.assertIn(("Abbeville", "AL"), towns)
        self.assertIn(("Mahwah", "NJ"), towns)

    def test_uses_core_city_name_for_consolidated_governments(self):
        self.assertIn(("Nashville", "TN"), self.build())

    def test_keeps_hyphenated_city_names(self):
        self.assertIn(("Winston-Salem", "NC"), self.build())

    def test_prefers_places_over_county_subdivisions_with_same_name(self):
        towns = self.build()
        self.assertEqual(towns[("Springfield", "IL")], ("39.783250", "-89.650148"))
        self.assertEqual(sum(1 for name, state in towns if name == "Springfield"), 1)

    def test_skips_areas_outside_the_fifty_states_and_dc(self):
        self.assertNotIn("PR", {state for _, state in self.build()})

    def test_adds_everyday_name_given_in_parentheses(self):
        towns = self.build()
        self.assertEqual(towns[("Ventura", "CA")], towns[("San Buenaventura", "CA")])

    def test_uses_core_city_name_for_any_city_county_merger(self):
        towns = self.build()
        self.assertIn(("Macon", "GA"), towns)  # "Macon-Bibb County"
        self.assertIn(("Butte", "MT"), towns)  # "Butte-Silver Bow (balance)"

    def test_incorporated_city_wins_over_same_named_census_designated_place(self):
        # "Marietta CDP" comes first in the file, but "Marietta, OK" means the city on I-35.
        self.assertEqual(self.build()[("Marietta", "OK")], ("33.936172", "-97.124716"))

    def test_real_town_wins_over_another_towns_alias(self):
        # "Tharptown (Uniontown) CDP" comes first in the file, but "Uniontown, PA"
        # must still point at the real city of Uniontown.
        towns = self.build()
        self.assertEqual(towns[("Uniontown", "PA")], ("39.899302", "-79.724529"))

    def test_moves_town_to_usgs_downtown_point_in_same_county(self):
        # The Census point for San Francisco is in the Pacific; USGS has City Hall.
        self.assertEqual(self.build()[("San Francisco", "CA")], ("37.775", "-122.4194444"))

    def test_aliases_get_the_corrected_point_too(self):
        towns = self.build()
        self.assertEqual(towns[("Honolulu", "HI")], ("21.3069444", "-157.8583333"))
        self.assertEqual(towns[("Urban Honolulu", "HI")], towns[("Honolulu", "HI")])

    def test_keeps_census_point_when_same_name_is_in_another_county(self):
        # USGS's "Prosper" is a different place, 400 miles away in another county.
        self.assertEqual(self.build()[("Prosper", "MN")], ("48.908432", "-94.9348"))

    def test_picks_nearest_usgs_center_when_county_has_two_same_named_places(self):
        # Coconino County has two "Red Lake"s; the nearer one is this town.
        self.assertEqual(self.build()[("Red Lake", "AZ")], ("35.3786822", "-112.161532"))

    def test_ignores_usgs_center_too_far_for_the_towns_size(self):
        # USGS's LeChee is 130 miles away: far more than a 17 sq mi town allows.
        self.assertEqual(self.build()[("LeChee", "AZ")], ("36.860892", "-111.424438"))

    def test_merged_city_without_usgs_link_uses_the_only_same_named_place(self):
        # The Census "(balance)" area for Butte has no record in the USGS file,
        # but Montana has exactly one populated place called Butte.
        self.assertEqual(self.build()[("Butte", "MT")], ("46.0038153", "-112.5347447"))

    def test_metro_government_names_use_the_core_city_name(self):
        self.assertIn(("Louisville", "KY"), self.build())

    def test_skips_census_placeholder_rows(self):
        self.assertNotIn("County subdivisions not defined", {name for name, _ in self.build()})

    def test_adds_usgs_places_missing_from_census_when_name_is_unique(self):
        self.assertEqual(self.build()[("Breezewood", "PA")], ("39.9992505", "-78.2386229"))

    def test_skips_usgs_places_whose_name_repeats_in_the_state(self):
        self.assertNotIn(("Midway", "KY"), self.build())

    def test_ignores_historical_places(self):
        self.assertNotIn("Laros", {name for name, _ in self.build()})

    def test_adds_everyday_names_for_known_census_naming_quirks(self):
        towns = self.build()
        self.assertEqual(towns[("New York City", "NY")], towns[("New York", "NY")])
        self.assertEqual(towns[("Honolulu", "HI")], towns[("Urban Honolulu", "HI")])
        self.assertEqual(towns[("Boise", "ID")], towns[("Boise City", "ID")])


class LoadTownsTests(TestCase):
    def load(self, path: Path = FIXTURES / "towns.csv") -> str:
        out = StringIO()
        call_command("load_towns", path=path, stdout=out)
        return out.getvalue()

    def test_loads_every_row_with_normalized_names(self):
        output = self.load()

        self.assertIn("Loaded 3 towns", output)
        town = Town.objects.get(normalized_name="saint louis", state="MO")
        self.assertEqual(town.name, "St. Louis")
        self.assertAlmostEqual(town.lat, 38.6357)
        self.assertAlmostEqual(town.lng, -90.2446)

    def test_running_twice_replaces_instead_of_duplicating(self):
        self.load()
        self.load()

        self.assertEqual(Town.objects.count(), 3)

    def test_missing_file_raises_command_error(self):
        with self.assertRaisesMessage(CommandError, "does-not-exist.csv"):
            self.load(FIXTURES / "does-not-exist.csv")
