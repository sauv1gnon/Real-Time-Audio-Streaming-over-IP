"""Audio playback sink.

Attempts live playback via *sounddevice*.  Falls back to writing a WAV
file when sounddevice is unavailable, which keeps the demo runnable in
headless CI environments.
"""

from __future__ import annotations

import queue
import threading
import wave
from pathlib import Path
from typing import Optional

from core.log import get_logger

logger = get_logger("media.playback")


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


class AudioPlaybackSink:
    """Receives PCM frames and plays them or writes them to a WAV file.

    Parameters
    ----------
    sample_rate:
        Audio sample rate in Hz.
    channels:
        Number of channels (1 for mono).
    sample_width:
        Bytes per sample (2 for 16-bit PCM).
    output_path:
        When supplied, received frames are written to this WAV file
        *in addition to* (or instead of) live playback.  Useful for
        offline verification.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        channels: int = 1,
        sample_width: int = 2,
        output_path: Optional[str | Path] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.output_path = Path(output_path) if output_path else None

        self._sd = _try_import_sounddevice()
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._wav_out: Optional[wave.Wave_write] = None

    def start(self) -> None:
        """Open output file (if any) and start the playback thread."""
        if self.output_path is not None:
            self._wav_out = wave.open(str(self.output_path), "wb")
            self._wav_out.setnchannels(self.channels)
            self._wav_out.setsampwidth(self.sample_width)
            self._wav_out.setframerate(self.sample_rate)
            logger.info("Writing received audio to %s", self.output_path)

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._playback_loop, daemon=True, name="playback")
        self._thread.start()

        if self._sd is not None:
            logger.info("Live playback via sounddevice at %d Hz", self.sample_rate)
        else:
            logger.info("sounddevice unavailable — audio saved to file only")

    def stop(self) -> None:
        """Stop playback and close the output WAV file."""
        self._stop_event.set()
        # Unblock queue.get() quickly so the thread can drain and exit cleanly.
        self._queue.put_nowait(None)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                logger.warning("Playback thread did not exit before timeout")
        if self._wav_out is not None:
            self._wav_out.close()
            self._wav_out = None
        logger.info("Playback sink stopped")

    def push(self, frame: bytes) -> None:
        """Enqueue a raw PCM frame for playback/writing."""
        self._queue.put_nowait(frame)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _playback_loop(self) -> None:
        np = _try_import_numpy() if self._sd is not None else None
        if self._sd is not None and np is None:
            logger.info("numpy unavailable - live playback disabled; audio saved to file only")

        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if frame is None:
                break

            # Write to WAV file
            if self._wav_out is not None:
                try:
                    self._wav_out.writeframes(frame)
                except OSError as exc:
                    logger.error("WAV write failed: %s", exc)
                    self._stop_event.set()
                    break

            # Live playback
            if self._sd is not None and np is not None:
                try:
                    audio = np.frombuffer(frame, dtype=np.int16)
                    self._sd.play(audio, samplerate=self.sample_rate, blocking=False)
                except Exception as exc:  # pragma: no cover
                    logger.debug("sounddevice playback error: %s", exc)
