"""Tests for biardtz.doa — Direction of Arrival estimation."""

import numpy as np
import pytest

from biardtz.doa import (
    _RADIUS_M,
    _SPEED_OF_SOUND,
    _estimate_tdoa,
    _gcc_phat,
    bearing_to_octant,
    estimate_doa,
)


class TestGccPhat:
    def test_zero_delay_peaks_at_zero(self):
        sig = np.random.randn(1000).astype(np.float32)
        cc = _gcc_phat(sig, sig)
        assert np.argmax(cc) == 0

    def test_known_delay(self):
        sig = np.random.randn(1000).astype(np.float32)
        delay = 5
        delayed = np.concatenate([np.zeros(delay), sig[:-delay]])
        cc = _gcc_phat(sig, delayed)
        nfft = len(cc)
        peak = np.argmax(cc)
        assert peak == delay or peak == nfft - delay


class TestEstimateTdoa:
    def test_zero_delay(self):
        sig = np.random.randn(16000).astype(np.float32)
        tdoa = _estimate_tdoa(sig, sig, 16000)
        assert abs(tdoa) < 1 / 16000  # within one sample

    def test_known_positive_delay(self):
        # Use 48kHz for clearer integer-sample delay
        sig = np.random.randn(48000).astype(np.float32)
        delayed = np.concatenate([np.zeros(1), sig[:-1]])
        tdoa = _estimate_tdoa(sig, delayed, 48000)
        # delayed arrives 1 sample later than sig
        assert abs(abs(tdoa) - 1 / 48000) < 1 / 48000


class TestEstimateDoa:
    # Use 48kHz for synthetic tests — at 16kHz the max inter-mic delay is ~1.5 samples
    # which makes integer-sample synthetic data too coarse for reliable DOA.
    _SR = 48000

    @classmethod
    def _make_synthetic(cls, angle_deg: float, duration: float = 0.5):
        """Create synthetic 4-channel audio from a source at a known angle."""
        sample_rate = cls._SR
        n_samples = int(sample_rate * duration)
        source = np.random.randn(n_samples + 200).astype(np.float32)

        mic_angles = np.array([0.0, 90.0, 180.0, 270.0])
        mic_positions = np.column_stack([
            _RADIUS_M * np.sin(np.radians(mic_angles)),
            _RADIUS_M * np.cos(np.radians(mic_angles)),
        ])

        angle_rad = np.radians(angle_deg)
        direction = np.array([np.sin(angle_rad), np.cos(angle_rad)])

        multichannel = np.zeros((n_samples, 4), dtype=np.float32)
        for i in range(4):
            delay_sec = np.dot(mic_positions[i], direction) / _SPEED_OF_SOUND
            delay_samples = delay_sec * sample_rate
            d = int(round(delay_samples))
            offset = 100 + d
            multichannel[:, i] = source[offset:offset + n_samples]

        return multichannel

    @pytest.mark.parametrize("angle,expected_octant", [
        (0, "N"),
        (90, "E"),
        (180, "S"),
        (270, "W"),
    ])
    def test_cardinal_directions(self, angle, expected_octant):
        multi = self._make_synthetic(angle)
        bearing, direction = estimate_doa(multi, self._SR, array_bearing=0.0)
        assert direction == expected_octant, f"Expected {expected_octant}, got {direction} (bearing={bearing:.0f})"

    def test_array_bearing_offset(self):
        """If array faces East (90 deg), a source from local 0 should read as East."""
        multi = self._make_synthetic(0)
        bearing, direction = estimate_doa(multi, self._SR, array_bearing=90.0)
        assert abs(bearing - 90) < 45


class TestBearingToOctant:
    @pytest.mark.parametrize("bearing,expected", [
        (0, "N"), (22.4, "N"), (22.5, "NE"), (45, "NE"),
        (90, "E"), (135, "SE"), (180, "S"), (225, "SW"),
        (270, "W"), (315, "NW"), (359, "N"),
    ])
    def test_octant_mapping(self, bearing, expected):
        assert bearing_to_octant(bearing) == expected
