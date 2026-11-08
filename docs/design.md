# Fuel Route Optimizer — Design

*2026-11-08 · Job assessment for "Backend Django Engineer" · GitHub: `xee-007/fuel-route-optimizer`*

## 1. Why this exists

A take-home assessment. Reviewers will judge four things, roughly in this order:

1. **It works**: correct route, sensible cheap fuel stops, correct total cost.
2. **It's fast and frugal with the routing API**: one external call per request is ideal; 2–3 is acceptable.
3. **The code is easy to read**: the candidate must walk through it on a 5-minute Loom.
4. **Professional habits**: feature branches, pull requests, tests, CI, clear README.

The candidate has to explain every line on camera, so **clarity beats cleverness** everywhere.

## 2. Requirements (from the brief)

- An API that takes a start and a finish location, both in the USA.
- It returns a map of the route plus the best places to buy fuel along it. "Best" mostly means cheapest, using the provided price file.
- The vehicle has a max range of **500 miles**, so long trips need several stops.
- It returns the **total fuel cost** at **10 miles per gallon**.
- A free map/routing API of our choosing.
- Latest stable Django (**6.1.3** as of today). The response must be fast, and the routing API should ideally be called once.
- Deliverables: a GitHub repo, and a ≤5-minute Loom showing Postman plus a code overview.

## 3. Goals, non-goals, anti-goals

**Goals**
- **Exactly one** routing-API call per new trip, and **zero** for a trip already cached.
- Server time excluding the routing call is **under ~300 ms**. With a warm cache, the whole response takes **under ~200 ms**.
- A small, readable codebase with the business logic in plain, unit-tested Python functions.
- A reviewer can clone the repo and run it in a few commands with no external database and no paid services.

**Non-goals**
- Authentication, user accounts, rate limiting, deployment or hosting.
- Street-address input. Start and finish are **towns** (`"Chicago, IL"`) or **coordinates**.
- Exact station coordinates. Stations are placed at their town's center (see 5.1).
- PostGIS or any GIS system library. It's overkill here and makes setup harder for reviewers.

**Anti-goals** (would count as failure even if it technically works)
- Calling a geocoding or routing service per fuel station, or more than once per request.
- Clever or over-abstracted code the candidate can't explain in 5 minutes.
- Committed secrets, or a repo that won't run from the README.
- One giant commit, or work done directly on `main`.

## 4. API contract

### `GET /api/v1/route-plan/?start=<location>&finish=<location>`

`<location>` is either:
- `"City, ST"`, e.g. `Chicago, IL` (the full state name `Chicago, Illinois` also works), or
- `"lat,lng"`, e.g. `41.8781,-87.6298`.

GET because the operation reads data, has no side effects and can be cached.

**200 response** (shape; field names may be polished during the build):

```json
{
  "start":  {"query": "Chicago, IL", "label": "Chicago, IL", "lat": 41.83, "lng": -87.68},
  "finish": {"query": "Los Angeles, CA", "label": "Los Angeles, CA", "lat": 34.02, "lng": -118.41},
  "distance_miles": 2015.4,
  "duration_hours": 29.8,
  "fuel_summary": {
    "miles_per_gallon": 10,
    "tank_range_miles": 500,
    "total_gallons": 201.54,
    "total_cost_usd": 651.12,
    "starts_with_full_tank": false
  },
  "fuel_stops": [
    {
      "stop_number": 1,
      "station_id": 1234,
      "name": "PILOT TRAVEL CENTER #123",
      "address": "I-55, EXIT 1",
      "city": "Chicago", "state": "IL",
      "lat": 41.83, "lng": -87.68,
      "route_mile": 0.0,
      "price_per_gallon": 3.199,
      "gallons": 18.2,
      "cost_usd": 58.22
    }
  ],
  "route": {"type": "LineString", "coordinates": [[-87.68, 41.83], "..."]},
  "map_url": "http://localhost:8000/api/v1/route-plan/map/?start=Chicago%2C+IL&finish=Los+Angeles%2C+CA"
}
```

- `route` is GeoJSON, **simplified** for the response so the payload stays small (target under ~150 KB). Planning uses the full-detail route.
- Money is computed with `Decimal` and rounded to cents. Gallons are rounded to 2 decimals.

### `GET /api/v1/route-plan/map/?start=…&finish=…`

An HTML page drawn with Leaflet and OpenStreetMap tiles (free, no key). It shows the route line, start and finish markers, and numbered fuel-stop markers whose popups give the price, gallons and cost, plus a small summary box. It reuses the cached route, so **opening the map makes no routing call**.

### Errors

The same JSON shape everywhere: `{"error": {"code": "...", "message": "..."}}`

| Status | When |
|---|---|
| 400 | Missing or malformed `start`/`finish`; unknown town; coordinates outside the USA |
| 422 | No drivable route; or a gap longer than 500 miles with no fuel station, so the trip is impossible |
| 502 / 504 | The routing service returned an error / timed out |

