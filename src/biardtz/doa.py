"""Direction of Arrival estimation using GCC-PHAT for the ReSpeaker 4-Mic Array."""

from __future__ import annotations

import logging

import numpy as np
from scipy.fft import irfft, rfft

_logger = logging.getLogger(__name__)

# ReSpeaker 4-Mic Array geometry: 4 mics on a circle, radius ~16mm
# Mic positions in the array's local coordinate frame (metres):
#   Mic 0 (ch1): +y  (0 degrees, "forward")
#   Mic 1 (ch2): +x  (90 degrees, "right")
#   Mic 2 (ch3): -y  (180 degrees, "back")
#   Mic 3 (ch4): -x  (270 degrees, "left")
_RADIUS_M = 0.016  # 16mm radius (32mm diameter circle)
_MIC_ANGLES_DEG = np.array([0.0, 90.0, 180.0, 270.0])
_MIC_POSITIONS = np.column_stack([
    _RADIUS_M * np.sin(np.radians(_MIC_ANGLES_DEG)),  # x
    _RADIUS_M * np.cos(np.radians(_MIC_ANGLES_DEG)),  # y
])  # shape (4, 2)

_SPEED_OF_SOUND = 343.0  # m/s at ~20C

# All 6 unique mic pairs from 4 mics
_MIC_PAIRS = [(i, j) for i in range(4) for j in range(i + 1, 4)]

# 8 compass octants
_OCTANTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _gcc_phat(sig1: np.ndarray, sig2: np.ndarray) -> np.ndarray:
    """GCC-PHAT cross-correlation between two signals."""
    n = len(sig1) + len(sig2) - 1
    nfft = 1 << (n - 1).bit_length()

    s1 = rfft(sig1, n=nfft)
    s2 = rfft(sig2, n=nfft)

    r = s1 * np.conj(s2)
    magnitude = np.abs(r)
    magnitude = np.where(magnitude > 1e-10, magnitude, 1e-10)
    r_phat = r / magnitude

    return np.real(irfft(r_phat, n=nfft))


def _estimate_tdoa(sig1: np.ndarray, sig2: np.ndarray, sample_rate: int) -> float:
    """Estimate time delay of arrival between two signals using GCC-PHAT.

    Uses parabolic interpolation for sub-sample accuracy.
    Positive means sig2 arrives after sig1.
    """
    cc = _gcc_phat(sig1, sig2)
    nfft = len(cc)

    # Maximum possible delay given mic spacing
    max_delay_samples = int(_RADIUS_M * 2 / _SPEED_OF_SOUND * sample_rate) + 2

    # Search only within physically possible delay range
    indices = np.concatenate([
        np.arange(0, max_delay_samples + 1),
        np.arange(nfft - max_delay_samples, nfft),
    ])
    peak_idx = int(indices[np.argmax(cc[indices])])

    # Parabolic interpolation for sub-sample accuracy
    if 0 < peak_idx < nfft - 1:
        alpha = float(cc[peak_idx - 1])
        beta = float(cc[peak_idx])
        gamma = float(cc[peak_idx + 1])
        denom = alpha - 2 * beta + gamma
        if abs(denom) > 1e-10:
            delta = 0.5 * (alpha - gamma) / denom
        else:
            delta = 0.0
    else:
        delta = 0.0

    if peak_idx > nfft // 2:
        delay_samples = (peak_idx - nfft) + delta
    else:
        delay_samples = peak_idx + delta

    return delay_samples / sample_rate


def estimate_doa(
    multichannel: np.ndarray,
    sample_rate: int,
    array_bearing: float = 0.0,
) -> tuple[float, str]:
    """Estimate direction of arrival from 4-channel mic array data.

    Args:
        multichannel: Array of shape (samples, 4) with raw mic data.
        sample_rate: Sample rate in Hz.
        array_bearing: Compass bearing (degrees) that mic 0 faces.

    Returns:
        (bearing, direction) where bearing is 0-360 degrees and
        direction is an octant label like "N", "NE", etc.
    """
    assert multichannel.shape[1] == 4, f"Expected 4 channels, got {multichannel.shape[1]}"

    # Pre-compute measured TDOAs for all mic pairs
    measured_tdoas = {}
    for i, j in _MIC_PAIRS:
        measured_tdoas[(i, j)] = _estimate_tdoa(
            multichannel[:, i], multichannel[:, j], sample_rate,
        )

    # Steering-vector scan: score each candidate angle
    candidate_angles = np.arange(0, 360, 1)
    scores = np.zeros(len(candidate_angles))

    for idx, angle_deg in enumerate(candidate_angles):
        angle_rad = np.radians(angle_deg)
        d = np.array([np.sin(angle_rad), np.cos(angle_rad)])

        score = 0.0
        for i, j in _MIC_PAIRS:
            mic_diff = _MIC_POSITIONS[j] - _MIC_POSITIONS[i]
            expected_tdoa = np.dot(mic_diff, d) / _SPEED_OF_SOUND
            score += 1.0 - abs(measured_tdoas[(i, j)] - expected_tdoa) * sample_rate
        scores[idx] = score

    local_angle = float(candidate_angles[np.argmax(scores)])
    bearing = (local_angle + array_bearing) % 360
    direction = bearing_to_octant(bearing)

    _logger.debug("DOA: local=%.0f, bearing=%.0f (%s)", local_angle, bearing, direction)
    return bearing, direction


def bearing_to_octant(bearing: float) -> str:
    """Convert a compass bearing (0-360) to the nearest octant label."""
    return _OCTANTS[int((bearing + 22.5) / 45) % 8]
