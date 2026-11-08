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
