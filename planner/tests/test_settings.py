from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import require_env


class VehicleSettingsTests(SimpleTestCase):
    def test_vehicle_constants_match_brief(self):
        self.assertEqual(settings.VEHICLE_RANGE_MILES, 500)
        self.assertEqual(settings.VEHICLE_MPG, 10)


class RequireEnvTests(SimpleTestCase):
    def test_returns_value_when_set(self):
        with mock.patch.dict("os.environ", {"SOME_SETTING": "value"}):
            self.assertEqual(require_env("SOME_SETTING"), "value")

    def test_missing_variable_raises_with_its_name(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesMessage(ImproperlyConfigured, "SOME_SETTING"):
                require_env("SOME_SETTING")

    def test_empty_variable_counts_as_missing(self):
        with mock.patch.dict("os.environ", {"SOME_SETTING": ""}):
            with self.assertRaises(ImproperlyConfigured):
                require_env("SOME_SETTING")
