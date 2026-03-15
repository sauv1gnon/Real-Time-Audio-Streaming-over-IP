"""RTP receiver: receives RTP packets from UDP and delivers payloads to a queue."""

from __future__ import annotations

import queue
import socket
import threading

from core.exceptions import RtpError
from core.log import get_logger
from net.udp import UdpSocketAdapter
from rtp.jitter_buffer import JitterBuffer
from rtp.packet import RtpPacket

logger = get_logger("rtp.receiver")


class RtpReceiver:
    """Receives RTP packets on a UDP socket and places payloads in a queue.

    Runs in a background thread started by :meth:`start`.

    Parameters
    ----------
    sock:
        Bound :class:`~net.udp.UdpSocketAdapter` for RTP.
    payload_type:
        Expected payload type; packets with other PTs are discarded.
    queue_maxsize:
        Maximum number of frames that can accumulate before the receiver
        starts dropping them (backpressure protection).
    """

    def __init__(
        self,
        sock: UdpSocketAdapter,
        payload_type: int = 96,
        queue_maxsize: int = 100,
        expected_ssrc: int | None = None,
        jitter_buffer: JitterBuffer | None = None,
    ) -> None:
        self._sock = sock
        self.payload_type = payload_type
        self.expected_ssrc = expected_ssrc
        self._jitter_buffer = jitter_buffer
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_maxsize)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._packets_received: int = 0
        self._bytes_received: int = 0
        self._frames_dropped: int = 0
        self._receive_errors: int = 0
        self._ssrc_drops: int = 0
        self._last_error: str | None = None

    # ---------------------------------------------------------------------------
    # Control
    # ---------------------------------------------------------------------------

    def start(self) -> None:
        """Start the background receiver thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True, name="rtp-recv")
        self._thread.start()
        logger.info("RTP receiver started (PT=%d)", self.payload_type)

    def stop(self) -> None:
        """Signal the receiver to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        logger.info(
            "RTP receiver stopped: %d packets / %d bytes received",
            self._packets_received,
            self._bytes_received,
        )

    # ---------------------------------------------------------------------------
    # Data access
    # ---------------------------------------------------------------------------

    @property
    def packets_received(self) -> int:
        return self._packets_received

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    @property
    def receive_errors(self) -> int:
        return self._receive_errors

    @property
    def ssrc_drops(self) -> int:
        return self._ssrc_drops

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def get_frame(self, timeout: float = 1.0) -> bytes | None:
        """Pop the next frame payload from the queue.

        Returns ``None`` on timeout.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, _ = self._sock.recv(8192)
            except socket.timeout:
                continue
            except OSError as exc:
                if self._stop_event.is_set():
                    break
                self._receive_errors += 1
                self._last_error = str(exc)
                logger.error("RTP receiver socket error: %s", exc)
                break

            try:
                pkt = RtpPacket.parse(data)
            except RtpError as exc:
                logger.warning("Bad RTP packet: %s", exc)
                continue

            if pkt.payload_type != self.payload_type:
                logger.debug("Discarding packet with unexpected PT=%d", pkt.payload_type)
                continue

            if self.expected_ssrc is None:
                self.expected_ssrc = pkt.ssrc
            elif pkt.ssrc != self.expected_ssrc:
                self._ssrc_drops += 1
                logger.warning(
                    "Dropping packet from unexpected SSRC=0x%08X (expected 0x%08X)",
                    pkt.ssrc,
                    self.expected_ssrc,
                )
                continue

            self._packets_received += 1
            self._bytes_received += len(pkt.payload)

            logger.debug(
                "RTP recv  seq=%d  ts=%d  bytes=%d",
                pkt.sequence_number,
                pkt.timestamp,
                len(pkt.payload),
            )

            payloads = [pkt.payload]
            if self._jitter_buffer is not None:
                payloads = self._jitter_buffer.push(pkt.sequence_number, pkt.payload)

            for payload in payloads:
                try:
                    self._queue.put_nowait(payload)
                except queue.Full:
                    self._frames_dropped += 1
                    logger.warning(
                        "RTP receiver queue full — dropping frame seq=%d",
                        pkt.sequence_number,
                    )

        if self._jitter_buffer is not None:
            for payload in self._jitter_buffer.flush():
                try:
                    self._queue.put_nowait(payload)
                except queue.Full:
                    self._frames_dropped += 1
                    logger.warning("RTP receiver queue full — dropping flushed frame")
