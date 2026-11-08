"""
Find the fuel stations that are on the way.

1. Ask the database only for stations inside the route's bounding box.
2. Measure each one's distance to the route with a KD-tree, a spatial index
   that finds the nearest of thousands of route points in microseconds.
3. Keep the stations within the corridor and note how far along the route each one is.
"""

import math
from collections.abc import Iterable

import numpy as np
from scipy.spatial import cKDTree

from planner.models import FuelStation
from planner.services.fuel_planner import StationCandidate
from planner.services.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles, resample_route

MILES_PER_DEGREE_OF_LATITUDE = 69.0

_STATION_FIELDS = ("opis_id", "name", "address", "city", "state", "lat", "lng", "price_per_gallon")


def find_stations_along_route(coords: Coordinates, corridor_miles: float) -> list[StationCandidate]:
    """Stations within `corridor_miles` of the route, sorted by how far along it they are."""
    route_lats, route_lngs, route_miles = resample_route(coords, step_miles=1.0)
    rows = _stations_in_box(
        route_lats.min(), route_lats.max(), route_lngs.min(), route_lngs.max(), corridor_miles
    )
    if not rows:
        return []

    station_lats = np.array([row["lat"] for row in rows])
    station_lngs = np.array([row["lng"] for row in rows])

    tree = cKDTree(_unit_vectors(route_lats, route_lngs))
    chord, nearest = tree.query(_unit_vectors(station_lats, station_lngs))
    # Straight-line (chord) distance through the Earth -> distance along its surface.
    miles_off_route = 2 * EARTH_RADIUS_MILES * np.arcsin(np.clip(chord / 2, 0.0, 1.0))

    found = [
        _candidate(row, route_mile=float(route_miles[index]))
        for row, distance, index in zip(rows, miles_off_route, nearest, strict=True)
        if distance <= corridor_miles
    ]
    return sorted(found, key=lambda station: station.route_mile)


def find_start_station(lat: float, lng: float, radius_miles: float) -> StationCandidate | None:
    """The cheapest station within `radius_miles` of a point (the nearest one on a tie)."""
    nearby = []
    for row in _stations_in_box(lat, lat, lng, lng, radius_miles):
        distance = float(haversine_miles(lat, lng, row["lat"], row["lng"]))
        if distance <= radius_miles:
            nearby.append((row["price_per_gallon"], distance, row))

    if not nearby:
        return None
    _, _, cheapest = min(nearby, key=lambda item: (item[0], item[1]))
    return _candidate(cheapest, route_mile=0.0)


def thin_stations(
    candidates: Iterable[StationCandidate], spacing_miles: float
) -> list[StationCandidate]:
    """Keep only the cheapest station in each `spacing_miles` stretch of the route.

    Stopping twice within a few miles to save a cent isn't a sensible plan.
    """
    cheapest_per_stretch: dict[int, StationCandidate] = {}
    for station in candidates:
        stretch = math.floor(station.route_mile / spacing_miles)
        current = cheapest_per_stretch.get(stretch)
        if current is None or (station.price_per_gallon, station.route_mile) < (
            current.price_per_gallon,
            current.route_mile,
        ):
            cheapest_per_stretch[stretch] = station
    return sorted(cheapest_per_stretch.values(), key=lambda station: station.route_mile)


def _stations_in_box(
    min_lat: float, max_lat: float, min_lng: float, max_lng: float, padding_miles: float
) -> list[dict]:
    """Stations inside a lat/lng box, widened by `padding_miles` on every side."""
    lat_padding = padding_miles / MILES_PER_DEGREE_OF_LATITUDE
    # A degree of longitude shrinks toward the poles, so pad more at higher latitudes.
    widest_lat = min(max(abs(min_lat), abs(max_lat)) + lat_padding, 89.0)
    lng_padding = lat_padding / math.cos(math.radians(widest_lat))

    return list(
        FuelStation.objects.filter(
            lat__range=(min_lat - lat_padding, max_lat + lat_padding),
            lng__range=(min_lng - lng_padding, max_lng + lng_padding),
        ).values(*_STATION_FIELDS)
    )


def _unit_vectors(lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
    """Points on a unit sphere (x, y, z), where straight-line distance tracks surface distance."""
    lat, lng = np.radians(lats), np.radians(lngs)
    return np.column_stack([np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat)])


def _candidate(row: dict, route_mile: float) -> StationCandidate:
    return StationCandidate(
        station_id=row["opis_id"],
        name=row["name"],
        address=row["address"],
        city=row["city"],
        state=row["state"],
        lat=row["lat"],
        lng=row["lng"],
        price_per_gallon=row["price_per_gallon"],
        route_mile=route_mile,
    )
