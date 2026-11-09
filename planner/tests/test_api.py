from decimal import ROUND_HALF_UP, Decimal
from unittest import mock

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from planner.models import FuelStation, Town
from planner.services.geo import cumulative_miles

# A straight 636-mile route along latitude 40, from Start Town to End Town.
ROUTE = [(-104.0 + 0.6 * i, 40.0) for i in range(21)]
ROUTE_MILES = cumulative_miles(ROUTE)[-1]

URL = reverse("route-plan")
TRIP = {"start": "Start Town, KS", "finish": "End Town, KS"}


def ors_response() -> mock.Mock:
    response = mock.Mock(status_code=200)
    response.json.return_value = {
        "features": [
            {
                "geometry": {"type": "LineString", "coordinates": [list(p) for p in ROUTE]},
                "properties": {
                    "summary": {"distance": ROUTE_MILES * 1609.344, "duration": ROUTE_MILES * 60}
                },
            }
        ]
    }
    return response


def add_station(opis_id: int, lng: float, price: str) -> None:
    FuelStation.objects.create(
        opis_id=opis_id,
        name=f"Station {opis_id}",
        address="I-70, EXIT 1",
        city="Town",
        state="KS",
        rack_id=1,
        price_per_gallon=Decimal(price),
        lat=40.0,
        lng=lng,
    )


