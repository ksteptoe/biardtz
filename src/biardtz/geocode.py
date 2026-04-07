"""Resolve location names to coordinates and timezone using Nominatim."""

from __future__ import annotations

import logging

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

_logger = logging.getLogger(__name__)

_geolocator = Nominatim(user_agent="biardtz-bird-detector")
_tzfinder = TimezoneFinder()


def resolve_location(query: str) -> tuple[float, float, str, str]:
    """Look up a place name and return (latitude, longitude, display_name, tz_name).

    Raises ValueError if the location cannot be found.
    """
    location = _geolocator.geocode(query)
    if location is None:
        raise ValueError(f"Could not find location: {query!r}")

    tz_name = _tzfinder.timezone_at(lat=location.latitude, lng=location.longitude)
    if tz_name is None:
        tz_name = "UTC"

    _logger.info(
        "Resolved %r -> %s (%.4f, %.4f, %s)",
        query, location.address, location.latitude, location.longitude, tz_name,
    )
    return location.latitude, location.longitude, location.address, tz_name
