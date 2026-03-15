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
        """Insert a new frame and return any frames that are now deliverable.

        Parameters
        ----------
        seq:
            16-bit RTP sequence number.
        payload:
            Raw frame bytes.

        Returns
        -------
        list[bytes]
            Ordered list of frames ready for playback (may be empty).
        """
        if self._next_seq is None:
            self._next_seq = seq

        if seq in self._buffer:
            return []  # duplicate

        self._buffer[seq] = payload
        # Sort by sequence number (handle 16-bit wrap-around naively)
        self._buffer = OrderedDict(sorted(self._buffer.items(), key=lambda x: x[0]))

        # Force flush if buffer depth exceeded
        if len(self._buffer) >= self._max_depth:
            return self._flush_all()

        return self._drain()

    def flush(self) -> list[bytes]:
        """Flush all remaining frames (call at end of stream)."""
        return self._flush_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drain(self) -> list[bytes]:
        """Pop consecutive in-order frames starting from *_next_seq*."""
        out: list[bytes] = []
        while self._next_seq in self._buffer:
            out.append(self._buffer.pop(self._next_seq))
            self._next_seq = (self._next_seq + 1) & 0xFFFF
        return out

    def _flush_all(self) -> list[bytes]:
        """Pop everything in sequence-number order."""
        out = list(self._buffer.values())
        if out and self._buffer:
            last_seq = next(reversed(self._buffer))
            self._next_seq = (last_seq + 1) & 0xFFFF
        self._buffer.clear()
        return out
