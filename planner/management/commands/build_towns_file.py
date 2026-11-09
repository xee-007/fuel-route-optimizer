"""
Build `data/us_towns.csv`: every US town with the coordinates of its center.

Two free, public-domain sources are combined:

- US Census Gazetteer ("Places" and "County Subdivisions"): every official town.
  Its point is a geometric "internal point", which can land far from downtown:
  San Francisco's is in the Pacific because the city limits include ocean.
- USGS Geographic Names (GNIS): the traditional center of every populated place,
  including small communities the Census list doesn't have.

Each Census town moves to the USGS center with the same name in the same county
(the county comes from the exact ID link between the two datasets). USGS places
missing from the Census are added when their name is unique in their state.

Download the Census files from
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
and the USGS file from
https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip
then run:

    python manage.py build_towns_file \\
        --places data/raw/2025_Gaz_place_national.txt \\
        --cousubs data/raw/2025_Gaz_cousubs_national.txt \\
        --usgs data/raw/Text/DomesticNames_National.txt
"""

import csv
import math
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from planner.services.geo import haversine_miles
from planner.services.place_names import US_STATES, normalize_place_name, state_code

DEFAULT_OUTPUT = settings.BASE_DIR / "data" / "us_towns.csv"

# Census names end with the kind of area: "Abbeville city", "Mahwah township".
_AREA_TYPE_SUFFIX = re.compile(
    r"\s+(city and borough|metropolitan government|metro government|consolidated government"
    r"|unified government|urban county|municipality|plantation|township"
    r"|borough|village|city|town|CDP)$"
)
# Merged city-county governments are named "<City>-<County> ..." or "<City>/<County> ...",
# e.g. "Nashville-Davidson metropolitan government". Travelers just say "Nashville".
_CITY_COUNTY_TYPES = {
    "metropolitan government",
    "metro government",
    "consolidated government",
    "unified government",
    "urban county",
}
# A USGS center may move a Census town by at most this many "town widths"
# (width ~ square root of its area). That allows San Francisco's 34-mile move
# (its limits include lots of ocean) but not a jump to a different, far-away
# place that happens to share the name.
_MAX_MOVE_IN_TOWN_WIDTHS = 3
# A few official Census names differ from what everyone calls the town.
_EVERYDAY_NAMES = {
    ("Urban Honolulu", "HI"): "Honolulu",
    ("Boise City", "ID"): "Boise",
}


def town_names(raw_name: str, state: str) -> tuple[str, list[str]]:
    """Return a town's main name and any other names people use for it.

    "Abbeville city"                                        -> ("Abbeville", [])
    "Nashville-Davidson metropolitan government (balance)"  -> ("Nashville", [])
    "Louisville/Jefferson County metro government (balance)" -> ("Louisville", [])
    "San Buenaventura (Ventura) city"                       -> ("San Buenaventura", ["Ventura"])
    "Urban Honolulu CDP"                                    -> ("Urban Honolulu", ["Honolulu"])
    """
    # "(balance)" marks the city part of a merged city-county government.
    is_city_county = "(balance)" in raw_name
    name = raw_name.replace("(balance)", "").strip()

    suffix = _AREA_TYPE_SUFFIX.search(name)
    if suffix:
        name = name[: suffix.start()].strip()
        is_city_county = is_city_county or suffix.group(1) in _CITY_COUNTY_TYPES

    if re.search(r"[-/]", name) and (is_city_county or name.endswith(" County")):
        name = re.split(r"[-/]", name)[0].strip()  # "Macon-Bibb County" -> "Macon"

    aliases = []
    alternate = re.search(r"\((.+?)\)", name)
    if alternate:
        aliases.append(alternate.group(1).strip())
        name = re.sub(r"\s*\(.+?\)", "", name).strip()

    if (name, state) in _EVERYDAY_NAMES:
        aliases.append(_EVERYDAY_NAMES[(name, state)])

    return name, aliases


class CensusArea(NamedTuple):
    state: str
    name: str  # official name, e.g. "Abbeville city"
    usgs_id: str  # the same area's ID in the USGS database
    lat: str
    lng: str
    area_sq_miles: float  # land + water


def read_gazetteer(path: Path) -> Iterator[CensusArea]:
    """Yield every row of a pipe-delimited Census Gazetteer file."""
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file, delimiter="|", quoting=csv.QUOTE_NONE):
            # Some Gazetteer years pad the last header with spaces, so strip keys too.
            row = {key.strip(): value.strip() for key, value in row.items()}
            yield CensusArea(
                state=row["USPS"],
                name=row["NAME"],
                usgs_id=row["ANSICODE"].lstrip("0"),  # zero-padded: "02411786"
                lat=row["INTPTLAT"],
                lng=row["INTPTLONG"],
                area_sq_miles=float(row["ALAND_SQMI"]) + float(row["AWATER_SQMI"]),
            )


