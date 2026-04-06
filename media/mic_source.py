"""Microphone audio source for RTP streaming.

Captures mono 16-bit PCM frames from the default input device using
sounddevice + numpy.
"""

from __future__ import annotations

from typing import Iterator

from core.exceptions import MediaError
from core.log import get_logger

logger = get_logger("media.mic_source")


def _try_import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore

        return sd
    except Exception:
        return None


def _try_import_numpy():
    try:
        import numpy as np  # type: ignore

        return np
    except Exception:
        return None


class MicrophoneAudioSource:
    """Capture fixed-size PCM frames from microphone input."""

    def __init__(
        self,
        sample_rate: int = 8000,
        channels: int = 1,
        frame_duration_ms: float = 20.0,
        duration_s: float = 5.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.duration_s = duration_s
        self._sd = _try_import_sounddevice()
        self._np = _try_import_numpy()

        self._samples_per_frame = int(self.sample_rate * self.frame_duration_ms / 1000.0)
        self._bytes_per_frame = self._samples_per_frame * self.channels * 2  # int16
        self._frame_count = max(1, int(self.duration_s * 1000.0 / self.frame_duration_ms))

    @property
    def samples_per_frame(self) -> int:
        return self._samples_per_frame

    @property
    def bytes_per_frame(self) -> int:
        return self._bytes_per_frame

    def open(self) -> None:
        if self._sd is None:
            raise MediaError(
                "Microphone mode requires sounddevice. Install with: pip install sounddevice"
            )
        if self._np is None:
            raise MediaError("Microphone mode requires numpy. Install with: pip install numpy")
        if self.channels != 1:
            raise MediaError(f"Only mono microphone capture is supported (got channels={self.channels})")
        logger.info(
            "Microphone capture ready: %d Hz, %d ms/frame, %.1f s total",
            self.sample_rate,
            self.frame_duration_ms,
            self.duration_s,
        )

    def frames(self) -> Iterator[bytes]:
        if self._sd is None or self._np is None:
            raise MediaError("Microphone dependencies are unavailable")
        logger.info("Recording from microphone...")
        for _ in range(self._frame_count):
            # Blocking capture for one frame interval.
            chunk = self._sd.rec(
                self._samples_per_frame,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocking=True,
            )
            yield chunk.tobytes()
