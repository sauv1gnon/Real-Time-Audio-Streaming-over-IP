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
