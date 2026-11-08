from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from planner.models import FuelStation, Town

FUEL_PRICES = Path(__file__).parent / "fixtures" / "fuel_prices.csv"


class LoadFuelStationsTests(TestCase):
    def setUp(self):
        Town.objects.create(
            name="Big Cabin", normalized_name="big cabin", state="OK", lat=36.5369, lng=-95.2216
        )
        Town.objects.create(
            name="Gila Bend", normalized_name="gila bend", state="AZ", lat=32.9478, lng=-112.7168
        )

    def load(self, **options) -> str:
        out = StringIO()
        call_command("load_fuel_stations", path=FUEL_PRICES, stdout=out, **options)
        return out.getvalue()

    def test_loads_us_stations_at_their_town_coordinates(self):
        self.load()

        self.assertEqual(FuelStation.objects.count(), 2)
        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual((station.lat, station.lng), (36.5369, -95.2216))
        self.assertEqual(station.address, "I-44, EXIT 283 & US-69")
        self.assertEqual(station.rack_id, 307)
        self.assertEqual(station.price_per_gallon, Decimal("3.00733333"))

    def test_strips_stray_whitespace_from_values(self):
        self.load()

        station = FuelStation.objects.get(opis_id=7)
        self.assertEqual(station.name, "WOODSHED OF BIG CABIN")
        self.assertEqual(station.city, "Big Cabin")

    def test_keeps_lowest_price_for_duplicate_station_ids(self):
        self.load()

        station = FuelStation.objects.get(opis_id=20)
        self.assertEqual(station.price_per_gallon, Decimal("3.799"))
        self.assertEqual(station.name, "PILOT #1243")

    def test_reports_loaded_skipped_and_ignored_counts(self):
        output = self.load()

        self.assertIn("Loaded 2 stations", output)
        self.assertIn("Skipped 1 with an unknown town", output)
        self.assertIn("Ignored 1 outside the US", output)

    def test_lists_unknown_towns_when_verbose(self):
        self.assertIn("Nowhereville, KS", self.load(verbosity=2))

    def test_running_twice_replaces_instead_of_duplicating(self):
        self.load()
        self.load()

        self.assertEqual(FuelStation.objects.count(), 2)

    def test_requires_towns_to_be_loaded_first(self):
        Town.objects.all().delete()

        with self.assertRaisesMessage(CommandError, "load_towns"):
            self.load()

    def test_missing_file_raises_command_error(self):
        with self.assertRaisesMessage(CommandError, "nope.csv"):
            call_command("load_fuel_stations", path=Path("nope.csv"), stdout=StringIO())
