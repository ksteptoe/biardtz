"""Resolve location names to coordinates using Nominatim (OpenStreetMap)."""

from __future__ import annotations

import logging

from geopy.geocoders import Nominatim

_logger = logging.getLogger(__name__)

_geolocator = Nominatim(user_agent="biardtz-bird-detector")


def resolve_location(query: str) -> tuple[float, float, str]:
    """Look up a place name and return (latitude, longitude, display_name).

    Raises ValueError if the location cannot be found.
    """
    location = _geolocator.geocode(query)
    if location is None:
        raise ValueError(f"Could not find location: {query!r}")
    _logger.info("Resolved %r -> %s (%.4f, %.4f)", query, location.address,
                 location.latitude, location.longitude)
    return location.latitude, location.longitude, location.address
