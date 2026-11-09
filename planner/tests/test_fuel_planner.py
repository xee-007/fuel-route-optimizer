"""
Tests for the fuel-stop planner. All cases use a 500-mile tank and 10 mpg,
so 1 gallon = 10 miles and a full tank = 50 gallons. The expected numbers
can be checked by hand.
"""

import random
from decimal import Decimal

from django.test import SimpleTestCase

from planner.services.fuel_planner import FuelPlanError, StationCandidate, plan_fuel_stops


def station(station_id: str, mile: float, price: str) -> StationCandidate:
    return StationCandidate(
        station_id=ord(station_id),
        name=f"Station {station_id}",
        address="I-70, EXIT 1",
        city="Town",
        state="KS",
        lat=39.0,
        lng=-98.0,
        price_per_gallon=Decimal(price),
        route_mile=mile,
    )


A, B, C, D = (ord(letter) for letter in "ABCD")


def plan(stations, trip_miles, full_tank=False, min_saving="0"):
    return plan_fuel_stops(
        stations,
        trip_miles=trip_miles,
        tank_range_miles=500,
        mpg=10,
        starts_with_full_tank=full_tank,
        min_saving_per_gallon=Decimal(min_saving),
    )


def summary(fuel_plan) -> list[tuple[int, str, str]]:
    """(station id, gallons, cost) for each stop, as strings for readable failures."""
    return [(s.station.station_id, str(s.gallons), str(s.cost)) for s in fuel_plan.stops]


class EmptyTankStartTests(SimpleTestCase):
    def test_short_trip_buys_just_enough_at_start(self):
        result = plan([station("A", 0, "3.00")], trip_miles=100)

        self.assertEqual(summary(result), [(A, "10.00", "30.00")])
        self.assertFalse(result.starts_with_full_tank)

    def test_buys_only_enough_to_reach_cheaper_station(self):
        result = plan([station("A", 0, "4.00"), station("B", 100, "3.00")], trip_miles=300)

        # A: 100 mi to cheaper B -> 10 gal. B: 200 mi to finish -> 20 gal.
        self.assertEqual(summary(result), [(A, "10.00", "40.00"), (B, "20.00", "60.00")])
        self.assertEqual(result.total_gallons, Decimal("30.00"))
        self.assertEqual(result.total_cost, Decimal("100.00"))

    def test_fills_up_when_no_cheaper_station_in_range(self):
        stations = [station("A", 0, "3.00"), station("B", 400, "4.00"), station("C", 800, "3.50")]

        result = plan(stations, trip_miles=1000)

        # A: nothing cheaper within 500 mi -> fill up (50 gal), drive to B (100 mi left).
        # B: C is cheaper -> buy 300 mi (30 gal) to reach it. C: 200 mi to finish -> 20 gal.
        self.assertEqual(
            summary(result),
            [(A, "50.00", "150.00"), (B, "30.00", "120.00"), (C, "20.00", "70.00")],
        )
        self.assertEqual(result.total_cost, Decimal("340.00"))

    def test_totals_equal_sum_of_stops(self):
        stations = [station("A", 0, "3.00"), station("B", 400, "4.00"), station("C", 800, "3.50")]

        result = plan(stations, trip_miles=1000)

        self.assertEqual(result.total_gallons, sum(s.gallons for s in result.stops))
        self.assertEqual(result.total_cost, sum(s.cost for s in result.stops))

    def test_equal_prices_ahead_prefer_the_farthest_station(self):
        stations = [
            station("A", 0, "3.00"),
            station("B", 100, "3.50"),
            station("C", 300, "3.50"),
            station("D", 700, "3.60"),
        ]

        result = plan(stations, trip_miles=1000)

        # Skipping B (same price as C, but nearer) saves a stop.
        self.assertEqual([s.station.station_id for s in result.stops], [A, C, D])

    def test_same_mile_stations_use_the_cheaper_one(self):
        result = plan([station("A", 0, "4.00"), station("B", 0, "3.00")], trip_miles=100)

        self.assertEqual(summary(result), [(B, "10.00", "30.00")])

    def test_negligible_purchases_are_not_reported_as_stops(self):
        # B is ~200 feet past A and cheaper: A's purchase rounds to 0.00 gallons.
        result = plan([station("A", 0, "3.00"), station("B", 0.04, "2.00")], trip_miles=100)

        self.assertEqual(summary(result), [(B, "10.00", "20.00")])

    def test_ignores_stations_past_finish(self):
        result = plan([station("A", 0, "3.00"), station("D", 900, "1.00")], trip_miles=100)

        self.assertEqual(summary(result), [(A, "10.00", "30.00")])

    def test_zero_length_trip_has_no_stops(self):
        result = plan([station("A", 0, "3.00")], trip_miles=0)

        self.assertEqual(result.stops, [])
        self.assertEqual(result.total_cost, Decimal("0.00"))

    def test_gap_longer_than_range_raises(self):
        with self.assertRaisesMessage(FuelPlanError, "500 miles"):
            plan([station("A", 0, "3.00"), station("B", 600, "3.00")], trip_miles=700)

    def test_gap_message_names_both_ends_of_the_gap(self):
        with self.assertRaisesMessage(FuelPlanError, "between mile 120 and mile 750"):
            plan(
                [station("A", 0, "3.00"), station("B", 120, "3.00"), station("C", 750, "3.00")],
                trip_miles=900,
            )

    def test_gap_up_to_the_finish_is_named_too(self):
        with self.assertRaisesMessage(FuelPlanError, "between mile 0 and the finish (mile 700)"):
            plan([station("A", 0, "3.00")], trip_miles=700)

    def test_missing_station_at_start_raises(self):
        with self.assertRaises(FuelPlanError):
            plan([station("B", 5, "3.00")], trip_miles=100)


