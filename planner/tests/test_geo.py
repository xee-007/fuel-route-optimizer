from django.test import SimpleTestCase

from planner.services.geo import (
    cumulative_miles,
    haversine_miles,
    resample_route,
    simplify_route,
)

# Routes are lists of (lng, lat) pairs, the GeoJSON order used by the routing API.
CHICAGO = (-87.6298, 41.8781)
ST_LOUIS = (-90.1994, 38.6270)


class HaversineTests(SimpleTestCase):
    def test_chicago_to_st_louis(self):
        miles = haversine_miles(CHICAGO[1], CHICAGO[0], ST_LOUIS[1], ST_LOUIS[0])
        self.assertAlmostEqual(miles, 262.3, delta=0.5)  # 422 km in a straight line

    def test_same_point_is_zero(self):
        self.assertEqual(haversine_miles(40.0, -100.0, 40.0, -100.0), 0)


class CumulativeMilesTests(SimpleTestCase):
    def test_starts_at_zero_and_adds_up_each_leg(self):
        miles = cumulative_miles([(-100.0, 40.0), (-99.0, 40.0), (-98.0, 40.0)])

        self.assertEqual(miles[0], 0)
        self.assertAlmostEqual(miles[1], 53.0, delta=0.5)  # 1 degree of longitude at 40°N
        self.assertAlmostEqual(miles[2], 2 * miles[1], places=6)


class ResampleRouteTests(SimpleTestCase):
    def test_spacing_and_endpoints(self):
        route = [(-100.0, 40.0), (-99.5, 40.3), (-98.2, 40.1)]

        lats, lngs, miles = resample_route(route, step_miles=1.0)

        self.assertEqual(miles[0], 0)
        self.assertAlmostEqual(miles[-1], cumulative_miles(route)[-1])
        self.assertLessEqual(max(b - a for a, b in zip(miles, miles[1:], strict=False)), 1.0001)
        self.assertEqual((lngs[0], lats[0]), route[0])
        self.assertAlmostEqual(lngs[-1], route[-1][0])
        self.assertAlmostEqual(lats[-1], route[-1][1])

    def test_single_point_route(self):
        lats, lngs, miles = resample_route([(-100.0, 40.0)], step_miles=1.0)

        self.assertEqual(list(miles), [0.0])


class SimplifyRouteTests(SimpleTestCase):
    def test_caps_points_and_keeps_endpoints(self):
        route = [(-100 + i * 0.0002, 40 + i * 0.0001) for i in range(25_000)]

        simplified = simplify_route(route, max_points=1000)

        self.assertLessEqual(len(simplified), 1000)
        self.assertEqual(simplified[0], [-100.0, 40.0])
        self.assertEqual(simplified[-1], [round(route[-1][0], 5), round(route[-1][1], 5)])

    def test_short_route_is_kept_whole(self):
        route = [(-100.0, 40.0), (-99.0, 40.5)]

        self.assertEqual(simplify_route(route), [[-100.0, 40.0], [-99.0, 40.5]])