@dataclass
class UsgsPlaces:
    county_of_area: dict[str, str]  # USGS ID of a Census area -> its county
    centers: dict[tuple[str, str, str], list[tuple[str, str]]]  # (name, state, county) -> points
    # Places whose name appears only once in their state: (name, state) -> (name, lat, lng)
    unique_places: dict[tuple[str, str], tuple[str, str, str]]

    def center_for(self, area: CensusArea, names: list[str]) -> tuple[str, str] | None:
        """The USGS center of a Census town: same name, same state and same county,
        and close enough for the town's size. The nearest one if the county has several."""
        keys = [(normalize_place_name(name), area.state) for name in names]
        county = self.county_of_area.get(area.usgs_id)
        if county is not None:
            options = [point for key in keys for point in self.centers.get((*key, county), [])]
        else:
            # No ID link (e.g. the city part of a merged city-county government):
            # only trust a USGS place whose name is unique in the state.
            options = [self.unique_places[key][1:] for key in keys if key in self.unique_places]
        if not options:
            return None

        def miles_away(point: tuple[str, str]) -> float:
            return float(haversine_miles(float(area.lat), float(area.lng), *map(float, point)))

        nearest = min(options, key=miles_away)
        max_move = _MAX_MOVE_IN_TOWN_WIDTHS * math.sqrt(area.area_sq_miles)
        return nearest if miles_away(nearest) <= max_move else None


def read_usgs_places(path: Path) -> UsgsPlaces:
    """Read the USGS Geographic Names file (every named feature in the US)."""
    county_of_area: dict[str, str] = {}
    centers: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    places_by_name: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)

    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file, delimiter="|", quoting=csv.QUOTE_NONE):
            state = state_code(row["state_name"])
            if state is None:
                continue
            if row["feature_class"] in ("Civil", "Census"):  # the areas Census towns link to
                county_of_area[row["feature_id"]] = row["county_name"]
            elif _is_current_populated_place(row):
                name, point = row["feature_name"], (row["prim_lat_dec"], row["prim_long_dec"])
                key = normalize_place_name(name)
                centers[(key, state, row["county_name"])].append(point)
                places_by_name[(key, state)].append((name, *point))

    unique_places = {key: places[0] for key, places in places_by_name.items() if len(places) == 1}
    return UsgsPlaces(county_of_area, centers, unique_places)


def _is_current_populated_place(row: dict[str, str]) -> bool:
    return (
        row["feature_class"] == "Populated Place"
        and "(historical)" not in row["feature_name"]  # ghost towns
        and float(row["prim_lat_dec"] or 0) != 0  # 0 means "location unknown"
    )


class Command(BaseCommand):
    help = "Build data/us_towns.csv (name, state, lat, lng) from Census and USGS place files."

    def add_arguments(self, parser):
        parser.add_argument("--places", type=Path, required=True, help="Gazetteer places file")
        parser.add_argument(
            "--cousubs", type=Path, required=True, help="Gazetteer county subdivisions file"
        )
        parser.add_argument(
            "--usgs", type=Path, required=True, help="USGS DomesticNames_National.txt file"
        )
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)

    def handle(self, *args, places: Path, cousubs: Path, usgs: Path, output: Path, **options):
        for path in (places, cousubs, usgs):
            if not path.exists():
                raise CommandError(f"File not found: {path}")

        usgs_places = read_usgs_places(usgs)
        main_names: list[tuple[str, str, str, str]] = []
        alias_names: list[tuple[str, str, str, str]] = []
        moved = 0

        # Places (cities, towns, villages) come first so they win over
        # same-named county subdivisions, whose centers are less precise.
        for path in (places, cousubs):
            for area in read_gazetteer(path):
                if area.state not in US_STATES or area.name == "County subdivisions not defined":
                    continue
                name, aliases = town_names(area.name, area.state)
                lat, lng = area.lat, area.lng
                center = usgs_places.center_for(area, [name, *aliases])
                if center:
                    lat, lng = center
                    moved += 1
                main_names.append((name, area.state, lat, lng))
                alias_names.extend((alias, area.state, lat, lng) for alias in aliases)

        # Real towns first, then USGS-only places, then aliases: a real town
        # always wins over another town's alias.
        rows: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        usgs_only = [
            (name, state, lat, lng)
            for (_, state), (name, lat, lng) in usgs_places.unique_places.items()
        ]
        for name, state, lat, lng in main_names + usgs_only + alias_names:
            key = (normalize_place_name(name), state)
            if key[0] and key not in seen:
                seen.add(key)
                rows.append((name, state, lat, lng))

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["name", "state", "lat", "lng"])
            writer.writerows(rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(rows)} towns to {output} "
                f"({moved} Census towns moved to their USGS center)."
            )
        )