class FullTankStartTests(SimpleTestCase):
    """No station near the start: the trip starts on a full tank. The fuel used
    from it is charged at the price of the first station along the route."""

    def test_short_trip_charges_starting_fuel_at_first_station_price(self):
        result = plan(
            [station("B", 100, "3.20"), station("C", 250, "2.90")], trip_miles=300, full_tank=True
        )

        self.assertEqual(result.stops, [])
        self.assertEqual(result.starting_fuel.station.station_id, B)
        self.assertEqual(result.starting_fuel.gallons, Decimal("30.00"))
        self.assertEqual(result.starting_fuel.cost, Decimal("96.00"))
        self.assertEqual(result.total_gallons, Decimal("30.00"))
        self.assertEqual(result.total_cost, Decimal("96.00"))
        self.assertTrue(result.starts_with_full_tank)

    def test_stops_at_cheapest_station_in_range(self):
        stations = [station("B", 200, "3.50"), station("C", 450, "3.00")]

        result = plan(stations, trip_miles=800, full_tank=True)

        # Drive on the starting tank to the cheapest station in range (C),
        # arriving with 50 mi left; buy the remaining 300 mi (30 gal) there.
        self.assertEqual(summary(result), [(C, "30.00", "90.00")])
        # The 500 miles of starting fuel (50 gal) are charged at B, the first station.
        self.assertEqual(result.starting_fuel.gallons, Decimal("50.00"))
        self.assertEqual(result.starting_fuel.cost, Decimal("175.00"))
        self.assertEqual(result.total_gallons, Decimal("80.00"))
        self.assertEqual(result.total_cost, Decimal("265.00"))

    def test_without_any_station_the_starting_fuel_cannot_be_priced(self):
        result = plan([], trip_miles=300, full_tank=True)

        self.assertIsNone(result.starting_fuel)
        self.assertEqual(result.total_cost, Decimal("0.00"))
        self.assertTrue(result.starts_with_full_tank)

    def test_empty_tank_start_has_no_starting_fuel_line(self):
        self.assertIsNone(plan([station("A", 0, "3.00")], trip_miles=100).starting_fuel)

    def test_gap_longer_than_range_raises(self):
        with self.assertRaises(FuelPlanError):
            plan([station("B", 600, "3.00")], trip_miles=900, full_tank=True)


