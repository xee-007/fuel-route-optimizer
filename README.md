# Fuel Route Optimizer

A Django API that plans a driving route between two US locations and picks the cheapest places to refuel along the way.

## Requirements

- Python 3.12+
- A free [OpenRouteService](https://openrouteservice.org/dev/#/signup) API key (for routing)

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env   # then fill in DJANGO_SECRET_KEY and ORS_API_KEY
python manage.py migrate
python manage.py load_towns           # ~50k US town coordinates (US Census)
python manage.py load_fuel_stations   # fuel stations + prices, placed at their town
python manage.py runserver
```

## Data

| File | What it is |
|---|---|
| `data/fuel_prices.csv` | The provided list of truck stops and their retail fuel prices |
| `data/us_towns.csv` | ~166k US towns with the coordinates of their center, built from two public-domain sources (below) |

The fuel price list has addresses but no coordinates, so each station is placed at the center of its town. Doing this once at setup means API requests never need a geocoding call. 99.5% of US stations are placed; the rest are in places too small for either source (run `load_fuel_stations -v 2` to list them).

**Where town centers come from**

- The [US Census Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) lists every official town, but its point is a geometric "internal point" that can be far from downtown. San Francisco's is in the Pacific, because the city limits include ocean.
- [USGS Geographic Names](https://www.usgs.gov/us-board-on-geographic-names/domestic-names) gives the traditional center of every populated place. Each Census town moves to the USGS center with the same name in the same county, as long as the move is plausible for the town's size. USGS places missing from the Census list (e.g. Breezewood, PA) are added when their name is unique in their state.

To rebuild `data/us_towns.csv`, download into `data/raw/` the 2025 "Places" and "County Subdivisions" national Gazetteer files and the USGS [`DomesticNames_National_Text.zip`](https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip), then run:

```bash
python manage.py build_towns_file \
    --places data/raw/2025_Gaz_place_national.txt \
    --cousubs data/raw/2025_Gaz_cousubs_national.txt \
    --usgs data/raw/Text/DomesticNames_National.txt
```

**Coverage of the price list.** The provided list has few stations in some regions. California, for example, has only 8, all in the far south-east. A trip with more than 500 miles between known stations (e.g. San Francisco → Las Vegas) can't be planned, and the API says so with a clear error.

## Development

```bash
python manage.py test   # run the test suite
ruff check .            # lint
ruff format .           # auto-format
```

Every push and pull request runs lint, a missing-migrations check and the tests on Python 3.12 and 3.14 via GitHub Actions.
