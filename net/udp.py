"""UDP socket adapter and endpoint configuration."""

import socket
from core.exceptions import NetworkError
from core.log import get_logger

logger = get_logger("net.udp")


class UdpSocketAdapter:
    """Thin wrapper around a blocking UDP socket.

    Parameters
    ----------
    local_ip:
        IP address to bind (use ``""`` or ``"0.0.0.0"`` for all interfaces).
    local_port:
        UDP port to bind.
    timeout:
        Socket receive timeout in seconds.  Defaults to 2 s.
    """

    def __init__(self, local_ip: str, local_port: int, timeout: float = 2.0) -> None:
        self.local_ip = local_ip
        self.local_port = local_port
        self._sock: socket.socket | None = None
        self._timeout = timeout

    def open(self) -> None:
        """Create and bind the UDP socket."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.settimeout(self._timeout)
            self._sock.bind((self.local_ip, self.local_port))
        except OSError as exc:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            raise NetworkError(
                f"Cannot bind UDP socket {self.local_ip or '0.0.0.0'}:{self.local_port}: {exc}"
            ) from exc
        logger.debug("Bound UDP socket %s:%d", self.local_ip or "0.0.0.0", self.local_port)

    def send(self, data: bytes, remote_ip: str, remote_port: int) -> None:
        """Send *data* as a UDP datagram to *remote_ip*:*remote_port*."""
        if self._sock is None:
            raise RuntimeError("Socket not open")
        self._sock.sendto(data, (remote_ip, remote_port))

    def recv(self, buf_size: int = 4096) -> tuple[bytes, tuple[str, int]]:
        """Receive one UDP datagram.

        Returns ``(data, (addr, port))``.  Raises ``socket.timeout`` if no
        packet arrives within the configured timeout.
        """
        if self._sock is None:
            raise RuntimeError("Socket not open")
        return self._sock.recvfrom(buf_size)

    def close(self) -> None:
        """Close the socket if it is open."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            logger.debug("Closed UDP socket %s:%d", self.local_ip or "0.0.0.0", self.local_port)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