## 5. How it works

### 5.1 Data: fuel stations and towns (one-time setup, no API calls)

The CSV has 8,151 rows (6,738 unique stations), with name, address, city, state and price but **no coordinates**.

- **Town list:** the free, public-domain **US Census Gazetteer** files ("places" plus "county subdivisions"). Each gives a town name, state and center latitude/longitude. A small management command turns them into one compact `data/us_towns.csv` (≈50k rows) that is committed, so a reviewer never has to download anything. The command that builds it is committed too, so it can be reproduced.
- **`load_towns`** loads that file into a `Town` table. Names are normalized ("St." → "Saint", "Ft." → "Fort", punctuation and case removed, and suffixes like "city"/"town"/"CDP" stripped).
- **`load_fuel_stations`** reads the provided CSV (committed at `data/fuel-prices-for-be-assessment.csv`) and:
  - drops non-US rows (Canadian provinces),
  - de-duplicates by OPIS Truckstop ID, keeping the **lowest** price,
  - looks up each station's town to get its coordinates,
  - skips stations whose town can't be found and prints a summary (measured: ~97% match; the ~250 skipped are in tiny unincorporated places),
  - is safe to run again (it replaces the previous data).
- The same `Town` table also turns the user's `"City, ST"` input into coordinates. That is why the API needs **no geocoding call**.

**Models**
- `Town`: `name`, `normalized_name`, `state`, `lat`, `lng`. Indexed on `(normalized_name, state)`.
- `FuelStation`: `opis_id` (unique), `name`, `address`, `city`, `state`, `rack_id`, `price_per_gallon` (Decimal), `lat`, `lng`. Indexed on `(lat, lng)`.

### 5.2 Routing: OpenRouteService (one call)

- `POST https://api.openrouteservice.org/v2/directions/driving-car/geojson` with `{"coordinates": [[lng, lat], [lng, lat]]}`.
- Free account and API key. The key is read from the `ORS_API_KEY` environment variable and never committed. Free quotas are about 2,000 directions/day and 40/minute, and the route length limit (~6,000 km) covers any trip within the lower 48 (confirm these when signing up).
- It returns the full route line, total distance and duration.
- **Caching:** the routing result is stored in Django's cache, keyed by the resolved start/finish coordinates (rounded), for 24 hours. Repeat requests and the map page reuse it. The cache backend is local memory by default and can be switched to Redis through settings, with no code change.
- The HTTP call has a timeout (~15 s) and turns failures into the 502/504 errors above.

### 5.3 Finding stations along the route

1. Work out the cumulative mile marker for each point of the route line.
2. Pull candidate stations from the database inside the route's bounding box, plus a small buffer.
3. Measure each candidate's distance to the route using **NumPy**, vectorized over a resampled route (~1 point per mile). Keep stations within **10 miles** of the route (`FUEL_CORRIDOR_MILES` setting). Each kept station gets the mile marker of its nearest route point.
4. **Thinning:** keep only the cheapest station in each **25-mile stretch** of the route (`STOP_SPACING_MILES` setting). This stops the plan from making two stops a few miles apart to save a cent.

### 5.4 Choosing fuel stops (the core algorithm)

**Start of the trip:** the vehicle starts **empty** and fills up before leaving at the **cheapest station within 25 miles of the start** (treated as mile 0, and never removed by thinning). That way every gallon of the trip is paid for, and the total is the real trip cost. If no station is that close, the vehicle is assumed to start with a **full tank**, and the response says so (`starts_with_full_tank: true`).

**Greedy plan:** this is the classic "gas station problem" strategy, which is cost-optimal for stops along a line:

```
At each stop:
  1. If a CHEAPER station is within range (500 mi) ahead,
       buy only enough fuel to reach it, then drive there.
  2. Otherwise, if the finish is within range,
       buy only enough to reach the finish. Done.
  3. Otherwise, fill the tank,
       then drive to the CHEAPEST station within range ahead.
  If there's no station within range and the finish is out of reach → 422.
```

- The vehicle arrives at the finish empty.
- The detour from the route to a station (at most ~10 miles) is not added to the fuel needed. This is a stated assumption.
- The planner is a **pure function** with no Django, database or HTTP inside it: `plan_fuel_stops(stations, trip_miles, tank_range, mpg, starts_full) -> FuelPlan`. That makes it easy to unit-test and to explain.

### 5.5 Code layout

