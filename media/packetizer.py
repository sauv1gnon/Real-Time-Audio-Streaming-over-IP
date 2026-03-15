"""Audio frame packetizer — bridges WavAudioSource and RtpSender."""

from __future__ import annotations

from typing import Iterator

from media.wav_reader import WavAudioSource


class AudioFramePacketizer:
    """Wraps a :class:`~media.wav_reader.WavAudioSource` and exposes its
    frames as an iterator suitable for :meth:`~rtp.sender.RtpSender.send_frames`.

    The packetizer is deliberately thin; format-specific logic lives in
    WavAudioSource and any future codec adapter.
    """

    def __init__(self, source: WavAudioSource) -> None:
        self._source = source

    def frame_iterator(self) -> Iterator[bytes]:
        """Return an iterator over raw PCM frame bytes."""
        return self._source.frames()

    @property
    def samples_per_frame(self) -> int:
        return self._source.samples_per_frame
