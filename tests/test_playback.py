"""Tests for playback fallback behavior with optional dependencies."""

from __future__ import annotations

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
