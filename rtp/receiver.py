"""RTP receiver: receives RTP packets from UDP and delivers payloads to a queue."""

from __future__ import annotations

import queue
import socket
import threading

from core.exceptions import RtpError
from core.log import get_logger
from net.udp import UdpSocketAdapter
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
    ) -> None:
        self._sock = sock
        self.payload_type = payload_type
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_maxsize)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._packets_received: int = 0
        self._bytes_received: int = 0

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
            except OSError:
                break

            try:
                pkt = RtpPacket.parse(data)
            except RtpError as exc:
                logger.warning("Bad RTP packet: %s", exc)
                continue

            if pkt.payload_type != self.payload_type:
                logger.debug("Discarding packet with unexpected PT=%d", pkt.payload_type)
                continue

            self._packets_received += 1
            self._bytes_received += len(pkt.payload)

            logger.debug(
                "RTP recv  seq=%d  ts=%d  bytes=%d",
                pkt.sequence_number,
                pkt.timestamp,
                len(pkt.payload),
            )

            try:
                self._queue.put_nowait(pkt.payload)
            except queue.Full:
                logger.warning("RTP receiver queue full — dropping frame seq=%d", pkt.sequence_number)
