"""
Tests for the fuel-stop planner. All cases use a 500-mile tank and 10 mpg,
so 1 gallon = 10 miles and a full tank = 50 gallons. The expected numbers
can be checked by hand.
"""

import random
from dataclasses import replace
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


def plan(stations, trip_miles, min_saving_per_stop="0"):
    return plan_fuel_stops(
        stations,
        trip_miles=trip_miles,
        tank_range_miles=500,
        mpg=10,
        min_saving_per_stop=Decimal(min_saving_per_stop),
    )


def summary(fuel_plan) -> list[tuple[int, str, str]]:
    """(station id, gallons, cost) for each stop, as strings for readable failures."""
    return [(s.station.station_id, str(s.gallons), str(s.cost)) for s in fuel_plan.stops]


class EmptyTankStartTests(SimpleTestCase):
    def test_short_trip_buys_just_enough_at_start(self):
        result = plan([station("A", 0, "3.00")], trip_miles=100)

        self.assertEqual(summary(result), [(A, "10.00", "30.00")])
        self.assertIsNone(result.starting_fuel)  # a station right at the start

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


class FirstStationTests(SimpleTestCase):
    """The trip starts with just enough fuel to reach the first station along the
    route, charged at that station's price."""

    def test_first_station_is_the_first_stop(self):
        result = plan([station("B", 100, "3.20"), station("C", 250, "2.90")], trip_miles=300)

        # Start: 100 mi (10 gal) charged at B. B: just enough to reach the cheaper
        # C (150 mi). C: the last 50 mi to the finish.
        self.assertEqual(result.starting_fuel.station.station_id, B)
        self.assertEqual(result.starting_fuel.gallons, Decimal("10.00"))
        self.assertEqual(result.starting_fuel.cost, Decimal("32.00"))
        self.assertEqual(summary(result), [(B, "15.00", "48.00"), (C, "5.00", "14.50")])
        self.assertEqual(result.total_gallons, Decimal("30.00"))
        self.assertEqual(result.total_cost, Decimal("94.50"))

    def test_short_trip_still_stops_at_the_first_station(self):
        result = plan([station("B", 5, "3.00")], trip_miles=100)

        self.assertEqual(summary(result), [(B, "9.50", "28.50")])
        self.assertEqual(result.starting_fuel.cost, Decimal("1.50"))
        self.assertEqual(result.total_cost, Decimal("30.00"))

    def test_first_station_farther_than_a_tank_raises(self):
        with self.assertRaisesMessage(FuelPlanError, "between mile 0 and mile 600"):
            plan([station("B", 600, "3.00")], trip_miles=900)

    def test_no_station_along_the_route_raises(self):
        with self.assertRaisesMessage(
            FuelPlanError, "No fuel station from the price list along this route"
        ):
            plan([station("Z", 400, "3.00")], trip_miles=300)  # only past the finish


class MinimumSavingPerStopTests(SimpleTestCase):
    """An extra stop has to save at least a set amount of money to be worth it."""

    # Houston -> Dallas: three stations, each a little cheaper than the last.
    HUNTSVILLE = station("A", 69, "2.979")
    CENTERVILLE = station("B", 116, "2.846")
    WILMER = station("C", 223, "2.756")

    def test_without_a_minimum_the_plan_is_simply_the_cheapest(self):
        result = plan([self.HUNTSVILLE, self.CENTERVILLE, self.WILMER], trip_miles=240)

        self.assertEqual(
            summary(result), [(A, "4.70", "14.00"), (B, "10.70", "30.45"), (C, "1.70", "4.69")]
        )
        self.assertEqual(result.total_cost, Decimal("69.70"))

    def test_drops_stops_that_save_less_than_the_minimum(self):
        result = plan(
            [self.HUNTSVILLE, self.CENTERVILLE, self.WILMER],
            trip_miles=240,
            min_saving_per_stop="3",
        )

        # Two extra stops saved only $1.80 in total: fill up once at Huntsville.
        self.assertEqual(summary(result), [(A, "17.10", "50.94")])
        self.assertEqual(result.starting_fuel.cost, Decimal("20.56"))
        self.assertEqual(result.total_cost, Decimal("71.50"))

    def test_skipping_a_stop_means_not_stopping_anywhere_nearby_either(self):
        # B and B2 are equally cheap: dropping B alone would just stop at B2 instead.
        stations = [station("A", 50, "3.00"), station("B", 100, "2.90"), station("D", 110, "2.90")]

        result = plan(stations, trip_miles=200, min_saving_per_stop="3")

        self.assertEqual(summary(result), [(A, "15.00", "45.00")])
        self.assertEqual(result.total_cost, Decimal("60.00"))  # the 2-stop plan was $59.00

    def test_keeps_a_stop_that_saves_enough(self):
        stations = [station("A", 0, "4.00"), station("B", 100, "3.00")]

        result = plan(stations, trip_miles=300, min_saving_per_stop="3")

        # Skipping B would mean buying 20 more gallons at $1 more: $20 > $3.
        self.assertEqual(summary(result), [(A, "10.00", "40.00"), (B, "20.00", "60.00")])

    def test_never_drops_a_stop_the_trip_needs(self):
        stations = [station("A", 0, "3.00"), station("B", 400, "3.10"), station("C", 800, "3.20")]

        result = plan(stations, trip_miles=1000, min_saving_per_stop="100")

        self.assertEqual([s.station.station_id for s in result.stops], [A, B, C])


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
                        plan_fuel_stops(stations, trip, 40, 1)
                else:
                    result = plan_fuel_stops(stations, trip, 40, 1)
                    self.assertEqual(result.total_cost, expected)

    def test_routes_starting_away_from_a_station_match_brute_force_too(self):
        rng = random.Random(2027)
        prices = ["2.50", "2.75", "3.00", "3.25", "3.50", "3.75", "4.00"]

        for trial in range(200):
            trip = rng.randint(2, 150)
            stations = [
                station(chr(66 + n), rng.randint(1, trip), rng.choice(prices))
                for n in range(rng.randint(1, 6))
            ]
            first = min(stations, key=lambda s: (s.route_mile, s.price_per_gallon))
            # After reaching the first station, it's an ordinary empty-tank trip from there.
            shifted = [replace(s, route_mile=s.route_mile - first.route_mile) for s in stations]
            expected = brute_force_cheapest_cost(shifted, trip - first.route_mile, tank_miles=40)

            with self.subTest(trial=trial, trip=trip):
                if expected is None or first.route_mile > 40:
                    with self.assertRaises(FuelPlanError):
                        plan_fuel_stops(stations, trip, 40, 1)
                    continue
                result = plan_fuel_stops(stations, trip, 40, 1)
                self.assertEqual(sum((s.cost for s in result.stops), Decimal("0")), expected)
                if first.route_mile:
                    self.assertEqual(result.starting_fuel.gallons, Decimal(first.route_mile))
                    self.assertEqual(result.starting_fuel.station, first)
