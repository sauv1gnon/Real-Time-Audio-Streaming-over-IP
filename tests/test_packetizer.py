"""Tests for audio frame packetizer behavior."""

from __future__ import annotations

import pytest

from media.packetizer import AudioFramePacketizer


class _FakeSource:
    def __init__(self, frames: list[bytes], samples_per_frame: int = 160) -> None:
        self._frames = list(frames)
        self.samples_per_frame = samples_per_frame

    def frames(self):
        for frame in self._frames:
            yield frame


class _ErrorSource:
    samples_per_frame = 160

    def frames(self):
        yield b"first"
        raise RuntimeError("source failure")


def test_frame_iterator_yields_source_frames_in_order():
    source = _FakeSource([b"a", b"b", b"c"])
    packetizer = AudioFramePacketizer(source)

    assert list(packetizer.frame_iterator()) == [b"a", b"b", b"c"]


def test_samples_per_frame_passthrough():
    source = _FakeSource([b"x"], samples_per_frame=320)
    packetizer = AudioFramePacketizer(source)

    assert packetizer.samples_per_frame == 320


def test_frame_iterator_propagates_source_errors():
    packetizer = AudioFramePacketizer(_ErrorSource())
    iterator = packetizer.frame_iterator()

    assert next(iterator) == b"first"
    with pytest.raises(RuntimeError, match="source failure"):
        next(iterator)
