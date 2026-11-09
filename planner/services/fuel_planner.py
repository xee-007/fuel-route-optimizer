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
class StartingFuel:
    """Fuel used from a tank that was full at the start, charged at the price
    of `station`: the first station along the route."""

    station: StationCandidate
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True)
class FuelPlan:
    stops: list[FuelStop]
    starting_fuel: StartingFuel | None  # only when the trip starts on a full tank
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
    With a full tank, the fuel used from it is charged at the first station's price.
    """
    if trip_miles <= 0:
        return _build_plan([], trip_miles, mpg, starts_with_full_tank, first_station=None)

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
            raise FuelPlanError(_gap_message(route, i, trip_miles, tank_range_miles))

        purchases.append((here, miles_to_buy))
        fuel_left += miles_to_buy - (route[next_i].route_mile - here.route_mile)
        i = next_i

    first_station = route[1] if starts_with_full_tank and len(route) > 1 else None
    return _build_plan(purchases, trip_miles, mpg, starts_with_full_tank, first_station)


def _gap_message(
    route: list[StationCandidate], i: int, trip_miles: float, tank_range_miles: float
) -> str:
    here = route[i].route_mile
    if i + 1 < len(route):
        gap_end = f"mile {route[i + 1].route_mile:.0f}"
    else:
        gap_end = f"the finish (mile {trip_miles:.0f})"
    return (
        f"No fuel station from the price list between mile {here:.0f} and {gap_end} "
        f"of the route, and a full tank only lasts {tank_range_miles:g} miles."
    )


def _build_plan(
    purchases: list[tuple[StationCandidate, float]],
    trip_miles: float,
    mpg: float,
    starts_with_full_tank: bool,
    first_station: StationCandidate | None,
) -> FuelPlan:
    stops = []
    bought_miles = 0.0
    for station, miles in purchases:
        if station is _STARTING_TANK:
            continue  # the starting tank isn't a real stop
        bought_miles += miles
        gallons = _gallons(miles, mpg)
        if gallons > 0:  # a 0.00-gallon "stop" isn't worth reporting
            stops.append(FuelStop(station, gallons, _cost(gallons, station.price_per_gallon)))

    starting_fuel = None
    if first_station is not None:
        # The tank is empty at the finish, so every mile not covered by fuel
        # bought along the way was driven on the starting tank.
        gallons = _gallons(trip_miles - bought_miles, mpg)
        if gallons > 0:
            cost = _cost(gallons, first_station.price_per_gallon)
            starting_fuel = StartingFuel(first_station, gallons, cost)

    charged = [*stops, *([starting_fuel] if starting_fuel else [])]
    return FuelPlan(
        stops=stops,
        starting_fuel=starting_fuel,
        total_gallons=sum((line.gallons for line in charged), Decimal("0.00")),
        total_cost=sum((line.cost for line in charged), Decimal("0.00")),
        starts_with_full_tank=starts_with_full_tank,
    )


def _gallons(miles: float, mpg: float) -> Decimal:
    return Decimal(miles / mpg).quantize(CENT, ROUND_HALF_UP)


def _cost(gallons: Decimal, price_per_gallon: Decimal) -> Decimal:
    return (gallons * price_per_gallon).quantize(CENT, ROUND_HALF_UP)
