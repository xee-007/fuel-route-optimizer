from django.test import TestCase

from planner.models import Town
from planner.services.locations import Location, LocationError, resolve_location


class ResolveTownTests(TestCase):
    def setUp(self):
        Town.objects.create(
            name="Chicago", normalized_name="chicago", state="IL", lat=41.84, lng=-87.68
        )
        Town.objects.create(
            name="Saint Louis", normalized_name="saint louis", state="MO", lat=38.64, lng=-90.24
        )

    def test_city_and_state_code_resolves(self):
        self.assertEqual(resolve_location("Chicago, IL"), Location("Chicago, IL", 41.84, -87.68))

    def test_city_and_full_state_name_resolves(self):
        self.assertEqual(resolve_location("chicago, illinois").label, "Chicago, IL")

    def test_saint_abbreviation_and_full_state_name_resolve(self):
        self.assertEqual(resolve_location("st. louis, mo").label, "Saint Louis, MO")
        self.assertEqual(resolve_location("SAINT  LOUIS, Missouri").label, "Saint Louis, MO")

    def test_empty_query_rejected(self):
        with self.assertRaises(LocationError):
            resolve_location("   ")

    def test_missing_state_rejected_with_format_hint(self):
        with self.assertRaisesMessage(LocationError, "City, ST"):
            resolve_location("Chicago")

    def test_unknown_state_rejected(self):
        with self.assertRaisesMessage(LocationError, "ZZ"):
            resolve_location("Chicago, ZZ")

    def test_unknown_town_rejected_with_its_name(self):
        with self.assertRaisesMessage(LocationError, "Atlantis, IL"):
            resolve_location("Atlantis, IL")


class ResolveCoordinatesTests(TestCase):
    def test_coordinates_resolve(self):
        self.assertEqual(
            resolve_location(" 41.8781 , -87.6298 "),
            Location("41.8781,-87.6298", 41.8781, -87.6298),
        )

    def test_coordinates_in_alaska_and_hawaii_resolve(self):
        self.assertEqual(resolve_location("61.2181,-149.9003").lat, 61.2181)  # Anchorage
        self.assertEqual(resolve_location("21.3069,-157.8583").lat, 21.3069)  # Honolulu

    def test_coordinates_outside_usa_rejected(self):
        with self.assertRaisesMessage(LocationError, "outside the USA"):
            resolve_location("51.5074,-0.1278")  # London

    def test_swapped_coordinates_are_rejected_with_hint(self):
        with self.assertRaisesMessage(
            LocationError, 'looks swapped. Put latitude first, as "lat,lng": "41.8781,-87.6298"'
        ):
            resolve_location("-87.6298,41.8781")

    def test_swapped_western_coordinates_get_the_hint_too(self):
        # A western longitude (below -90) typed first is also out of latitude range.
        with self.assertRaisesMessage(LocationError, '"37.7749,-122.4194"'):
            resolve_location("-122.4194,37.7749")  # San Francisco, swapped

    def test_impossible_coordinates_rejected(self):
        with self.assertRaises(LocationError):
            resolve_location("123.0,-87.6")
