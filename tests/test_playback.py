"""Tests for playback fallback behavior with optional dependencies."""

from __future__ import annotations

import time
from pathlib import Path

import media.playback as playback


class _DummySoundDevice:
    def play(self, *args, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("play should not be called when numpy is unavailable")


def test_wav_only_mode_does_not_require_numpy(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playback, "_try_import_sounddevice", lambda: None)

    def _raise_numpy_import() -> None:
        raise AssertionError("numpy import should be skipped when sounddevice is unavailable")

    monkeypatch.setattr(playback, "_try_import_numpy", _raise_numpy_import)

    output_path = tmp_path / "fallback.wav"
    sink = playback.AudioPlaybackSink(output_path=output_path)
    sink.start()
    sink.push(b"\x00\x01" * 160)
    sink.stop()

    assert output_path.exists()
    assert output_path.stat().st_size > 44


def test_wav_write_failure_stops_cleanly(monkeypatch, tmp_path: Path):
    class _BrokenWaveWriter:
        def setnchannels(self, *_args):
            return None

        def setsampwidth(self, *_args):
            return None

        def setframerate(self, *_args):
            return None

        def writeframes(self, _data):
            raise OSError("disk full")

        def close(self):
            return None

    monkeypatch.setattr(playback, "_try_import_sounddevice", lambda: None)
    monkeypatch.setattr(playback.wave, "open", lambda *_args, **_kwargs: _BrokenWaveWriter())

    output_path = tmp_path / "broken.wav"
    sink = playback.AudioPlaybackSink(output_path=output_path)
    sink.start()
    sink.push(b"\x00\x01" * 160)
    time.sleep(0.05)
    sink.stop()


def test_sounddevice_without_numpy_still_writes_wav(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playback, "_try_import_sounddevice", lambda: _DummySoundDevice())
    monkeypatch.setattr(playback, "_try_import_numpy", lambda: None)

    output_path = tmp_path / "sounddevice_no_numpy.wav"
    sink = playback.AudioPlaybackSink(output_path=output_path)
    sink.start()
    sink.push(b"\x00\x01" * 160)
    sink.stop()

    assert output_path.exists()
    assert output_path.stat().st_size > 44


def test_small_playback_queue_drops_frames_without_crashing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playback, "_try_import_sounddevice", lambda: None)

    output_path = tmp_path / "small_queue.wav"
    sink = playback.AudioPlaybackSink(output_path=output_path, queue_maxsize=1)
    sink.start()
    for _ in range(20):
        sink.push(b"\x00\x01" * 160)
    time.sleep(0.05)
    sink.stop()

    assert output_path.exists()
    assert output_path.stat().st_size > 44


def test_playback_stop_handles_wav_close_failure(monkeypatch, tmp_path: Path):
    class _CloseFailWaveWriter:
        def setnchannels(self, *_args):
            return None

        def setsampwidth(self, *_args):
            return None

        def setframerate(self, *_args):
            return None

        def writeframes(self, _data):
            return None

        def close(self):
            raise OSError("close failure")

    monkeypatch.setattr(playback, "_try_import_sounddevice", lambda: None)
    monkeypatch.setattr(playback.wave, "open", lambda *_args, **_kwargs: _CloseFailWaveWriter())

    output_path = tmp_path / "close_failure.wav"
    sink = playback.AudioPlaybackSink(output_path=output_path)
    sink.start()
    sink.push(b"\x00\x01" * 160)
    time.sleep(0.05)

    # Must not raise even if close() fails.
    sink.stop()
