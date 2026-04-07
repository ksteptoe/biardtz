"""Tests for biardtz.geocode."""

from unittest.mock import MagicMock, patch

import pytest

from biardtz.geocode import resolve_location


class TestResolveLocation:
    @patch("biardtz.geocode._geolocator")
    def test_resolves_known_city(self, mock_geolocator):
        mock_location = MagicMock()
        mock_location.latitude = 43.4832
        mock_location.longitude = -1.5586
        mock_location.address = "Biarritz, Pyrénées-Atlantiques, France"
        mock_geolocator.geocode.return_value = mock_location

        lat, lon, display = resolve_location("Biarritz")
        assert abs(lat - 43.4832) < 1e-4
        assert abs(lon - (-1.5586)) < 1e-4
        assert "Biarritz" in display
        mock_geolocator.geocode.assert_called_once_with("Biarritz")

    @patch("biardtz.geocode._geolocator")
    def test_raises_on_unknown_location(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with pytest.raises(ValueError, match="Could not find location"):
            resolve_location("xyznonexistent99")
