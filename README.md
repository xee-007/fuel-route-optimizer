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
python manage.py runserver
```

## Development

```bash
python manage.py test   # run the test suite
ruff check .            # lint
ruff format .           # auto-format
```

Every push and pull request runs lint, a missing-migrations check and the tests on Python 3.12 and 3.14 via GitHub Actions.
