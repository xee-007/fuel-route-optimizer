from decimal import Decimal

from django.test import TestCase

from planner.models import FuelStation
from planner.services.station_search import find_stations_along_route

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
