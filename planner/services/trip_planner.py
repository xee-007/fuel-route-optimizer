"""
Plan a whole trip: the one place where all the services come together.

    "Chicago, IL" -> coordinates -> route (1 API call, cached)
                  -> stations along the route -> cheapest fuel stops
"""

from dataclasses import dataclass

from django.conf import settings

from planner.services.fuel_planner import FuelPlan, FuelPlanError, StationCandidate, plan_fuel_stops
from planner.services.locations import Location, resolve_location
from planner.services.routing import Route, get_route
from planner.services.station_search import (
    find_start_station,
    find_stations_along_route,
    thin_stations,
)


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

    # The tank starts empty: fill up at the cheapest station near the start.
    # If there's none nearby, assume the trip starts with a full tank.
    start_station = find_start_station(start.lat, start.lng, settings.START_STATION_RADIUS_MILES)

    along_route = find_stations_along_route(route.coordinates, settings.FUEL_CORRIDOR_MILES)
    if start_station:
        along_route = [s for s in along_route if s.station_id != start_station.station_id]

    def plan_with(stations: list[StationCandidate]) -> FuelPlan:
        return plan_fuel_stops(
            ([start_station] if start_station else []) + stations,
            trip_miles=route.distance_miles,
            tank_range_miles=settings.VEHICLE_RANGE_MILES,
            mpg=settings.VEHICLE_MPG,
            starts_with_full_tank=start_station is None,
            min_saving_per_gallon=settings.MIN_SAVING_PER_GALLON,
        )

    try:
        # Usually: only the cheapest station in each stretch, for fewer stops.
        fuel_plan = plan_with(thin_stations(along_route, settings.STOP_SPACING_MILES))
    except FuelPlanError:
        # Thinning can drop the stations on either side of a long gap. Before
        # saying the trip is impossible, try again with every station.
        fuel_plan = plan_with(along_route)

    return TripPlan(start=start, finish=finish, route=route, fuel_plan=fuel_plan)
