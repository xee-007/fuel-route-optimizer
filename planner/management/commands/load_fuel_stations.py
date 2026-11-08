"""
Load the fuel price list into the database.

The price file has addresses like "I-44, EXIT 283 & US-69" but no coordinates,
so each station is placed at the center of its town (see `load_towns`).
This runs once at setup, so API requests never need a geocoding call.
"""

import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation, Town
from planner.services.place_names import normalize_place_name, state_code

DEFAULT_PATH = settings.BASE_DIR / "data" / "fuel_prices.csv"


def read_cheapest_us_rows(path: Path) -> tuple[dict[int, dict[str, str]], int]:
    """Return the cheapest row per station ID (US only) and the number of non-US rows.

    Some stations appear more than once with different prices; a driver would
    pay the lowest one, so that is the price we keep.
    """
    cheapest: dict[int, dict[str, str]] = {}
    non_us_rows = 0

    with path.open(newline="", encoding="utf-8") as file:
        for raw_row in csv.DictReader(file):
            row = {key.strip(): value.strip() for key, value in raw_row.items()}
            state = state_code(row["State"])
            if state is None:
                non_us_rows += 1
                continue
            row["State"] = state

            opis_id = int(row["OPIS Truckstop ID"])
            current = cheapest.get(opis_id)
            if current is None or Decimal(row["Retail Price"]) < Decimal(current["Retail Price"]):
                cheapest[opis_id] = row

    return cheapest, non_us_rows


class Command(BaseCommand):
    help = "Load fuel stations and prices from the fuel price CSV, replacing existing stations."

    def add_arguments(self, parser):
        parser.add_argument("--path", type=Path, default=DEFAULT_PATH)

    def handle(self, *args, path: Path, verbosity: int, **options):
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        town_coordinates = {
            (name, state): (lat, lng)
            for name, state, lat, lng in Town.objects.values_list(
                "normalized_name", "state", "lat", "lng"
            )
        }
        if not town_coordinates:
            raise CommandError("No towns in the database. Run `python manage.py load_towns` first.")

        rows, non_us_rows = read_cheapest_us_rows(path)

        stations: list[FuelStation] = []
        unknown_towns: set[str] = set()
        for opis_id, row in rows.items():
            coordinates = town_coordinates.get((normalize_place_name(row["City"]), row["State"]))
            if coordinates is None:
                unknown_towns.add(f"{row['City']}, {row['State']}")
                continue
            stations.append(
                FuelStation(
                    opis_id=opis_id,
                    name=row["Truckstop Name"],
                    address=row["Address"],
                    city=row["City"],
                    state=row["State"],
                    rack_id=int(row["Rack ID"]),
                    price_per_gallon=Decimal(row["Retail Price"]),
                    lat=coordinates[0],
                    lng=coordinates[1],
                )
            )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=2000)

        skipped = len(rows) - len(stations)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} stations. "
                f"Skipped {skipped} with an unknown town. "
                f"Ignored {non_us_rows} outside the US."
            )
        )
        if verbosity >= 2 and unknown_towns:
            self.stdout.write("Unknown towns: " + "; ".join(sorted(unknown_towns)))
