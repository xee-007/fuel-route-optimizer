"""
Choose where to buy fuel along a route, and how much, so the trip costs as little as possible.

Stations are points along the route (mile markers from the start) and the tank
holds `tank_range_miles` worth of fuel. This greedy rule gives the cheapest plan:

    At each station:
      1. If a CHEAPER station is within range, buy just enough fuel to reach it.
      2. Otherwise, if the finish is within range, buy just enough to finish.
      3. Otherwise, fill the tank and drive to the cheapest station within range.

Why it's optimal: fuel is never carried past a cheaper station (it's better
bought there), and when every reachable station is pricier, filling up here
buys as much of the cheaper fuel as the tank can hold.

Saving a cent or two isn't worth an extra stop, so `min_saving_per_gallon` sets
how much cheaper a station must be to count as "cheaper" (rule 1). After filling
up (rule 3), the plan drives to the farthest station priced within that margin
of the cheapest one. With a margin of 0 the plan is exactly the cheapest.

This module is plain Python (no Django), so it's easy to test and reason about.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class StationCandidate:
    """A fuel station somewhere along the route."""

    station_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lng: float
    price_per_gallon: Decimal
    route_mile: float  # distance from the start of the route, in miles


@dataclass(frozen=True)
class FuelStop:
    station: StationCandidate
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    stops: list[FuelStop]
    total_gallons: Decimal
    total_cost: Decimal
    starts_with_full_tank: bool


class FuelPlanError(Exception):
    """No plan is possible. The message is safe to show to API users."""


# A full tank at the start works exactly like a free station at mile 0.
_STARTING_TANK = StationCandidate(
    station_id=0,
    name="Starting tank",
    address="",
    city="",
    state="",
    lat=0.0,
    lng=0.0,
    price_per_gallon=Decimal("0"),
    route_mile=0.0,
)


def plan_fuel_stops(
    stations: Sequence[StationCandidate],
    trip_miles: float,
    tank_range_miles: float,
    mpg: float,
    starts_with_full_tank: bool,
    min_saving_per_gallon: Decimal = Decimal("0"),
) -> FuelPlan:
    """Return the cheapest set of fuel stops for the trip.

    With an empty tank, there must be a station at mile 0 to fill up before leaving.
    """
    if trip_miles <= 0:
        return _build_plan([], mpg, starts_with_full_tank)

    # Only stations before the finish matter. Cheaper first when two share a mile marker.
    route = sorted(
        (s for s in stations if s.route_mile <= trip_miles),
        key=lambda s: (s.route_mile, s.price_per_gallon),
    )
    if starts_with_full_tank:
        route.insert(0, _STARTING_TANK)
    if not route or route[0].route_mile > 0:
        raise FuelPlanError("There is no fuel station at the start of the route.")

    purchases: list[tuple[StationCandidate, float]] = []  # (station, miles of fuel bought)
    fuel_left = 0.0  # miles of driving left in the tank
    i = 0

    while True:
        here = route[i]
        reachable = [
            j
            for j in range(i + 1, len(route))
            if route[j].route_mile - here.route_mile <= tank_range_miles
        ]
        worth_stopping_below = here.price_per_gallon - min_saving_per_gallon
        cheaper = next(
            (j for j in reachable if route[j].price_per_gallon < worth_stopping_below), None
        )

        if cheaper is not None:
            # Rule 1: buy just enough to reach the next cheaper station.
            next_i = cheaper
            miles_to_buy = max(0.0, route[next_i].route_mile - here.route_mile - fuel_left)
        elif trip_miles - here.route_mile <= tank_range_miles:
            # Rule 2: buy just enough to reach the finish.
            purchases.append((here, max(0.0, trip_miles - here.route_mile - fuel_left)))
            break
        elif reachable:
            # Rule 3: fill up, then go to the cheapest station in range. Of the
            # stations within the saving margin of that price, take the farthest:
            # fewer stops for (at most) a few cents more.
            cheapest_price = min(route[j].price_per_gallon for j in reachable)
            next_i = max(
                (
                    j
                    for j in reachable
                    if route[j].price_per_gallon <= cheapest_price + min_saving_per_gallon
                ),
                key=lambda j: route[j].route_mile,
            )
            miles_to_buy = tank_range_miles - fuel_left
        else:
            raise FuelPlanError(
                f"The route has a stretch of more than {tank_range_miles:g} miles with no "
                f"known fuel station (after mile {here.route_mile:.0f})."
            )

        purchases.append((here, miles_to_buy))
        fuel_left += miles_to_buy - (route[next_i].route_mile - here.route_mile)
        i = next_i

    return _build_plan(purchases, mpg, starts_with_full_tank)


def _build_plan(
    purchases: list[tuple[StationCandidate, float]], mpg: float, starts_with_full_tank: bool
) -> FuelPlan:
    stops = []
    for station, miles in purchases:
        gallons = Decimal(miles / mpg).quantize(CENT, ROUND_HALF_UP)
        # The starting tank isn't a real stop, and a 0.00-gallon "stop" isn't worth reporting.
        if station is _STARTING_TANK or gallons == 0:
            continue
        cost = (gallons * station.price_per_gallon).quantize(CENT, ROUND_HALF_UP)
        stops.append(FuelStop(station=station, gallons=gallons, cost=cost))

    return FuelPlan(
        stops=stops,
        total_gallons=sum((stop.gallons for stop in stops), Decimal("0.00")),
        total_cost=sum((stop.cost for stop in stops), Decimal("0.00")),
        starts_with_full_tank=starts_with_full_tank,
    )