```
fuel-route-optimizer/
├── config/                     # Django project: settings, urls, wsgi/asgi
├── planner/                    # the single Django app
│   ├── models.py               # Town, FuelStation
│   ├── services/
│   │   ├── locations.py        # parse "City, ST" / "lat,lng" → coordinates
│   │   ├── routing.py          # OpenRouteService client + caching
│   │   ├── geo.py              # haversine, mile markers, corridor search
│   │   └── fuel_planner.py     # the greedy algorithm (pure Python)
│   ├── api/
│   │   ├── serializers.py      # input validation + output shape (DRF)
│   │   ├── views.py            # thin views: validate → call services → respond
│   │   └── urls.py
│   ├── management/commands/    # build_towns_file, load_towns, load_fuel_stations
│   ├── templates/planner/map.html
│   └── tests/                  # one test module per service + API tests
├── data/                       # fuel CSV + us_towns.csv
├── docs/design.md              # this document
├── postman/                    # Postman collection for the demo
├── .github/workflows/ci.yml    # run lint + tests on every PR
├── .env.example  requirements.txt  README.md
```

Views stay thin, and all logic lives in `services/`. Each file does one job.

## 6. Engineering practices

- **Stack:** Python 3.14 (installed locally), Django 6.1.3, Django REST Framework, `requests`, `numpy`, `python-dotenv`. SQLite. Dependencies are pinned in `requirements.txt`.
- **Config:** `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` and `ORS_API_KEY` come from environment variables. `.env.example` is committed and `.env` is git-ignored.
- **Lint/format:** `ruff`, enforced in CI.
- **Tests:** unit tests for the location parser, geo helpers and planner (hand-built stations covering cheap-ahead, fill-up, finish-in-range, gap → error, full-tank fallback). There are also routing-client tests with the HTTP call mocked, and API tests that **assert exactly one routing call and zero on a cache hit**, plus a load-command test with a tiny CSV. No test touches the real network.
- **CI:** GitHub Actions runs ruff and the tests on every push and PR.
- **Git:**
  - `main` only ever receives merged pull requests.
  - One branch per feature, using conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
  - Each PR gets a short description: what changed, why, and how it was tested.
  - Claude opens each PR. **The candidate reviews it and clicks Merge on GitHub** once CI passes. It's merged with a merge commit, so the step-by-step history stays visible.
  - Commits are authored as **Zeeshan Amir <127728122+xee-007@users.noreply.github.com>** (GitHub private email), set **only inside this repo**. Pushing uses HTTPS with the `xee-007` login pinned to this repo, so the Mac's other GitHub accounts and global settings are untouched.

**Branch / PR plan**

| # | Branch | What lands |
|---|---|---|
| 1 | `chore/project-setup` | Django project, settings from env, DRF, ruff, CI, `.gitignore`, `.env.example`, README skeleton, this design doc |
| 2 | `feat/station-data` | `Town` and `FuelStation` models, town file builder, load commands, data files, tests |
| 3 | `feat/routing-client` | Location parsing, OpenRouteService client, caching, tests |
| 4 | `feat/fuel-planner` | Corridor search, thinning, greedy planner, tests |
| 5 | `feat/route-plan-api` | Endpoint, serializers, errors, map page, API tests |
| 6 | `docs/readme-and-postman` | Full README (setup, design choices, assumptions, trade-offs), Postman collection |

## 7. Deliverables

- A public GitHub repo `xee-007/fuel-route-optimizer` with the history above.
- **README:** what it does, a quickstart (venv → install → `.env` → migrate → load data → runserver), example requests, assumptions, design trade-offs (why town-level positions, why the greedy algorithm, why one API call), and how to run the tests.
- **Postman collection** with ready-made requests: a long trip with several stops, a medium trip, a short trip, and a few error cases.
- A short **Loom talk-track** for the candidate (not committed): demo order and the 4–5 code points to show.

## 8. Calls I made (open to change)

- OpenRouteService for routing; Leaflet + OpenStreetMap for the map page.
- Census Gazetteer for town coordinates, about 97% of stations covered.
- Town or coordinate input instead of street addresses, which keeps it to one routing call.
- Tank starts empty with a fill-up near the start, falling back to a full tank.
- 10-mile corridor, 25-mile stop spacing, 25-mile start radius, all adjustable in settings.
- GET endpoint plus a separate HTML map page.
- SQLite, local-memory cache, NumPy for the distance math.
- Merge commits (not squash); public repo; project folder at `~/Desktop/fuel-route-optimizer`.
- When a Census "place" and a "county subdivision" share a name in the same state, the place wins.
- "Inside the USA" for coordinate input means inside rough bounding boxes for the lower 48, Alaska and Hawaii. Town input is in the USA by definition.
- Routes that briefly cross into Canada (e.g. Detroit → Buffalo) still work; only US stations are offered.
- If DRF turns out not to support Django 6.1 yet, the API uses plain Django views with `JsonResponse` instead. The brief's "latest stable Django" wins.

## 9. Left to the builder

- Exact name-normalization rules and the town-file build details.
- Route simplification method for the response.
- Test runner (Django's built-in runner or pytest).
- Small naming and response-field polish.
