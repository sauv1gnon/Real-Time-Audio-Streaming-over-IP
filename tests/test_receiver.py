"""Tests for RTP receiver error handling and SSRC filtering."""

from __future__ import annotations

import socket
import time

from rtp.jitter_buffer import JitterBuffer
from rtp.packet import RtpPacket
from rtp.receiver import RtpReceiver


class _FakeRecvSocket:
    def __init__(self, payloads: list[bytes]):
        self._payloads = list(payloads)

    def recv(self, _buf_size: int = 4096):
        if self._payloads:
            return self._payloads.pop(0), ("127.0.0.1", 5004)
        raise socket.timeout()


class _ErrorSocket:
    def recv(self, _buf_size: int = 4096):
        raise OSError("simulated receive failure")


def _rtp(ssrc: int, seq: int, payload: bytes = b"\x00\x01" * 160) -> bytes:
    return RtpPacket(
        payload_type=96,
        sequence_number=seq,
        timestamp=seq * 160,
        ssrc=ssrc,
        payload=payload,
    ).serialize()


def test_receiver_drops_unexpected_ssrc_packets():
    sock = _FakeRecvSocket([
        _rtp(0x11111111, 1),
        _rtp(0x22222222, 2),
    ])
    receiver = RtpReceiver(sock=sock, payload_type=96)

    receiver.start()
    time.sleep(0.05)
    receiver.stop()

    assert receiver.packets_received == 1
    assert receiver.ssrc_drops == 1
    assert receiver.get_frame(timeout=0.01) is not None


def test_receiver_records_socket_errors():
    receiver = RtpReceiver(sock=_ErrorSocket(), payload_type=96)

    receiver.start()
    time.sleep(0.05)
    receiver.stop()

    assert receiver.receive_errors == 1
    assert receiver.last_error is not None


def test_receiver_start_stop_is_idempotent():
    sock = _FakeRecvSocket([_rtp(0x11111111, 1)])
    receiver = RtpReceiver(sock=sock, payload_type=96)

    receiver.start()
    receiver.start()
    time.sleep(0.05)
    receiver.stop()
    receiver.stop()

    assert receiver.packets_received >= 1


def test_receiver_inserts_silence_for_missing_sequence_numbers():
    first = b"\x01\x02" * 160
    third = b"\x03\x04" * 160
    sock = _FakeRecvSocket([
        _rtp(0x11111111, 1, first),
        _rtp(0x11111111, 3, third),
    ])
    receiver = RtpReceiver(
        sock=sock,
        payload_type=96,
        jitter_buffer=JitterBuffer(max_depth=2),
    )

    receiver.start()
    time.sleep(0.05)
    receiver.stop()

    frame1 = receiver.get_frame(timeout=0.01)
    frame2 = receiver.get_frame(timeout=0.01)
    frame3 = receiver.get_frame(timeout=0.01)

    assert frame1 == first
    assert frame2 == b"\x00" * len(first)
    assert frame3 == third
    assert receiver.packets_lost == 1
    assert receiver.concealment_frames_inserted == 1
