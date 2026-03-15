"""WAV file reader that validates PCM format and exposes raw frame bytes."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Iterator

from core.exceptions import MediaError
from core.log import get_logger

logger = get_logger("media.wav_reader")

# Required audio format for this project
REQUIRED_SAMPLE_RATE = 8000
REQUIRED_SAMPLE_WIDTH = 2   # 16-bit PCM
REQUIRED_CHANNELS = 1       # mono


class WavAudioSource:
    """Reads PCM frames from a WAV file.

    Parameters
    ----------
    path:
        Path to a WAV file (must be mono, 8 kHz, 16-bit PCM).
    frame_duration_ms:
        Duration of each frame in milliseconds.
    strict:
        When *True* (default), raise :class:`~core.exceptions.MediaError` if
        the file format does not match requirements.  When *False*, log a
        warning and continue.
    """

    def __init__(self, path: str | Path, frame_duration_ms: float = 20.0, strict: bool = True) -> None:
        self.path = Path(path)
        self.frame_duration_ms = frame_duration_ms
        self._strict = strict
        self._sample_rate: int = 0
        self._sample_width: int = 0
        self._channels: int = 0
        self._samples_per_frame: int = 0
        self._bytes_per_frame: int = 0
        self._total_frames: int = 0

    def open(self) -> None:
        """Open the WAV file and validate its format."""
        if not self.path.exists():
            raise MediaError(f"WAV file not found: {self.path}")
        try:
            with wave.open(str(self.path), "rb") as wf:
                self._sample_rate = wf.getframerate()
                self._sample_width = wf.getsampwidth()
                self._channels = wf.getnchannels()
                self._total_frames = wf.getnframes()
        except wave.Error as exc:
            raise MediaError(f"Cannot open WAV file {self.path}: {exc}") from exc

        self._validate()
        self._samples_per_frame = int(self._sample_rate * self.frame_duration_ms / 1000)
        self._bytes_per_frame = self._samples_per_frame * self._sample_width * self._channels
        logger.info(
            "WAV opened: %s  rate=%d Hz  width=%d B  ch=%d  total_frames=%d  "
            "frame_size=%d bytes/frame",
            self.path.name,
            self._sample_rate,
            self._sample_width,
            self._channels,
            self._total_frames,
            self._bytes_per_frame,
        )

    def _validate(self) -> None:
        issues = []
        if self._sample_rate != REQUIRED_SAMPLE_RATE:
            issues.append(f"sample rate {self._sample_rate} Hz (expected {REQUIRED_SAMPLE_RATE})")
        if self._sample_width != REQUIRED_SAMPLE_WIDTH:
            issues.append(f"sample width {self._sample_width} bytes (expected {REQUIRED_SAMPLE_WIDTH})")
        if self._channels != REQUIRED_CHANNELS:
            issues.append(f"{self._channels} channel(s) (expected {REQUIRED_CHANNELS})")
        if issues:
            msg = f"WAV format mismatch for {self.path}: " + "; ".join(issues)
            if self._strict:
                raise MediaError(msg)
            logger.warning(msg)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def samples_per_frame(self) -> int:
        return self._samples_per_frame

    @property
    def bytes_per_frame(self) -> int:
        return self._bytes_per_frame

    def frames(self) -> Iterator[bytes]:
        """Yield raw PCM byte chunks, one per frame."""
        with wave.open(str(self.path), "rb") as wf:
            while True:
                data = wf.readframes(self._samples_per_frame)
                if not data:
                    break
                # Pad last frame if needed
                if len(data) < self._bytes_per_frame:
                    data = data + b"\x00" * (self._bytes_per_frame - len(data))
                yield data
