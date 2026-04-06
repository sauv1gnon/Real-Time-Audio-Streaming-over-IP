"""Tests for microphone source timing and frame shaping."""

from __future__ import annotations

import pytest

from core.exceptions import MediaError
import media.mic_source as mic_source


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _FakeRawInputStream:
    def __init__(
        self,
        *,
        clock: _FakeClock,
        channels: int,
        bytes_per_sample: int,
        step_s: float,
        payload_scale: float = 1.0,
    ) -> None:
        self._clock = clock
        self._channels = channels
        self._bytes_per_sample = bytes_per_sample
        self._step_s = step_s
        self._payload_scale = payload_scale

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, frames: int) -> tuple[bytes, bool]:
        self._clock.now += self._step_s
        payload_bytes = int(frames * self._channels * self._bytes_per_sample * self._payload_scale)
        return (b"\x01" * payload_bytes, False)


class _FakeSoundDevice:
    def __init__(self, *, clock: _FakeClock, step_s: float, payload_scale: float = 1.0) -> None:
        self._clock = clock
        self._step_s = step_s
        self._payload_scale = payload_scale

    def RawInputStream(self, *, samplerate: int, channels: int, dtype: str, blocksize: int):
        assert samplerate == 8000
        assert channels == 1
        assert dtype == "int16"
        assert blocksize == 160
        return _FakeRawInputStream(
            clock=self._clock,
            channels=channels,
            bytes_per_sample=2,
            step_s=self._step_s,
            payload_scale=self._payload_scale,
        )


def test_open_requires_sounddevice(monkeypatch):
    monkeypatch.setattr(mic_source, "_try_import_sounddevice", lambda: None)

    source = mic_source.MicrophoneAudioSource()
    with pytest.raises(MediaError, match="sounddevice"):
        source.open()


def test_frames_respect_wall_clock_duration(monkeypatch):
    clock = _FakeClock()
    fake_sd = _FakeSoundDevice(clock=clock, step_s=1.0)

    monkeypatch.setattr(mic_source, "_try_import_sounddevice", lambda: fake_sd)
    monkeypatch.setattr(mic_source.time, "monotonic", clock.monotonic)

    source = mic_source.MicrophoneAudioSource(
        sample_rate=8000,
        channels=1,
        frame_duration_ms=20.0,
        duration_s=2.5,
    )
    source.open()

    frames = list(source.frames())

    # Reads happen at t=1.0, 2.0, 3.0. The third frame crosses the deadline and is not emitted.
    assert len(frames) == 2
    assert all(len(frame) == source.bytes_per_frame for frame in frames)


def test_frames_are_padded_to_expected_size(monkeypatch):
    clock = _FakeClock()
    # Return half-sized payload from sounddevice; source must pad to bytes_per_frame.
    fake_sd = _FakeSoundDevice(clock=clock, step_s=0.1, payload_scale=0.5)

    monkeypatch.setattr(mic_source, "_try_import_sounddevice", lambda: fake_sd)
    monkeypatch.setattr(mic_source.time, "monotonic", clock.monotonic)

    source = mic_source.MicrophoneAudioSource(
        sample_rate=8000,
        channels=1,
        frame_duration_ms=20.0,
        duration_s=0.25,
    )
    source.open()

    first = next(source.frames())
    assert len(first) == source.bytes_per_frame
