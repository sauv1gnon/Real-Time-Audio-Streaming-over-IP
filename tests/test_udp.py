"""Tests for UDP adapter failure handling."""

from __future__ import annotations

import pytest

from core.exceptions import NetworkError
from net.udp import UdpSocketAdapter


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def setsockopt(self, *_args) -> None:
        return None

    def settimeout(self, *_args) -> None:
        return None

    def bind(self, *_args) -> None:
        raise OSError("port already in use")

    def close(self) -> None:
        self.closed = True


class _HappySocket:
    def __init__(self) -> None:
        self.closed = False
        self.bound: tuple[str, int] | None = None
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.recv_payload: bytes = b"payload"
        self.recv_addr: tuple[str, int] = ("127.0.0.1", 5004)

    def setsockopt(self, *_args) -> None:
        return None

    def settimeout(self, *_args) -> None:
        return None

    def bind(self, addr: tuple[str, int]) -> None:
        self.bound = addr

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def recvfrom(self, _buf_size: int):
        return self.recv_payload, self.recv_addr

    def close(self) -> None:
        self.closed = True


def test_open_closes_socket_on_bind_failure(monkeypatch):
    fake = _FakeSocket()

    def _factory(*_args, **_kwargs):
        return fake

    monkeypatch.setattr("socket.socket", _factory)

    adapter = UdpSocketAdapter("127.0.0.1", 9999)
    with pytest.raises(NetworkError, match="Cannot bind UDP socket"):
        adapter.open()

    assert fake.closed is True
    assert adapter._sock is None


def test_open_send_recv_and_close_success(monkeypatch):
    fake = _HappySocket()

    def _factory(*_args, **_kwargs):
        return fake

    monkeypatch.setattr("socket.socket", _factory)

    adapter = UdpSocketAdapter("127.0.0.1", 9998)
    adapter.open()
    adapter.send(b"abc", "127.0.0.1", 6000)
    data, addr = adapter.recv(2048)
    adapter.close()

    assert fake.bound == ("127.0.0.1", 9998)
    assert fake.sent == [(b"abc", ("127.0.0.1", 6000))]
    assert data == b"payload"
    assert addr == ("127.0.0.1", 5004)
    assert fake.closed is True
    assert adapter._sock is None


def test_send_and_recv_raise_when_socket_not_open():
    adapter = UdpSocketAdapter("127.0.0.1", 9997)

    with pytest.raises(RuntimeError, match="Socket not open"):
        adapter.send(b"x", "127.0.0.1", 5000)

    with pytest.raises(RuntimeError, match="Socket not open"):
        adapter.recv(1024)


def test_context_manager_opens_and_closes(monkeypatch):
    fake = _HappySocket()

    def _factory(*_args, **_kwargs):
        return fake

    monkeypatch.setattr("socket.socket", _factory)

    with UdpSocketAdapter("127.0.0.1", 9996) as adapter:
        adapter.send(b"ok", "127.0.0.1", 6001)

    assert fake.closed is True
