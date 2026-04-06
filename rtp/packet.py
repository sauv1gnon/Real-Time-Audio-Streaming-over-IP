"""RTP packet builder and parser (RFC 3550).

Only the fixed header fields required by the project are implemented.
Extension headers and CSRC lists are not used.

Packet structure (12-byte fixed header + payload):
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |V=2|P|X|  CC   |M|     PT      |       sequence number         |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                           timestamp                           |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |           synchronisation source (SSRC) identifier           |
 +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+
 |            contributing source (CSRC) identifiers            |
 |                             ....                              |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from core.exceptions import RtpError

# RTP version is always 2
_RTP_VERSION = 2
_HEADER_FMT = "!BBHII"   # version+flags byte, marker+pt byte, seq, ts, ssrc
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 12 bytes


@dataclass
class RtpPacket:
    """Represents one RTP packet."""

    payload_type: int
    sequence_number: int
    timestamp: int
    ssrc: int
    payload: bytes
    marker: bool = False
    version: int = _RTP_VERSION
    padding: bool = False
    extension: bool = False

    def serialize(self) -> bytes:
        """Pack the fixed header fields and payload into bytes."""
        # Byte 0: V(2) P(1) X(1) CC(4)
        b0 = (_RTP_VERSION << 6) | (int(self.padding) << 5) | (int(self.extension) << 4)
        # Byte 1: M(1) PT(7)
        b1 = (int(self.marker) << 7) | (self.payload_type & 0x7F)
        seq = self.sequence_number & 0xFFFF
        ts = self.timestamp & 0xFFFFFFFF
        ssrc = self.ssrc & 0xFFFFFFFF
        header = struct.pack(_HEADER_FMT, b0, b1, seq, ts, ssrc)
        return header + self.payload

    @classmethod
    def parse(cls, data: bytes) -> "RtpPacket":
        """Parse raw bytes into an :class:`RtpPacket`.

        Raises :class:`~core.exceptions.RtpError` on invalid data.
        """
        if len(data) < _HEADER_SIZE:
            raise RtpError(f"Packet too short: {len(data)} bytes")
        b0, b1, seq, ts, ssrc = struct.unpack_from(_HEADER_FMT, data)
        version = (b0 >> 6) & 0x3
        if version != _RTP_VERSION:
            raise RtpError(f"Unexpected RTP version {version}")
        padding = bool(b0 & 0x20)
        extension = bool(b0 & 0x10)
        marker = bool(b1 & 0x80)
        pt = b1 & 0x7F
        payload = data[_HEADER_SIZE:]
        return cls(
            payload_type=pt,
            sequence_number=seq,
            timestamp=ts,
            ssrc=ssrc,
            payload=payload,
            marker=marker,
            version=version,
            padding=padding,
            extension=extension,
        )
