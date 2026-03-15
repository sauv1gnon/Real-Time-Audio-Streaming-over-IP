"""Tests for SIP caller session state transitions and dialog validation."""

from __future__ import annotations

import socket

from sip.messages import SipRequest, SipResponse
from sip.parser import parse
from sip.sdp import SdpDescription
from sip.session import CallerSession, CallerState


class _FakeUdpSocket:
    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.sent: list[tuple[bytes, str, int]] = []

    def send(self, data: bytes, remote_ip: str, remote_port: int) -> None:
        self.sent.append((data, remote_ip, remote_port))

    def recv(self, buf_size: int = 4096) -> tuple[bytes, tuple[str, int]]:
        if not self._responses:
            raise socket.timeout()
        return self._responses.pop(0), ("127.0.0.1", 5061)


def _offer_sdp() -> SdpDescription:
    return SdpDescription(
        media_ip="127.0.0.1",
        rtp_port=10000,
        payload_type=96,
        codec_name="L16",
        clock_rate=8000,
    )


def _build_200_ok(to_header: str) -> bytes:
    resp = SipResponse(200, "OK")
    resp.set_header("Via", "SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest")
    resp.set_header("From", "<sip:client1@127.0.0.1:5060>;tag=fromtag")
    resp.set_header("To", to_header)
    resp.set_header("Call-ID", "call-id")
    resp.set_header("CSeq", "1 INVITE")
    resp.set_header("Content-Length", "0")
    return resp.serialize()


def _new_session(fake_sock: _FakeUdpSocket) -> CallerSession:
    return CallerSession(
        sock=fake_sock,
        local_ip="127.0.0.1",
        local_sip_port=5060,
        remote_ip="127.0.0.1",
        remote_sip_port=5061,
        local_sdp=_offer_sdp(),
    )


def test_receive_200_ok_missing_to_tag_fails():
    fake_sock = _FakeUdpSocket([_build_200_ok("<sip:client2@127.0.0.1:5061>")])
    session = _new_session(fake_sock)
    session.send_invite()

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED
    assert len(fake_sock.sent) == 1


def test_receive_200_ok_empty_to_tag_fails():
    fake_sock = _FakeUdpSocket([_build_200_ok("<sip:client2@127.0.0.1:5061>;tag=")])
    session = _new_session(fake_sock)
    session.send_invite()

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED
    assert len(fake_sock.sent) == 1


def test_receive_200_ok_valid_to_tag_sends_ack():
    to_tag = "dialog123"
    fake_sock = _FakeUdpSocket([_build_200_ok(f"<sip:client2@127.0.0.1:5061>;tag={to_tag}")])
    session = _new_session(fake_sock)
    session.send_invite()

    assert session.receive_200_ok() is True
    assert session.state == CallerState.ESTABLISHED
    assert session.to_tag == to_tag
    assert len(fake_sock.sent) == 2

    ack = parse(fake_sock.sent[-1][0])
    assert isinstance(ack, SipRequest)
    assert ack.method == "ACK"
    assert f";tag={to_tag}" in ack.get_header("To")
