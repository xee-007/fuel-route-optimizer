"""
Driving routes from OpenRouteService (https://openrouteservice.org), a free routing API.

A new trip costs exactly one API call. The result is cached, so repeat
requests for the same trip (and the map page) never call the API again.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from planner.services.locations import Location

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class Route:
    coordinates: list[tuple[float, float]]  # (lng, lat) pairs, GeoJSON order
    distance_miles: float
    duration_hours: float


class RoutingError(Exception):
    """The route could not be fetched. Messages are safe to show to API users;
    technical details are logged instead."""

    status_code = 502
    code = "routing_failed"
    default_message = "The routing service failed. Please try again."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.default_message)


class RoutingTimeout(RoutingError):
    status_code = 504
    code = "routing_timeout"
    default_message = "The routing service took too long to respond. Please try again."


class RoutingUnavailable(RoutingError):
    status_code = 503
    code = "routing_unavailable"
    default_message = "Routing is temporarily unavailable. Please try again shortly."


class NoRouteFound(RoutingError):
    status_code = 422
    code = "no_route"
    default_message = "No drivable route was found between these locations."


def get_route(start: Location, finish: Location) -> Route:
    """Return the driving route, from the cache when this trip was requested before."""
    cache_key = f"route:{start.lat:.4f},{start.lng:.4f}:{finish.lat:.4f},{finish.lng:.4f}"
    route = cache.get(cache_key)
    if route is None:
        route = fetch_route(start, finish)
        cache.set(cache_key, route, settings.ROUTE_CACHE_SECONDS)
    return route


def fetch_route(start: Location, finish: Location) -> Route:
    """Call OpenRouteService once and return the route."""
    if not settings.ORS_API_KEY:
        logger.error("ORS_API_KEY is not set, so routes cannot be fetched.")
        raise RoutingUnavailable("Routing is not configured on this server.")

    try:
        response = requests.post(
            settings.ORS_DIRECTIONS_URL,
            json={
                "coordinates": [[start.lng, start.lat], [finish.lng, finish.lat]],
                "instructions": False,  # we only need the line, not turn-by-turn text
                "radiuses": [settings.ORS_SNAP_RADIUS_METERS] * 2,  # how far to look for a road
            },
            headers={"Authorization": settings.ORS_API_KEY},
            timeout=settings.ORS_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise RoutingTimeout() from error
    except requests.RequestException as error:
        logger.error("Could not reach OpenRouteService: %s", error)
        raise RoutingError() from error

    if response.status_code != 200:
        raise _error_for(response)
    return _parse_route(response)


def _parse_route(response: requests.Response) -> Route:
    try:
        feature = response.json()["features"][0]
        coordinates = [
            (float(lng), float(lat)) for lng, lat, *_ in feature["geometry"]["coordinates"]
        ]
        summary = feature["properties"].get("summary", {})  # empty when start == finish
    except (ValueError, KeyError, IndexError, TypeError) as error:
        logger.error("Unexpected OpenRouteService response: %r", error)
        raise RoutingError() from error

    return Route(
        coordinates=coordinates,
        distance_miles=summary.get("distance", 0.0) / METERS_PER_MILE,
        duration_hours=summary.get("duration", 0.0) / SECONDS_PER_HOUR,
    )


def _error_for(response: requests.Response) -> RoutingError:
    """Translate an OpenRouteService error response into one of our errors."""
    status = response.status_code
    detail = _error_detail(response)

    if status in (401, 403):
        # A bad key or a used-up daily quota: retrying won't help.
        logger.error("OpenRouteService rejected the request (HTTP %s): %s", status, detail)
        return RoutingUnavailable()
    if status == 429:
        logger.warning("OpenRouteService rate limit reached: %s", detail)
        return RoutingUnavailable()
    if 400 <= status < 500:
        # e.g. a point far from any road, or a route longer than the API allows
        return NoRouteFound(f"{NoRouteFound.default_message} {detail}".strip())

    logger.error("OpenRouteService error (HTTP %s): %s", status, detail)
    return RoutingError()


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else body
    if isinstance(error, dict):
        return str(error.get("message", ""))
    return str(error or "")
