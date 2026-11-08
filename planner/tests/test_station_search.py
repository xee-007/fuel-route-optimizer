from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from planner.models import FuelStation
from planner.services.fuel_planner import StationCandidate
from planner.services.station_search import (
    find_start_station,
    find_stations_along_route,
    thin_stations,
)

# A straight east-west route along latitude 40 from Kansas into Missouri (~265 miles).
ROUTE = [(-100.0, 40.0), (-99.0, 40.0), (-98.0, 40.0), (-97.0, 40.0), (-96.0, 40.0), (-95.0, 40.0)]


def add_station(opis_id: int, lat: float, lng: float, price: str) -> FuelStation:
    return FuelStation.objects.create(
        opis_id=opis_id,
        name=f"Station {opis_id}",
        address="I-70, EXIT 1",
        city="Town",
        state="KS",
        rack_id=1,
        price_per_gallon=Decimal(price),
        lat=lat,
        lng=lng,
    )


class FindStationsAlongRouteTests(TestCase):
    def test_finds_station_on_route_with_its_mile_marker(self):
        add_station(1, 40.0, -97.5, "3.10")

        [found] = find_stations_along_route(ROUTE, corridor_miles=10)

        self.assertEqual(found.station_id, 1)
        self.assertEqual(found.price_per_gallon, Decimal("3.10"))
        self.assertAlmostEqual(found.route_mile, 132.5, delta=2)

    def test_finds_station_slightly_off_route_within_corridor(self):
        add_station(1, 40.1, -97.5, "3.10")  # ~7 miles north of the route

        self.assertEqual(len(find_stations_along_route(ROUTE, corridor_miles=10)), 1)

    def test_excludes_station_outside_corridor(self):
        add_station(1, 40.5, -97.5, "3.10")  # ~35 miles north of the route

        self.assertEqual(find_stations_along_route(ROUTE, corridor_miles=10), [])

    def test_results_sorted_by_route_mile(self):
        add_station(1, 40.0, -96.0, "3.10")
        add_station(2, 40.0, -99.0, "3.20")
        add_station(3, 40.0, -97.0, "3.30")

        found = find_stations_along_route(ROUTE, corridor_miles=10)

        self.assertEqual([s.station_id for s in found], [2, 3, 1])

    def test_no_stations_returns_empty_list(self):
        self.assertEqual(find_stations_along_route(ROUTE, corridor_miles=10), [])


class FindStartStationTests(TestCase):
    def test_returns_cheapest_station_within_radius_at_mile_zero(self):
        add_station(1, 40.1, -100.0, "3.50")  # ~7 miles away
        add_station(2, 40.2, -100.0, "3.20")  # ~14 miles away, cheaper
        add_station(3, 40.6, -100.0, "2.00")  # ~41 miles away: too far

        found = find_start_station(40.0, -100.0, radius_miles=25)

        self.assertEqual(found.station_id, 2)
        self.assertEqual(found.route_mile, 0.0)

    def test_equal_prices_prefer_the_nearest(self):
        add_station(1, 40.2, -100.0, "3.20")
        add_station(2, 40.1, -100.0, "3.20")

        self.assertEqual(find_start_station(40.0, -100.0, radius_miles=25).station_id, 2)

    def test_none_when_nothing_is_near(self):
        add_station(1, 41.0, -100.0, "3.00")  # ~69 miles away

        self.assertIsNone(find_start_station(40.0, -100.0, radius_miles=25))


def candidate(mile: float, price: str) -> StationCandidate:
    return StationCandidate(
        station_id=int(mile * 10),
        name="",
        address="",
        city="",
        state="KS",
        lat=40.0,
        lng=-100.0,
        price_per_gallon=Decimal(price),
        route_mile=mile,
    )


class ThinStationsTests(SimpleTestCase):
    def test_keeps_cheapest_station_per_stretch(self):
        thinned = thin_stations(
            [candidate(1, "3.50"), candidate(5, "3.10"), candidate(30, "3.90")], spacing_miles=25
        )

        self.assertEqual([s.route_mile for s in thinned], [5, 30])

    def test_equal_prices_keep_the_earliest(self):
        thinned = thin_stations([candidate(8, "3.10"), candidate(3, "3.10")], spacing_miles=25)

        self.assertEqual([s.route_mile for s in thinned], [3])
