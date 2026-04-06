"""Microphone audio source for RTP streaming.

Captures mono 16-bit PCM frames from the default input device using
sounddevice + numpy.
"""

from __future__ import annotations

import time
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
        if self.channels != 1:
            raise MediaError(f"Only mono microphone capture is supported (got channels={self.channels})")
        logger.info(
            "Microphone capture ready: %d Hz, %.1f ms/frame, %.1f s total",
            self.sample_rate,
            self.frame_duration_ms,
            self.duration_s,
        )

    def frames(self) -> Iterator[bytes]:
        if self._sd is None:
            raise MediaError("Microphone dependency (sounddevice) is unavailable")
        logger.info("Recording from microphone...")
        started_at = time.monotonic()
        deadline = started_at + self.duration_s
        emitted = 0

        stream = self._sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self._samples_per_frame,
        )

        with stream:
            while emitted < self._frame_count:
                if time.monotonic() >= deadline:
                    break

                chunk, overflowed = stream.read(self._samples_per_frame)
                if time.monotonic() > deadline:
                    break
                if overflowed:
                    logger.warning("Microphone input overflow detected")

                data = bytes(chunk)
                if len(data) < self._bytes_per_frame:
                    data += b"\x00" * (self._bytes_per_frame - len(data))
                elif len(data) > self._bytes_per_frame:
                    data = data[: self._bytes_per_frame]

                emitted += 1
                yield data

        elapsed = time.monotonic() - started_at
        logger.info(
            "Microphone capture finished: %d frames in %.2f s (target %.2f s)",
            emitted,
            elapsed,
            self.duration_s,
        )