@override_settings(ORS_API_KEY="test-key")
class RoutePlanApiTests(TestCase):
    def setUp(self):
        cache.clear()
        Town.objects.create(
            name="Start Town", normalized_name="start town", state="KS", lat=40.0, lng=-104.0
        )
        Town.objects.create(
            name="End Town", normalized_name="end town", state="KS", lat=40.0, lng=-92.0
        )
        add_station(1, -104.0, "3.50")  # at the start
        add_station(2, -102.0, "3.20")
        add_station(3, -100.0, "3.40")
        add_station(4, -98.0, "2.90")
        add_station(5, -96.0, "3.30")
        add_station(6, -94.0, "3.10")

        patcher = mock.patch("planner.services.routing.requests.post", return_value=ors_response())
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def get_plan(self, **params):
        return self.client.get(URL, params or TRIP)

    def test_returns_plan_with_route_stops_and_total(self):
        response = self.get_plan()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            list(data),
            [
                "start",
                "finish",
                "distance_miles",
                "duration_hours",
                "fuel_summary",
                "fuel_stops",
                "route",
                "map_url",
            ],
        )
        self.assertEqual(data["start"], {"label": "Start Town, KS", "lat": 40.0, "lng": -104.0})
        self.assertAlmostEqual(data["distance_miles"], ROUTE_MILES, delta=0.1)
        self.assertEqual(data["fuel_stops"][0]["route_mile"], 0.0)
        self.assertEqual(data["fuel_stops"][0]["station_id"], 1)
        self.assertEqual(data["fuel_stops"][0]["stop_number"], 1)

    def test_total_gallons_cover_the_whole_trip(self):
        summary = self.get_plan().json()["fuel_summary"]

        self.assertEqual(summary["miles_per_gallon"], 10)
        self.assertEqual(summary["tank_range_miles"], 500)
        self.assertEqual(
            list(summary),
            [
                "miles_per_gallon",
                "tank_range_miles",
                "total_gallons",
                "total_cost_usd",
                "starting_fuel",
            ],
        )
        self.assertAlmostEqual(summary["total_gallons"], ROUTE_MILES / 10, delta=0.05)
        self.assertIsNone(summary["starting_fuel"])  # station 1 is right at the start

    def test_total_cost_equals_sum_of_stop_costs(self):
        data = self.get_plan().json()

        stop_costs = sum(Decimal(str(stop["cost_usd"])) for stop in data["fuel_stops"])
        self.assertEqual(Decimal(str(data["fuel_summary"]["total_cost_usd"])), stop_costs)

    def test_prices_are_exact_so_each_stop_adds_up(self):
        # Prices in the list often have 8 decimals; rounding them in the response
        # would make gallons x price differ from the cost by a cent.
        FuelStation.objects.filter(opis_id=4).update(price_per_gallon=Decimal("2.89733333"))

        stops = self.get_plan().json()["fuel_stops"]

        self.assertIn(2.89733333, [stop["price_per_gallon"] for stop in stops])
        for stop in stops:
            gallons, price = Decimal(str(stop["gallons"])), Decimal(str(stop["price_per_gallon"]))
            expected = (gallons * price).quantize(Decimal("0.01"), ROUND_HALF_UP)
            self.assertEqual(Decimal(str(stop["cost_usd"])), expected, stop["name"])

    def test_total_includes_fuel_to_reach_the_first_station(self):
        FuelStation.objects.filter(opis_id=1).delete()  # no station at the start

        data = self.get_plan().json()

        summary = data["fuel_summary"]
        stops = sum(Decimal(str(stop["cost_usd"])) for stop in data["fuel_stops"])
        starting = Decimal(str(summary["starting_fuel"]["cost_usd"]))
        self.assertEqual(Decimal(str(summary["total_cost_usd"])), stops + starting)
        self.assertAlmostEqual(summary["total_gallons"], ROUTE_MILES / 10, delta=0.05)

    def test_route_is_geojson_in_lng_lat_order(self):
        route = self.get_plan().json()["route"]

        self.assertEqual(route["type"], "LineString")
        self.assertEqual(route["coordinates"][0], [-104.0, 40.0])
        self.assertEqual(route["coordinates"][-1], [-92.0, 40.0])

    def test_map_url_points_at_map_page_with_same_query(self):
        map_url = self.get_plan().json()["map_url"]

        self.assertTrue(map_url.startswith("http://testserver/api/v1/route-plan/map/?"))
        self.assertIn("start=Start+Town%2C+KS", map_url)
        self.assertIn("finish=End+Town%2C+KS", map_url)

    def test_calls_routing_api_once_then_uses_cache(self):
        self.get_plan()
        self.get_plan()

        self.assertEqual(self.post.call_count, 1)

    def test_first_stop_is_the_first_station_when_none_is_at_the_start(self):
        FuelStation.objects.filter(opis_id=1).delete()

        data = self.get_plan().json()

        first_stop = data["fuel_stops"][0]
        self.assertEqual(first_stop["station_id"], 2)
        # The ~106 miles to get there are charged at station 2's price ($3.20).
        starting = data["fuel_summary"]["starting_fuel"]
        self.assertEqual(starting["priced_at"]["station_id"], 2)
        self.assertAlmostEqual(starting["gallons"], first_stop["route_mile"] / 10, delta=0.01)
        self.assertEqual(starting["price_per_gallon"], 3.2)

    def assert_error(self, response, status: int, code: str) -> str:
        self.assertEqual(response.status_code, status)
        error = response.json()["error"]
        self.assertEqual(error["code"], code)
        return error["message"]

    def test_missing_finish_returns_400(self):
        message = self.assert_error(self.get_plan(start="Start Town, KS"), 400, "invalid_request")

        self.assertIn("finish", message)

    def test_unknown_town_returns_400_without_calling_routing_api(self):
        response = self.get_plan(start="Atlantis, KS", finish="End Town, KS")

        self.assertIn("Atlantis, KS", self.assert_error(response, 400, "invalid_location"))
        self.post.assert_not_called()

    def test_routing_timeout_returns_504(self):
        self.post.side_effect = requests.Timeout()

        self.assert_error(self.get_plan(), 504, "routing_timeout")

    def test_fuel_gap_returns_422(self):
        FuelStation.objects.exclude(opis_id=1).delete()

        message = self.assert_error(self.get_plan(), 422, "no_fuel_plan")

        self.assertIn("between mile 0 and the finish", message)

    def test_other_api_errors_use_the_same_shape(self):
        self.assert_error(self.client.post(URL, TRIP), 405, "method_not_allowed")
