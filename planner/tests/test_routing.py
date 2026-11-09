import copy
import json
from pathlib import Path
from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from planner.services.locations import Location
from planner.services.routing import (
    NoRouteFound,
    Route,
    RoutingError,
    RoutingTimeout,
    RoutingUnavailable,
    fetch_route,
    get_route,
)

ORS_RESPONSE = json.loads((Path(__file__).parent / "fixtures" / "ors_response.json").read_text())

CHICAGO = Location("Chicago, IL", 41.84, -87.68)
ST_LOUIS = Location("St. Louis, MO", 38.63, -90.2)


def fake_response(status_code: int = 200, payload: dict | None = None) -> mock.Mock:
    response = mock.Mock(status_code=status_code)
    response.json.return_value = ORS_RESPONSE if payload is None else payload
    return response


@override_settings(ORS_API_KEY="test-key")
@mock.patch("planner.services.routing.requests.post")
class FetchRouteTests(SimpleTestCase):
    def test_parses_geometry_distance_and_duration(self, post):
        post.return_value = fake_response()

        route = fetch_route(CHICAGO, ST_LOUIS)

        self.assertIsInstance(route, Route)
        self.assertAlmostEqual(route.distance_miles, 10.0, places=2)
        self.assertAlmostEqual(route.duration_hours, 0.25)
        self.assertEqual(route.coordinates[0], (-87.68, 41.84))
        self.assertEqual(len(route.coordinates), 5)

    def test_sends_lng_lat_order_api_key_and_timeout(self, post):
        post.return_value = fake_response()

        fetch_route(CHICAGO, ST_LOUIS)

        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["coordinates"], [[-87.68, 41.84], [-90.2, 38.63]])
        self.assertIs(kwargs["json"]["instructions"], False)
        # Start and finish may be a little off-road (a town center in a park):
        # let the routing service look up to 5 km for the nearest road.
        self.assertEqual(kwargs["json"]["radiuses"], [5000, 5000])
        self.assertEqual(kwargs["headers"]["Authorization"], "test-key")
        self.assertEqual(kwargs["timeout"], 15)

    def test_missing_summary_means_zero_distance(self, post):
        payload = copy.deepcopy(ORS_RESPONSE)
        payload["features"][0]["properties"]["summary"] = {}  # e.g. start == finish
        post.return_value = fake_response(payload=payload)

        route = fetch_route(CHICAGO, CHICAGO)

        self.assertEqual(route.distance_miles, 0.0)
        self.assertEqual(route.duration_hours, 0.0)

    def test_timeout_maps_to_routing_timeout(self, post):
        post.side_effect = requests.Timeout()

        with self.assertRaises(RoutingTimeout):
            fetch_route(CHICAGO, ST_LOUIS)

    def test_connection_failure_maps_to_routing_error(self, post):
        post.side_effect = requests.ConnectionError()

        with self.assertLogs("planner.services.routing", "ERROR"):
            with self.assertRaises(RoutingError):
                fetch_route(CHICAGO, ST_LOUIS)

    def test_unroutable_points_map_to_no_route_with_reason(self, post):
        post.return_value = fake_response(
            404, {"error": {"code": 2010, "message": "Could not find routable point"}}
        )

        with self.assertRaisesMessage(NoRouteFound, "Could not find routable point"):
            fetch_route(CHICAGO, ST_LOUIS)

    def test_rejected_key_or_used_up_quota_is_unavailable_and_hidden_from_users(self, post):
        # Retrying won't help, so it's "unavailable" (503), not "please try again".
        post.return_value = fake_response(403, {"error": "Access to this API has been disallowed"})

        with self.assertLogs("planner.services.routing", "ERROR") as logs:
            with self.assertRaises(RoutingUnavailable) as raised:
                fetch_route(CHICAGO, ST_LOUIS)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertNotIn("disallowed", str(raised.exception))
        self.assertIn("403", "\n".join(logs.output))

    def test_error_body_that_is_not_an_object_is_still_handled(self, post):
        post.return_value = fake_response(500, ["unexpected", "shape"])

        with self.assertLogs("planner.services.routing", "ERROR"):
            with self.assertRaises(RoutingError):
                fetch_route(CHICAGO, ST_LOUIS)

    def test_rate_limit_maps_to_unavailable(self, post):
        post.return_value = fake_response(429, {"error": "Rate limit exceeded"})

        with self.assertLogs("planner.services.routing", "WARNING"):
            with self.assertRaises(RoutingUnavailable):
                fetch_route(CHICAGO, ST_LOUIS)

    def test_server_error_maps_to_routing_error(self, post):
        post.return_value = fake_response(500, {"error": "Internal error"})

        with self.assertLogs("planner.services.routing", "ERROR"):
            with self.assertRaises(RoutingError):
                fetch_route(CHICAGO, ST_LOUIS)

    def test_malformed_success_body_maps_to_routing_error(self, post):
        post.return_value = fake_response(200, {"unexpected": "shape"})

        with self.assertLogs("planner.services.routing", "ERROR"):
            with self.assertRaises(RoutingError):
                fetch_route(CHICAGO, ST_LOUIS)

    @override_settings(ORS_API_KEY="")
    def test_missing_api_key_raises_without_http_call(self, post):
        with self.assertLogs("planner.services.routing", "ERROR"):
            with self.assertRaises(RoutingUnavailable):
                fetch_route(CHICAGO, ST_LOUIS)

        post.assert_not_called()


@override_settings(ORS_API_KEY="test-key")
@mock.patch("planner.services.routing.requests.post")
class GetRouteCachingTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_same_trip_calls_the_api_only_once(self, post):
        post.return_value = fake_response()

        first = get_route(CHICAGO, ST_LOUIS)
        second = get_route(CHICAGO, ST_LOUIS)

        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)

    def test_different_trips_are_cached_separately(self, post):
        post.return_value = fake_response()

        get_route(CHICAGO, ST_LOUIS)
        get_route(ST_LOUIS, CHICAGO)

        self.assertEqual(post.call_count, 2)

    def test_failures_are_not_cached(self, post):
        post.side_effect = [requests.Timeout(), fake_response()]

        with self.assertRaises(RoutingTimeout):
            get_route(CHICAGO, ST_LOUIS)
        get_route(CHICAGO, ST_LOUIS)

        self.assertEqual(post.call_count, 2)
