"""Smoke test: record audio from the ReSpeaker and verify we get data."""
from __future__ import annotations

import numpy as np
import pytest
import sounddevice as sd

pytestmark = pytest.mark.live

RECORD_SECONDS = 3
SAMPLE_RATE = 16_000


class TestAudioSmoke:
    def test_records_audio_from_mic(self, live_config):
        """Record 3 s from the capture device and check shape + non-silence."""
        audio = sd.rec(
            frames=int(RECORD_SECONDS * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=live_config.device_index,
        )
        sd.wait()

        assert isinstance(audio, np.ndarray)
        assert audio.shape[0] == RECORD_SECONDS * SAMPLE_RATE
        # Should not be dead silence (all zeros)
        rms = np.sqrt(np.mean(audio ** 2))
        assert rms > 1e-6, f"Audio appears silent (RMS={rms:.2e})"

    def test_input_stream_callback(self, live_config):
        """Verify InputStream callback fires and delivers data."""
        import queue
        import time

        q: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):
            q.put(indata.copy())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=live_config.channels,
            dtype="float32",
            device=live_config.device_index,
            blocksize=4096,
            callback=callback,
        )
        stream.start()
        time.sleep(1)
        stream.stop()
        stream.close()

        assert not q.empty(), "Callback never fired"
        chunk = q.get()
        assert chunk.ndim == 2
        assert chunk.shape[1] == live_config.channels
