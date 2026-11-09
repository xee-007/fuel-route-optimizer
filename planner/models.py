from django.db import models


class Town(models.Model):
    """A US town with the coordinates of its center (US Census towns, placed at
    their USGS town center; see the build_towns_file command).

    Used to place fuel stations on the map and to turn "City, ST" input into
    coordinates without calling an external geocoding API.
    """

    name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128)
    state = models.CharField(max_length=2)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["normalized_name", "state"], name="unique_town_per_state"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.state}"


class FuelStation(models.Model):
    """A truck stop from the fuel price list, placed at the center of its town."""

    opis_id = models.PositiveIntegerField(unique=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()
    price_per_gallon = models.DecimalField(max_digits=10, decimal_places=8)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["lat", "lng"], name="station_location_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"