class MinimumSavingTests(SimpleTestCase):
    """A cheaper station is only worth an extra stop if it saves at least N cents a gallon."""

    def test_small_saving_does_not_justify_an_extra_stop(self):
        stations = [station("A", 0, "3.00"), station("B", 100, "2.98")]

        self.assertEqual(len(plan(stations, trip_miles=300).stops), 2)
        self.assertEqual(
            summary(plan(stations, trip_miles=300, min_saving="0.05")), [(A, "30.00", "90.00")]
        )

    def test_meaningful_saving_still_gets_a_stop(self):
        stations = [station("A", 0, "3.00"), station("B", 100, "2.90")]

        result = plan(stations, trip_miles=300, min_saving="0.05")

        self.assertEqual(summary(result), [(A, "10.00", "30.00"), (B, "20.00", "58.00")])

    def test_after_filling_up_drives_to_farthest_nearly_cheapest_station(self):
        stations = [station("A", 0, "3.00"), station("B", 50, "3.10"), station("C", 480, "3.13")]

        exact = plan(stations, trip_miles=900)
        relaxed = plan(stations, trip_miles=900, min_saving="0.05")

        # Exact: A, B and C ($275.05). Relaxed: B is skipped, C is only 3 cents
        # pricier than B, so it's one stop fewer for 15 cents more ($275.20).
        self.assertEqual([s.station.station_id for s in exact.stops], [A, B, C])
        self.assertEqual(exact.total_cost, Decimal("275.05"))
        self.assertEqual(summary(relaxed), [(A, "50.00", "150.00"), (C, "40.00", "125.20")])


def brute_force_cheapest_cost(stations, trip_miles, tank_miles) -> Decimal | None:
    """Try every whole-mile amount of fuel at every station (1 mpg); None if impossible.

    `cheapest[f]` is the lowest cost of arriving at the current station with
    `f` miles of fuel in the tank.
    """
    route = sorted(stations, key=lambda s: s.route_mile)
    cheapest = {0: Decimal("0")}
    for k, here in enumerate(route):
        next_mile = route[k + 1].route_mile if k + 1 < len(route) else trip_miles
        distance = next_mile - here.route_mile
        arriving = {}
        for fuel, cost in cheapest.items():
            for bought in range(tank_miles - fuel + 1):
                if fuel + bought >= distance:
                    left = fuel + bought - distance
                    total = cost + bought * here.price_per_gallon
                    arriving[left] = min(total, arriving.get(left, total))
        if not arriving:
            return None
        cheapest = arriving
    return min(cheapest.values())


class OptimalityTests(SimpleTestCase):
    def test_matches_brute_force_on_random_routes(self):
        rng = random.Random(2026)  # fixed seed: the same 200 routes every run
        prices = ["2.50", "2.75", "3.00", "3.25", "3.50", "3.75", "4.00"]

        for trial in range(200):
            trip = rng.randint(1, 150)
            miles = [0] + [rng.randint(0, trip) for _ in range(rng.randint(0, 5))]
            stations = [
                station(chr(65 + n), mile, rng.choice(prices)) for n, mile in enumerate(miles)
            ]
            expected = brute_force_cheapest_cost(stations, trip, tank_miles=40)

            with self.subTest(
                trial=trial,
                trip=trip,
                stations=[(s.route_mile, str(s.price_per_gallon)) for s in stations],
            ):
                if expected is None:
                    with self.assertRaises(FuelPlanError):
                        plan_fuel_stops(stations, trip, 40, 1, starts_with_full_tank=False)
                else:
                    result = plan_fuel_stops(stations, trip, 40, 1, starts_with_full_tank=False)
                    self.assertEqual(result.total_cost, expected)

    def test_full_tank_starts_match_brute_force_too(self):
        rng = random.Random(2027)
        prices = ["2.50", "2.75", "3.00", "3.25", "3.50", "3.75", "4.00"]

        for trial in range(200):
            trip = rng.randint(1, 150)
            stations = [
                station(chr(66 + n), rng.randint(1, trip), rng.choice(prices))
                for n in range(rng.randint(0, 5))
            ]
            # A full tank at the start is a free station at mile 0 for the brute force.
            free_start = station("@", 0, "0")  # whole miles, like the brute force
            expected = brute_force_cheapest_cost([free_start, *stations], trip, tank_miles=40)

            with self.subTest(trial=trial, trip=trip):
                if expected is None:
                    with self.assertRaises(FuelPlanError):
                        plan_fuel_stops(stations, trip, 40, 1, starts_with_full_tank=True)
                    continue
                result = plan_fuel_stops(stations, trip, 40, 1, starts_with_full_tank=True)
                self.assertEqual(sum((s.cost for s in result.stops), Decimal("0")), expected)
                if stations:  # the starting tank is fully used, up to the trip length
                    self.assertEqual(result.starting_fuel.gallons, Decimal(min(trip, 40)))
