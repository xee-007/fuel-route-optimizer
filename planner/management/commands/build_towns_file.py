"""
Build `data/us_towns.csv` from the US Census Gazetteer files.

The Gazetteer is free, public-domain data listing every US town with the
coordinates of its center. Download the "Places" and "County Subdivisions"
national files from
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
then run:

    python manage.py build_towns_file \\
        --places data/raw/2025_Gaz_place_national.txt \\
        --cousubs data/raw/2025_Gaz_cousubs_national.txt
"""

import csv
import re
from collections.abc import Iterator
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.services.place_names import US_STATES, normalize_place_name

DEFAULT_OUTPUT = settings.BASE_DIR / "data" / "us_towns.csv"

# Census names end with the kind of area: "Abbeville city", "Mahwah township".
_AREA_TYPE_SUFFIX = re.compile(
    r"\s+(city and borough|metropolitan government|consolidated government"
    r"|unified government|urban county|municipality|plantation|township"
    r"|borough|village|city|town|CDP)$"
)
# Merged city-county governments are named "<City>-<County> ...",
# e.g. "Nashville-Davidson metropolitan government". Travelers just say "Nashville".
_CITY_COUNTY_TYPES = {
    "metropolitan government",
    "consolidated government",
    "unified government",
    "urban county",
}


def clean_census_name(raw_name: str) -> str:
    """Turn a Census area name into the town name people actually use."""
    name = raw_name.replace("(balance)", "").strip()
    match = _AREA_TYPE_SUFFIX.search(name)
    if not match:
        return name
    name = name[: match.start()]
    if match.group(1) in _CITY_COUNTY_TYPES:
        name = name.split("-")[0]
    return name.strip()


def read_gazetteer(path: Path) -> Iterator[tuple[str, str, str, str]]:
    """Yield (state, name, lat, lng) for every row of a pipe-delimited Gazetteer file."""
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file, delimiter="|", quoting=csv.QUOTE_NONE):
            # Some Gazetteer years pad the last header with spaces, so strip keys too.
            row = {key.strip(): value.strip() for key, value in row.items()}
            yield row["USPS"], row["NAME"], row["INTPTLAT"], row["INTPTLONG"]


class Command(BaseCommand):
    help = "Build data/us_towns.csv (name, state, lat, lng) from US Census Gazetteer files."

    def add_arguments(self, parser):
        parser.add_argument("--places", type=Path, required=True, help="Gazetteer places file")
        parser.add_argument(
            "--cousubs", type=Path, required=True, help="Gazetteer county subdivisions file"
        )
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    def handle(self, *args, places: Path, cousubs: Path, output: Path, **options):
        seen: set[tuple[str, str]] = set()
        rows: list[tuple[str, str, str, str]] = []

        # Places (cities, towns, villages) come first so they win over
        # same-named county subdivisions, whose centers are less precise.
        for path in (places, cousubs):
            if not path.exists():
                raise CommandError(f"File not found: {path}")
            for state, raw_name, lat, lng in read_gazetteer(path):
                if state not in US_STATES:
                    continue
                name = clean_census_name(raw_name)
                key = (normalize_place_name(name), state)
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                rows.append((name, state, lat, lng))

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["name", "state", "lat", "lng"])
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(rows)} towns to {output}."))
