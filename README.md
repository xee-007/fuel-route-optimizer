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
| `data/us_towns.csv` | US town center coordinates, built from the public-domain [US Census Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) files |

The fuel price list has addresses but no coordinates, so each station is placed at the center of its town. Doing this once at setup means API requests never need a geocoding call. About 3% of stations are in very small unincorporated places that the Census list doesn't include; those are skipped (run `load_fuel_stations -v 2` to list them).

To rebuild `data/us_towns.csv`, download the 2025 "Places" and "County Subdivisions" national Gazetteer files into `data/raw/` and run:

```bash
python manage.py build_towns_file \
    --places data/raw/2025_Gaz_place_national.txt \
    --cousubs data/raw/2025_Gaz_cousubs_national.txt
```

## Development

```bash
python manage.py test   # run the test suite
ruff check .            # lint
ruff format .           # auto-format
```

Every push and pull request runs lint, a missing-migrations check and the tests on Python 3.12 and 3.14 via GitHub Actions.
