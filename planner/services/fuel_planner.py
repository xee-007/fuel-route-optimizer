"""
Choose where to buy fuel along a route, and how much, so the trip costs as little as possible.

Stations are points along the route (mile markers from the start) and the tank
holds `tank_range_miles` worth of fuel. The trip starts with just enough fuel to
reach the first station, and that fuel is charged at the first station's price.
From there, this greedy rule gives the cheapest plan:

    At each station:
      1. If a CHEAPER station is within range, buy just enough fuel to reach it.
      2. Otherwise, if the finish is within range, buy just enough to finish.
      3. Otherwise, fill the tank and drive to the cheapest station within range.

Why it's optimal: fuel is never carried past a cheaper station (it's better
bought there), and when every reachable station is pricier, filling up here
buys as much of the cheaper fuel as the tank can hold.

Saving a dollar or two isn't worth an extra stop, so with `min_saving_per_stop`
the cheapest plan is then simplified: for each stop, try driving straight past it
(from the stop before to the stop after, without stopping in between). If that
plan has fewer stops and costs less than that much more per stop saved, keep it.
With 0, the plan is exactly the cheapest.

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
class StartingFuel:
    """The fuel used to reach the first station along the route (`station`),
    charged at that station's price."""

    station: StationCandidate
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    stops: list[FuelStop]
    starting_fuel: StartingFuel | None  # None when the first station is at the start
    total_gallons: Decimal
    total_cost: Decimal


class FuelPlanError(Exception):
    """No plan is possible. The message is safe to show to API users."""


def plan_fuel_stops(
    stations: Sequence[StationCandidate],
    trip_miles: float,
    tank_range_miles: float,
    mpg: float,
    min_saving_per_stop: Decimal = Decimal("0"),
) -> FuelPlan:
    """The cheapest fuel plan, without stops that save less than `min_saving_per_stop`."""
    if trip_miles <= 0:
        return _build_plan([], mpg, first_station=None)

    # Only stations before the finish matter. Cheaper first when two share a mile marker.
    route = sorted(
        (s for s in stations if s.route_mile <= trip_miles),
        key=lambda s: (s.route_mile, s.price_per_gallon),
    )
    if not route:
        raise FuelPlanError("No fuel station from the price list along this route.")

    plan = _cheapest_plan(route, trip_miles, tank_range_miles, mpg)
    if min_saving_per_stop > 0:
        plan = _drop_stops_not_worth_it(
            plan, route, trip_miles, tank_range_miles, mpg, min_saving_per_stop
        )
    return plan


def _cheapest_plan(
    route: list[StationCandidate], trip_miles: float, tank_range_miles: float, mpg: float
) -> FuelPlan:
    """The greedy rule from the top of this module. `route` is sorted by mile."""
    if route[0].route_mile > tank_range_miles:
        raise FuelPlanError(_gap_message(0, route[0].route_mile, trip_miles, tank_range_miles))

    purchases: list[tuple[StationCandidate, float]] = []  # (station, miles of fuel bought)
    fuel_left = 0.0  # miles of driving left in the tank
    i = 0

    while True:
        here = route[i]
        reachable = []
        for j in range(i + 1, len(route)):
            if route[j].route_mile - here.route_mile > tank_range_miles:
                break  # sorted by mile, so every later station is out of range too
            reachable.append(j)
        cheaper = next(
            (j for j in reachable if route[j].price_per_gallon < here.price_per_gallon), None
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
            # Rule 3: fill up, then go to the cheapest station in range
            # (the farthest one if several share that price: fewer stops).
            next_i = min(reachable, key=lambda j: (route[j].price_per_gallon, -route[j].route_mile))
            miles_to_buy = tank_range_miles - fuel_left
        else:
            next_mile = route[i + 1].route_mile if i + 1 < len(route) else trip_miles
            raise FuelPlanError(
                _gap_message(here.route_mile, next_mile, trip_miles, tank_range_miles)
            )

        purchases.append((here, miles_to_buy))
        fuel_left += miles_to_buy - (route[next_i].route_mile - here.route_mile)
        i = next_i

    return _build_plan(purchases, mpg, first_station=route[0])


def _drop_stops_not_worth_it(
    plan: FuelPlan,
    route: list[StationCandidate],
    trip_miles: float,
    tank_range_miles: float,
    mpg: float,
    min_saving_per_stop: Decimal,
) -> FuelPlan:
    """Skip every stop that saves less than `min_saving_per_stop`.

    To skip a stop, plan again without any station between the stop before it
    and the stop after it (or the finish). Keep the result if it has fewer stops
    and costs less than the minimum saving per stop skipped. Repeat until every
    stop is worth it. The first station always stays: the fuel to reach it is
    charged at its price.
    """
    while True:
        best: tuple[Decimal, FuelPlan, list[StationCandidate]] | None = None
        for k, stop in enumerate(plan.stops):
            if stop.station.station_id == route[0].station_id:
                continue
            before = plan.stops[k - 1].station.route_mile if k > 0 else route[0].route_mile
            after = plan.stops[k + 1].station.route_mile if k + 1 < len(plan.stops) else trip_miles
            without = [s for s in route if not before < s.route_mile < after]
            try:
                simpler = _cheapest_plan(without, trip_miles, tank_range_miles, mpg)
            except FuelPlanError:
                continue  # the trip needs a stop here
            stops_saved = len(plan.stops) - len(simpler.stops)
            extra_cost = simpler.total_cost - plan.total_cost
            if stops_saved > 0 and extra_cost < min_saving_per_stop * stops_saved:
                if best is None or extra_cost < best[0]:
                    best = (extra_cost, simpler, without)
        if best is None:
            return plan
        _, plan, route = best


def _gap_message(
    from_mile: float, to_mile: float, trip_miles: float, tank_range_miles: float
) -> str:
    gap_end = (
        f"the finish (mile {trip_miles:.0f})" if to_mile >= trip_miles else f"mile {to_mile:.0f}"
    )
    return (
        f"No fuel station from the price list between mile {from_mile:.0f} and {gap_end} "
        f"of the route, and a full tank only lasts {tank_range_miles:g} miles."
    )


def _build_plan(
    purchases: list[tuple[StationCandidate, float]],
    mpg: float,
    first_station: StationCandidate | None,
) -> FuelPlan:
    stops = []
    for station, miles in purchases:
        gallons = _gallons(miles, mpg)
        if gallons > 0:  # a 0.00-gallon "stop" isn't worth reporting
            stops.append(FuelStop(station, gallons, _cost(gallons, station.price_per_gallon)))

    starting_fuel = None
    if first_station is not None:
        gallons = _gallons(first_station.route_mile, mpg)  # the drive to the first station
        if gallons > 0:
            cost = _cost(gallons, first_station.price_per_gallon)
            starting_fuel = StartingFuel(first_station, gallons, cost)

    charged = [*([starting_fuel] if starting_fuel else []), *stops]
    return FuelPlan(
        stops=stops,
        starting_fuel=starting_fuel,
        total_gallons=sum((line.gallons for line in charged), Decimal("0.00")),
        total_cost=sum((line.cost for line in charged), Decimal("0.00")),
    )


def _gallons(miles: float, mpg: float) -> Decimal:
    return Decimal(miles / mpg).quantize(CENT, ROUND_HALF_UP)


def _cost(gallons: Decimal, price_per_gallon: Decimal) -> Decimal:
    return (gallons * price_per_gallon).quantize(CENT, ROUND_HALF_UP)
