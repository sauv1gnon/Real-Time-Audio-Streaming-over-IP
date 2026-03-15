"""RTP sender: packetises audio frames and sends them over UDP at a real-time pace."""

from __future__ import annotations

import random
import threading
from typing import Iterator

from core.log import get_logger
from core.timers import monotonic_ms, sleep_until
from net.udp import UdpSocketAdapter
from rtp.packet import RtpPacket

logger = get_logger("rtp.sender")

# Samples per frame for 8 kHz / 20 ms
_SAMPLES_PER_FRAME = 160
_FRAME_DURATION_MS = 20.0


class RtpSender:
    """Sends a sequence of audio frames as RTP packets.

    Parameters
    ----------
    sock:
        Bound :class:`~net.udp.UdpSocketAdapter` for RTP.
    remote_ip:
        Destination IP.
    remote_port:
        Destination RTP port.
    payload_type:
        RTP payload type to use.
    ssrc:
        Synchronisation source identifier.  A random 32-bit value is
        generated when not specified.
    samples_per_frame:
        Number of audio samples per frame (determines timestamp increment).
    frame_duration_ms:
        Target frame interval in milliseconds (used for pacing).
    """

    def __init__(
        self,
        sock: UdpSocketAdapter,
        remote_ip: str,
        remote_port: int,
        payload_type: int = 96,
        ssrc: int | None = None,
        samples_per_frame: int = _SAMPLES_PER_FRAME,
        frame_duration_ms: float = _FRAME_DURATION_MS,
    ) -> None:
        self._sock = sock
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.ssrc = ssrc if ssrc is not None else random.getrandbits(32)
        self.samples_per_frame = samples_per_frame
        self.frame_duration_ms = frame_duration_ms

        self._seq: int = random.randint(0, 65535)
        self._timestamp: int = random.randint(0, 0xFFFFFFFF)
        self._packets_sent: int = 0
        self._bytes_sent: int = 0
        self._send_errors: int = 0
        self._stats_lock = threading.Lock()

    # ---------------------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------------------

    @property
    def packets_sent(self) -> int:
        with self._stats_lock:
            return self._packets_sent

    @property
    def bytes_sent(self) -> int:
        with self._stats_lock:
            return self._bytes_sent

    @property
    def current_timestamp(self) -> int:
        with self._stats_lock:
            return self._timestamp

    @property
    def send_errors(self) -> int:
        with self._stats_lock:
            return self._send_errors

    def get_stats_snapshot(self) -> tuple[int, int, int]:
        """Return a consistent (packets, octets, current_timestamp) snapshot."""
        with self._stats_lock:
            return self._packets_sent, self._bytes_sent, self._timestamp

    def send_frames(self, frames: Iterator[bytes], stop_event=None) -> None:
        """Send each frame in *frames* as one RTP packet, paced in real time.

        Parameters
        ----------
        frames:
            Iterator of raw PCM byte chunks (one per frame).
        stop_event:
            Optional :class:`threading.Event` checked between frames.  When
            set, sending stops early.
        """
        next_send_ms = monotonic_ms()
        for frame in frames:
            if stop_event is not None and stop_event.is_set():
                logger.info("Stop event set — halting RTP send")
                break

            pkt = RtpPacket(
                payload_type=self.payload_type,
                sequence_number=self._seq & 0xFFFF,
                timestamp=self._timestamp & 0xFFFFFFFF,
                ssrc=self.ssrc,
                payload=frame,
            )
            data = pkt.serialize()

            sleep_until(next_send_ms)
            try:
                self._sock.send(data, self.remote_ip, self.remote_port)
            except OSError as exc:
                with self._stats_lock:
                    self._send_errors += 1
                logger.error("RTP send failed to %s:%d: %s", self.remote_ip, self.remote_port, exc)
                break

            self._seq = (self._seq + 1) & 0xFFFF
            with self._stats_lock:
                self._timestamp = (self._timestamp + self.samples_per_frame) & 0xFFFFFFFF
                self._packets_sent += 1
                self._bytes_sent += len(frame)
            next_send_ms += self.frame_duration_ms

            logger.debug(
                "RTP sent  seq=%d  ts=%d  bytes=%d  total_pkts=%d",
                pkt.sequence_number,
                pkt.timestamp,
                len(frame),
                self.packets_sent,
            )

        logger.info(
            "RTP sender done: %d packets / %d bytes sent (send_errors=%d)",
            self.packets_sent,
            self.bytes_sent,
            self.send_errors,
        )
