"""Minimal RTCP Sender Report (SR) implementation (RFC 3550).

Only the fields needed by the project rubric are included:
  - SSRC
  - Packet count
  - Octet count
  - NTP-format timestamp (seconds + fractions)

SR fixed header layout (28 bytes):
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |V=2|P|    RC   |   PT=200(SR)  |             length            |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                         SSRC of sender                        |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |              NTP timestamp, most significant word             |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |             NTP timestamp, least significant word             |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                         RTP timestamp                         |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                     sender's packet count                     |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                      sender's octet count                     |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass

from core.log import get_logger
from net.udp import UdpSocketAdapter

logger = get_logger("rtp.rtcp")

# RTCP packet type 200 = Sender Report
_RTCP_SR_PT = 200
# NTP epoch offset (seconds between 1900-01-01 and 1970-01-01)
_NTP_EPOCH_OFFSET = 2208988800

_SR_FMT = "!BBHIIIIII"  # v+p+rc, PT, length, SSRC, NTP_hi, NTP_lo, RTP_ts, pkt_cnt, oct_cnt
_SR_SIZE = struct.calcsize(_SR_FMT)  # 28 bytes


@dataclass
class RtcpPacket:
    """A minimal RTCP Sender Report packet."""

    ssrc: int
    ntp_timestamp_hi: int
    ntp_timestamp_lo: int
    rtp_timestamp: int
    packet_count: int
    octet_count: int

    def serialize(self) -> bytes:
        # V=2, P=0, RC=0  → 0x80
        b0 = 0x80
        # PT = 200, length = 6 (words minus one, i.e. (28/4) - 1 = 6)
        length_words = (_SR_SIZE // 4) - 1
        return struct.pack(
            _SR_FMT,
            b0,
            _RTCP_SR_PT,
            length_words,
            self.ssrc,
            self.ntp_timestamp_hi,
            self.ntp_timestamp_lo,
            self.rtp_timestamp,
            self.packet_count,
            self.octet_count,
        )

    @classmethod
    def parse(cls, data: bytes) -> "RtcpPacket":
        if len(data) < _SR_SIZE:
            raise ValueError(f"RTCP SR too short: {len(data)} bytes")
        b0, pt, _length, ssrc, ntp_hi, ntp_lo, rtp_ts, pkt_cnt, oct_cnt = struct.unpack_from(
            _SR_FMT, data
        )
        version = (b0 >> 6) & 0x03
        if version != 2:
            raise ValueError(f"Invalid RTCP version {version}; expected 2")
        if pt != _RTCP_SR_PT:
            raise ValueError(f"Unsupported RTCP packet type {pt}; expected {_RTCP_SR_PT}")
        expected_length_words = (_SR_SIZE // 4) - 1
        if _length != expected_length_words:
            raise ValueError(
                f"Invalid RTCP SR length field {_length}; expected {expected_length_words}"
            )
        return cls(
            ssrc=ssrc,
            ntp_timestamp_hi=ntp_hi,
            ntp_timestamp_lo=ntp_lo,
            rtp_timestamp=rtp_ts,
            packet_count=pkt_cnt,
            octet_count=oct_cnt,
        )


def _ntp_now() -> tuple[int, int]:
    """Return (NTP_seconds, NTP_fraction) for the current wall-clock time."""
    now = time.time()
    ntp_sec = int(now) + _NTP_EPOCH_OFFSET
    ntp_frac = int((now % 1.0) * (2 ** 32))
    return ntp_sec, ntp_frac


class RtcpReporter:
    """Sends periodic RTCP Sender Reports on a background thread.

    Parameters
    ----------
    sock:
        Bound :class:`~net.udp.UdpSocketAdapter` for RTCP (usually RTP port + 1).
    remote_ip:
        Destination IP.
    remote_port:
        Destination RTCP port.
    ssrc:
        SSRC of the RTP sender this SR reports for.
    interval_s:
        Interval between Sender Reports in seconds.
    get_stats:
        Callable that returns ``(packet_count, octet_count, rtp_timestamp)``
        at call time.  This avoids direct coupling to the sender object.
    """

    def __init__(
        self,
        sock: UdpSocketAdapter,
        remote_ip: str,
        remote_port: int,
        ssrc: int,
        interval_s: float = 5.0,
        get_stats=None,
    ) -> None:
        self._sock = sock
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.ssrc = ssrc
        self.interval_s = interval_s
        self._get_stats = get_stats or (lambda: (0, 0, 0))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._reports_sent: int = 0

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._report_loop, daemon=True, name="rtcp-sr")
        self._thread.start()
        logger.info("RTCP reporter started (interval=%.1f s)", self.interval_s)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 1.0)
        logger.info("RTCP reporter stopped — %d SR(s) sent", self._reports_sent)

    def _report_loop(self) -> None:
        while not self._stop_event.wait(timeout=self.interval_s):
            pkt_cnt, oct_cnt, rtp_ts = self._get_stats()
            ntp_hi, ntp_lo = _ntp_now()
            sr = RtcpPacket(
                ssrc=self.ssrc,
                ntp_timestamp_hi=ntp_hi,
                ntp_timestamp_lo=ntp_lo,
                rtp_timestamp=rtp_ts,
                packet_count=pkt_cnt,
                octet_count=oct_cnt,
            )
            try:
                self._sock.send(sr.serialize(), self.remote_ip, self.remote_port)
                self._reports_sent += 1
                logger.info(
                    "RTCP SR sent  pkts=%d  octets=%d  ntp_hi=%d",
                    pkt_cnt,
                    oct_cnt,
                    ntp_hi,
                )
            except OSError as exc:
                logger.warning("RTCP send failed: %s", exc)
