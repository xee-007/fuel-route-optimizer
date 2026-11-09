from decimal import Decimal
from unittest import mock

from django.test import TestCase

from planner.models import FuelStation, Town
from planner.services.fuel_planner import FuelPlanError
from planner.services.geo import cumulative_miles
from planner.services.routing import Route
from planner.services.trip_planner import plan_trip

# A straight ~1,000-mile route east along latitude 40.
ROUTE_POINTS = [(-110.0 + 0.1 * i, 40.0) for i in range(190)]
MILES = cumulative_miles(ROUTE_POINTS)
MILES_PER_DEGREE = MILES[-1] / (ROUTE_POINTS[-1][0] - ROUTE_POINTS[0][0])
ROUTE = Route(coordinates=ROUTE_POINTS, distance_miles=1000.0, duration_hours=16.0)


def add_station_at_mile(opis_id: int, mile: float, price: str) -> None:
    FuelStation.objects.create(
        opis_id=opis_id,
        name=f"Mile {mile} station",
        address="I-70",
        city="Town",
        state="KS",
        rack_id=1,
        price_per_gallon=Decimal(price),
        lat=40.0,
        lng=-110.0 + mile / MILES_PER_DEGREE,
    )


@mock.patch("planner.services.trip_planner.get_route", return_value=ROUTE)
class ThinningNeverBlocksAPossibleTripTests(TestCase):
    def setUp(self):
        Town.objects.create(
            name="Start Town", normalized_name="start town", state="KS", lat=40.0, lng=-110.0
        )
        Town.objects.create(
            name="End Town", normalized_name="end town", state="KS", lat=40.0, lng=-91.1
        )
        # Thinning keeps one station per 25-mile stretch: 101 over 124 and 620
        # over 604, which leaves a 519-mile gap. Every station: at most 480 miles.
        for opis_id, mile, price in [
            (1, 0, "3.00"),
            (2, 101, "3.00"),
            (3, 124, "3.40"),
            (4, 604, "3.40"),
            (5, 620, "3.00"),
            (6, 900, "3.20"),
        ]:
            add_station_at_mile(opis_id, mile, price)

    def test_plans_with_every_station_when_thinning_leaves_a_gap(self, _):
        plan = plan_trip("Start Town, KS", "End Town, KS")

        # Mile 124 (dropped by thinning) bridges the gap: from there a full tank
        # reaches the cheaper station at mile 620, so 604 isn't needed.
        stop_ids = [stop.station.station_id for stop in plan.fuel_plan.stops]
        self.assertEqual(stop_ids, [1, 2, 3, 5])

    def test_a_real_gap_is_reported_with_its_real_miles(self, _):
        FuelStation.objects.filter(opis_id=3).delete()  # now 101 -> 604 is 503 miles

        with self.assertRaisesMessage(FuelPlanError, "between mile 101 and mile 60"):
            plan_trip("Start Town, KS", "End Town, KS")
