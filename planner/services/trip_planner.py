"""
Plan a whole trip: the one place where all the services come together.

    "Chicago, IL" -> coordinates -> route (1 API call, cached)
                  -> stations along the route -> cheapest fuel stops
"""

from dataclasses import dataclass

from django.conf import settings

from planner.services.fuel_planner import FuelPlan, plan_fuel_stops
from planner.services.locations import Location, resolve_location
from planner.services.routing import Route, get_route
from planner.services.station_search import find_stations_along_route


@dataclass(frozen=True)
class TripPlan:
    start: Location
    finish: Location
    route: Route
    fuel_plan: FuelPlan


def plan_trip(start_query: str, finish_query: str) -> TripPlan:
    # Resolve both locations first, so bad input never costs a routing API call.
    start = resolve_location(start_query)
    finish = resolve_location(finish_query)
    route = get_route(start, finish)

    stations = find_stations_along_route(route.coordinates, settings.FUEL_CORRIDOR_MILES)
    fuel_plan = plan_fuel_stops(
        stations,
        trip_miles=route.distance_miles,
        tank_range_miles=settings.VEHICLE_RANGE_MILES,
        mpg=settings.VEHICLE_MPG,
        min_saving_per_stop=settings.MIN_SAVING_PER_STOP,
    )
    return TripPlan(start=start, finish=finish, route=route, fuel_plan=fuel_plan)
