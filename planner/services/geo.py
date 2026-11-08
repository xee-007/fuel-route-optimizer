"""
Distance helpers for routes on the Earth's surface.

Routes are sequences of (lng, lat) pairs, the GeoJSON order the routing API uses.
The math uses NumPy so a 20,000-point route is processed in milliseconds.
"""

import math
from collections.abc import Sequence

import numpy as np

EARTH_RADIUS_MILES = 3958.8

Coordinates = Sequence[tuple[float, float]]


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles. Works on single numbers or NumPy arrays."""
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cumulative_miles(coords: Coordinates) -> np.ndarray:
    """Distance from the start of the route to each of its points."""
    points = np.asarray(coords, dtype=float)
    lngs, lats = points[:, 0], points[:, 1]
    legs = haversine_miles(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    return np.concatenate([[0.0], np.cumsum(legs)])


def resample_route(coords: Coordinates, step_miles: float) -> tuple[np.ndarray, ...]:
    """Return (lats, lngs, miles) for points every `step_miles` along the route.

    Routing APIs put many points on curves but few on long straight highways;
    evenly spaced points make "how far is this station from the route" reliable.
    The final point of the route is always included.
    """
    points = np.asarray(coords, dtype=float)
    miles = cumulative_miles(coords)
    sample_miles = np.append(np.arange(0.0, miles[-1], step_miles), miles[-1])
    lats = np.interp(sample_miles, miles, points[:, 1])
    lngs = np.interp(sample_miles, miles, points[:, 0])
    return lats, lngs, sample_miles


def simplify_route(coords: Coordinates, max_points: int = 1000) -> list[list[float]]:
    """Thin a route to at most `max_points` points (keeping both ends) for API responses."""
    step = max(1, math.ceil(len(coords) / (max_points - 1)))
    kept = list(coords[::step])
    if kept[-1] != coords[-1]:
        kept.append(coords[-1])
    return [[round(lng, 5), round(lat, 5)] for lng, lat in kept]
