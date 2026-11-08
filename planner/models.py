from django.db import models


class Town(models.Model):
    """A US town with the coordinates of its center (from the US Census Gazetteer).

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
