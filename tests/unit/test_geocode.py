"""Tests for biardtz.geocode."""

from unittest.mock import MagicMock, patch

import pytest

from biardtz.geocode import resolve_location


class TestResolveLocation:
    @patch("biardtz.geocode._tzfinder")
    @patch("biardtz.geocode._geolocator")
    def test_resolves_known_city(self, mock_geolocator, mock_tzfinder):
        mock_location = MagicMock()
        mock_location.latitude = 43.4832
        mock_location.longitude = -1.5586
        mock_location.address = "Biarritz, Pyrénées-Atlantiques, France"
        mock_geolocator.geocode.return_value = mock_location
        mock_tzfinder.timezone_at.return_value = "Europe/Paris"

        lat, lon, display, tz_name = resolve_location("Biarritz")
        assert abs(lat - 43.4832) < 1e-4
        assert abs(lon - (-1.5586)) < 1e-4
        assert "Biarritz" in display
        assert tz_name == "Europe/Paris"
        mock_geolocator.geocode.assert_called_once_with("Biarritz")

    @patch("biardtz.geocode._geolocator")
    def test_raises_on_unknown_location(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with pytest.raises(ValueError, match="Could not find location"):
            resolve_location("xyznonexistent99")

    @patch("biardtz.geocode._tzfinder")
    @patch("biardtz.geocode._geolocator")
    def test_timezone_finder_returns_none_falls_back_to_utc(self, mock_geolocator, mock_tzfinder):
        """When TimezoneFinder returns None (e.g. ocean coords), fall back to UTC."""
        mock_location = MagicMock()
        mock_location.latitude = 0.0
        mock_location.longitude = 0.0
        mock_location.address = "Null Island"
        mock_geolocator.geocode.return_value = mock_location
        mock_tzfinder.timezone_at.return_value = None

        lat, lon, display, tz_name = resolve_location("Null Island")
        assert tz_name == "UTC"
        assert lat == 0.0
        assert lon == 0.0

    @patch("biardtz.geocode._geolocator")
    def test_network_error_propagates(self, mock_geolocator):
        """Network errors from geocoder should propagate to the caller."""
        from geopy.exc import GeocoderServiceError

        mock_geolocator.geocode.side_effect = GeocoderServiceError("Connection refused")

        with pytest.raises(GeocoderServiceError):
            resolve_location("Biarritz")
