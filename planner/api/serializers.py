"""Input validation and response shape for the route plan API."""

from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from planner.services.geo import simplify_route


class RoutePlanQuerySerializer(serializers.Serializer):
    """Query parameters: ?start=Chicago, IL&finish=Denver, CO"""

    start = serializers.CharField(max_length=200)
    finish = serializers.CharField(max_length=200)


class RoundedNumberField(serializers.DecimalField):
    """A decimal rounded to `decimal_places` and output as a plain number (30.25),
    so the JSON API and the map page's JavaScript both get numbers, not strings.
    Prices keep all 8 decimals of the price list, so gallons x price = cost."""

    def __init__(self, decimal_places: int, **kwargs):
        super().__init__(
            max_digits=12, decimal_places=decimal_places, coerce_to_string=False, **kwargs
        )

    def to_representation(self, value) -> float:
        return float(super().to_representation(value))


class LocationSerializer(serializers.Serializer):
    label = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    station_id = serializers.IntegerField(source="station.station_id")
    name = serializers.CharField(source="station.name")
    address = serializers.CharField(source="station.address")
    city = serializers.CharField(source="station.city")
    state = serializers.CharField(source="station.state")
    lat = serializers.FloatField(source="station.lat")
    lng = serializers.FloatField(source="station.lng")
    route_mile = serializers.SerializerMethodField()
    price_per_gallon = RoundedNumberField(source="station.price_per_gallon", decimal_places=8)
    gallons = RoundedNumberField(decimal_places=2)
    cost_usd = RoundedNumberField(source="cost", decimal_places=2)

    def get_route_mile(self, stop) -> float:
        return round(stop.station.route_mile, 1)


class StationRefSerializer(serializers.Serializer):
    station_id = serializers.IntegerField()
    name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    route_mile = serializers.SerializerMethodField()

    def get_route_mile(self, station) -> float:
        return round(station.route_mile, 1)


class StartingFuelSerializer(serializers.Serializer):
    """The fuel used to reach the first station along the route, charged at its price."""

    gallons = RoundedNumberField(decimal_places=2)
    price_per_gallon = RoundedNumberField(source="station.price_per_gallon", decimal_places=8)
    cost_usd = RoundedNumberField(source="cost", decimal_places=2)
    priced_at = StationRefSerializer(source="station")


class TripPlanSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    distance_miles = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()
    fuel_summary = serializers.SerializerMethodField()
    fuel_stops = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    map_url = serializers.SerializerMethodField()

    def get_distance_miles(self, plan) -> float:
        return round(plan.route.distance_miles, 1)

    def get_duration_hours(self, plan) -> float:
        return round(plan.route.duration_hours, 1)

    def get_fuel_summary(self, plan) -> dict:
        return {
            "miles_per_gallon": settings.VEHICLE_MPG,
            "tank_range_miles": settings.VEHICLE_RANGE_MILES,
            "total_gallons": float(plan.fuel_plan.total_gallons),
            "total_cost_usd": float(plan.fuel_plan.total_cost),
            "starting_fuel": (
                StartingFuelSerializer(plan.fuel_plan.starting_fuel).data
                if plan.fuel_plan.starting_fuel
                else None
            ),
        }

    def get_fuel_stops(self, plan) -> list[dict]:
        return [
            {"stop_number": number, **FuelStopSerializer(stop).data}
            for number, stop in enumerate(plan.fuel_plan.stops, start=1)
        ]

    def get_route(self, plan) -> dict:
        # GeoJSON, thinned to at most 1,000 points to keep the response small.
        return {"type": "LineString", "coordinates": simplify_route(plan.route.coordinates)}

    def get_map_url(self, plan) -> str:
        query = urlencode(self.context["query"])
        return self.context["request"].build_absolute_uri(f"{reverse('route-plan-map')}?{query}")
