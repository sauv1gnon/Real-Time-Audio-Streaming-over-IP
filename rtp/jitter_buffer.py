"""Simple reorder buffer that compensates for mild out-of-order UDP delivery.

The jitter buffer holds up to *max_depth* frames indexed by RTP sequence
number and delivers them in order to the playback sink.  It introduces a
fixed playout delay of *max_depth* frames to tolerate reordering within
that window.

For a student demo this is optional but adds robustness when running over
a real LAN.
"""

from __future__ import annotations

from collections import OrderedDict

from core.log import get_logger

logger = get_logger("rtp.jitter")


class JitterBuffer:
    """Ordered sequence-number buffer for RTP payloads.

    Parameters
    ----------
    max_depth:
        Number of frames to buffer before forcing delivery.  Larger values
        tolerate more reordering but add latency.
    """

    def __init__(self, max_depth: int = 5) -> None:
        self._max_depth = max_depth
        self._buffer: OrderedDict[int, bytes] = OrderedDict()
        self._next_seq: int | None = None

    def push(self, seq: int, payload: bytes) -> list[bytes]:
        """Insert a new frame and return payloads that are now deliverable."""
        return [frame for _, frame in self.push_with_sequence(seq, payload)]

    def push_with_sequence(self, seq: int, payload: bytes) -> list[tuple[int, bytes]]:
        """Insert a new frame and return any frames that are now deliverable.

        Parameters
        ----------
        seq:
            16-bit RTP sequence number.
        payload:
            Raw frame bytes.

        Returns
        -------
        list[tuple[int, bytes]]
            Ordered list of (sequence_number, frame) ready for playback.
        """
        if self._next_seq is None:
            self._next_seq = seq

        if seq in self._buffer:
            return []  # duplicate

        self._buffer[seq] = payload
        self._sort_by_modular_distance()

        # Force flush if buffer depth exceeded
        if len(self._buffer) >= self._max_depth:
            return self._flush_all_with_sequence()

        return self._drain_with_sequence()

    def flush(self) -> list[bytes]:
        """Flush all remaining frames (call at end of stream)."""
        return [frame for _, frame in self.flush_with_sequence()]

    def flush_with_sequence(self) -> list[tuple[int, bytes]]:
        """Flush all remaining frames with sequence numbers."""
        return self._flush_all_with_sequence()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drain(self) -> list[bytes]:
        return [frame for _, frame in self._drain_with_sequence()]

    def _drain_with_sequence(self) -> list[tuple[int, bytes]]:
        """Pop consecutive in-order frames starting from *_next_seq*."""
        out: list[tuple[int, bytes]] = []
        while self._next_seq in self._buffer:
            seq = self._next_seq
            out.append((seq, self._buffer.pop(seq)))
            self._next_seq = (self._next_seq + 1) & 0xFFFF
        return out

    def _flush_all(self) -> list[bytes]:
        return [frame for _, frame in self._flush_all_with_sequence()]

    def _flush_all_with_sequence(self) -> list[tuple[int, bytes]]:
        """Pop everything in sequence-number order."""
        self._sort_by_modular_distance()
        out = list(self._buffer.items())
        if out:
            last_seq = out[-1][0]
            self._next_seq = (last_seq + 1) & 0xFFFF
        self._buffer.clear()
        return out

    def _sort_by_modular_distance(self) -> None:
        if self._next_seq is None or not self._buffer:
            return
        self._buffer = OrderedDict(
            sorted(
                self._buffer.items(),
                key=lambda item: ((item[0] - self._next_seq) & 0xFFFF),
            )
        )
