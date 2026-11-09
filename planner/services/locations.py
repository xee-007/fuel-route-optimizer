"""
Turn a user's start/finish text into coordinates.

Accepted formats:
- "City, ST" or "City, State Name"  e.g. "Chicago, IL", "chicago, illinois"
- "lat,lng"                          e.g. "41.8781,-87.6298"

Towns are looked up in our own Town table, so no geocoding API call is needed.
"""

import re
from dataclasses import dataclass

from planner.models import Town
from planner.services.place_names import normalize_place_name, state_code

FORMAT_HINT = 'Use "City, ST" (e.g. "Chicago, IL") or "lat,lng" (e.g. "41.8781,-87.6298").'

_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# Rough (min_lat, max_lat, min_lng, max_lng) boxes around the US.
_USA_BOUNDING_BOXES = (
    (24.4, 49.5, -125.0, -66.9),  # Lower 48 states
    (51.0, 71.5, -180.0, -129.9),  # Alaska
    (18.9, 22.3, -160.3, -154.8),  # Hawaii
)


@dataclass(frozen=True)
class Location:
    label: str
    lat: float
    lng: float


class LocationError(ValueError):
    """The text could not be turned into a US location. The message is safe to show users."""


def resolve_location(query: str) -> Location:
    text = query.strip()
    if not text:
        raise LocationError(f"Location is required. {FORMAT_HINT}")

    match = _COORDINATES.match(text)
    if match:
        return _resolve_coordinates(match.group(1), match.group(2))
    return _resolve_town(text)


def _resolve_coordinates(lat_text: str, lng_text: str) -> Location:
    lat, lng = float(lat_text), float(lng_text)
    typed = f"{lat_text},{lng_text}"

    # Check for swapped values first: a western longitude such as -122 typed as
    # the latitude would otherwise just look "not valid".
    if not _is_in_usa(lat, lng) and _is_in_usa(lng, lat):
        raise LocationError(
            f'"{typed}" looks swapped. Put latitude first, as "lat,lng": "{lng_text},{lat_text}".'
        )
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise LocationError(f'"{typed}" are not valid coordinates. {FORMAT_HINT}')
    if not _is_in_usa(lat, lng):
        raise LocationError(f'"{typed}" is outside the USA.')

    return Location(label=f"{lat:.4f},{lng:.4f}", lat=lat, lng=lng)


def _resolve_town(text: str) -> Location:
    city, separator, state_text = text.rpartition(",")
    if not separator or not city.strip():
        raise LocationError(f'Could not understand "{text}". {FORMAT_HINT}')

    code = state_code(state_text)
    if code is None:
        raise LocationError(
            f'"{state_text.strip()}" is not a US state. '
            'Use a two-letter code like "IL" or a full name like "Illinois".'
        )

    town = Town.objects.filter(normalized_name=normalize_place_name(city), state=code).first()
    if town is None:
        raise LocationError(
            f'Could not find "{city.strip()}, {code}". '
            'Check the spelling, or pass coordinates as "lat,lng".'
        )

    return Location(label=f"{town.name}, {town.state}", lat=town.lat, lng=town.lng)


def _is_in_usa(lat: float, lng: float) -> bool:
    return any(
        min_lat <= lat <= max_lat and min_lng <= lng <= max_lng
        for min_lat, max_lat, min_lng, max_lng in _USA_BOUNDING_BOXES
    )
