import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from planner.models import FuelStation, Town
from planner.tests.test_api import TRIP, add_station, ors_response

MAP_URL = reverse("route-plan-map")


@override_settings(ORS_API_KEY="test-key")
class RoutePlanMapPageTests(TestCase):
    def setUp(self):
        cache.clear()
        Town.objects.create(
            name="Start Town", normalized_name="start town", state="KS", lat=40.0, lng=-104.0
        )
        Town.objects.create(
            name="End Town", normalized_name="end town", state="KS", lat=40.0, lng=-92.0
        )
        add_station(1, -104.0, "3.50")
        add_station(4, -98.0, "2.90")
        add_station(6, -94.0, "3.10")

        patcher = mock.patch("planner.services.routing.requests.post", return_value=ors_response())
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def test_renders_map_with_route_and_stops(self):
        response = self.client.get(MAP_URL, TRIP)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertContains(response, "leaflet")
        self.assertContains(response, "Start Town, KS")
        self.assertContains(response, "Station 1")

    def test_map_data_has_numbers_not_strings(self):
        # The page's JavaScript formats these with toFixed(), which needs numbers.
        html = self.client.get(MAP_URL, TRIP).content.decode()
        raw = html.split('<script id="plan-data" type="application/json">')[1].split("</script>")[0]
        stop = json.loads(raw)["fuel_stops"][0]

        for field in ("price_per_gallon", "gallons", "cost_usd", "lat", "lng", "route_mile"):
            self.assertIsInstance(stop[field], (int, float), field)

    def test_lets_the_tile_server_see_which_site_is_asking(self):
        # OpenStreetMap blocks map tiles requested without a Referer. Send the
        # origin only (never the full URL with the trip in it).
        response = self.client.get(MAP_URL, TRIP)

        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_shows_the_starting_fuel_charge_when_trip_starts_full(self):
        FuelStation.objects.filter(opis_id=1).delete()  # no station near the start

        response = self.client.get(MAP_URL, TRIP)

        self.assertContains(response, "Starting tank")
        self.assertContains(response, "Station 4")  # the first station along the route

    def test_reuses_the_cached_route_from_the_api_call(self):
        self.client.get(reverse("route-plan"), TRIP)
        self.client.get(MAP_URL, TRIP)

        self.assertEqual(self.post.call_count, 1)

    def test_shows_a_readable_error_for_bad_input(self):
        response = self.client.get(MAP_URL, {"start": "Atlantis, KS", "finish": "End Town, KS"})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Could not find", status_code=400)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

    def test_shows_a_readable_error_for_missing_parameters(self):
        response = self.client.get(MAP_URL, {"start": "Start Town, KS"})

        self.assertContains(response, "finish", status_code=400)

    def test_station_names_are_escaped(self):
        FuelStation.objects.filter(opis_id=1).update(name="</script><b>Bad & Co</b>")

        response = self.client.get(MAP_URL, TRIP)

        self.assertNotContains(response, "</script><b>")
        # Still shown, but as text: the panel escapes it like any other name.
        self.assertContains(response, "&lt;/script&gt;&lt;b&gt;Bad &amp; Co&lt;/b&gt;")
