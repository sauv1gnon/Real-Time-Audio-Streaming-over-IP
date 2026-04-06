"""Tests for SIP caller session state transitions and dialog validation."""

from __future__ import annotations

import socket
import pytest

from sip.messages import SipRequest, SipResponse, build_invite
from sip.parser import parse
from sip.sdp import SdpDescription
from sip.session import CallerSession, CallerState, CalleeSession, CalleeState
from core.exceptions import SessionError


class _FakeUdpSocket:
    def __init__(self, responses: list[bytes], addr: str = "127.0.0.1", port: int = 5061) -> None:
        self._responses = list(responses)
        self._addr = addr
        self._port = port
        self.sent: list[tuple[bytes, str, int]] = []

    def send(self, data: bytes, remote_ip: str, remote_port: int) -> None:
        self.sent.append((data, remote_ip, remote_port))

    def recv(self, buf_size: int = 4096) -> tuple[bytes, tuple[str, int]]:
        if not self._responses:
            raise socket.timeout()
        return self._responses.pop(0), (self._addr, self._port)


def _offer_sdp() -> SdpDescription:
    return SdpDescription(
        media_ip="127.0.0.1",
        rtp_port=10000,
        payload_type=96,
        codec_name="L16",
        clock_rate=8000,
    )


def _valid_sdp() -> str:
    return (
        "v=0\r\n"
        "o=- 12345 1 IN IP4 127.0.0.1\r\n"
        "s=Session\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "t=0 0\r\n"
        "m=audio 10002 RTP/AVP 96\r\n"
        "a=rtpmap:96 L16/8000\r\n"
    )


def _build_200_ok(
    to_header: str,
    call_id: str,
    cseq: str = "1 INVITE",
    content_type: str = "application/sdp",
    body: str | None = None,
) -> bytes:
    resp = SipResponse(200, "OK")
    resp.set_header("Via", "SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest")
    resp.set_header("From", "<sip:client1@127.0.0.1:5060>;tag=fromtag")
    resp.set_header("To", to_header)
    resp.set_header("Call-ID", call_id)
    resp.set_header("CSeq", cseq)
    resp.set_header("Content-Type", content_type)
    resp.body = _valid_sdp() if body is None else body
    return resp.serialize()


def _build_100_trying(call_id: str, cseq: str = "1 INVITE") -> bytes:
    resp = SipResponse(100, "Trying")
    resp.set_header("Via", "SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest")
    resp.set_header("From", "<sip:client1@127.0.0.1:5060>;tag=fromtag")
    resp.set_header("To", "<sip:client2@127.0.0.1:5061>")
    resp.set_header("Call-ID", call_id)
    resp.set_header("CSeq", cseq)
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
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [_build_200_ok("<sip:client2@127.0.0.1:5061>", session.call_id)]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED
    assert len(fake_sock.sent) == 1


def test_receive_200_ok_empty_to_tag_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [_build_200_ok("<sip:client2@127.0.0.1:5061>;tag=", session.call_id)]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED
    assert len(fake_sock.sent) == 1


def test_receive_200_ok_valid_to_tag_sends_ack():
    to_tag = "dialog123"
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [_build_200_ok(f"<sip:client2@127.0.0.1:5061>;tag={to_tag}", session.call_id)]

    assert session.receive_200_ok() is True
    assert session.state == CallerState.ESTABLISHED
    assert session.to_tag == to_tag
    assert len(fake_sock.sent) == 2

    ack = parse(fake_sock.sent[-1][0])
    assert isinstance(ack, SipRequest)
    assert ack.method == "ACK"
    assert f";tag={to_tag}" in ack.get_header("To")


def test_receive_200_ok_call_id_mismatch_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [_build_200_ok("<sip:client2@127.0.0.1:5061>;tag=ok", "different-call-id")]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED


def test_receive_200_ok_malformed_remote_sdp_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [
        _build_200_ok(
            "<sip:client2@127.0.0.1:5061>;tag=ok",
            session.call_id,
            body="v=0\r\nm=audio\r\n",
        )
    ]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED


def test_receive_200_ok_without_sdp_body_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [
        _build_200_ok(
            "<sip:client2@127.0.0.1:5061>;tag=ok",
            session.call_id,
            body="",
        )
    ]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED


def test_receive_200_ok_wrong_content_type_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [
        _build_200_ok(
            "<sip:client2@127.0.0.1:5061>;tag=ok",
            session.call_id,
            content_type="text/plain",
            body="hello",
        )
    ]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED


def test_receive_200_ok_cseq_mismatch_fails():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [
        _build_200_ok(
            "<sip:client2@127.0.0.1:5061>;tag=ok",
            session.call_id,
            cseq="2 INVITE",
        )
    ]

    assert session.receive_200_ok() is False
    assert session.state == CallerState.TERMINATED


def test_receive_200_ok_after_provisional_response_succeeds():
    to_tag = "dialog123"
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [
        _build_100_trying(session.call_id),
        _build_200_ok(f"<sip:client2@127.0.0.1:5061>;tag={to_tag}", session.call_id),
    ]

    assert session.receive_200_ok() is True
    assert session.state == CallerState.ESTABLISHED
    assert session.to_tag == to_tag


def test_send_bye_invalid_state_raises():
    session = _new_session(_FakeUdpSocket([]))
    with pytest.raises(SessionError):
        session.send_bye()


def test_send_bye_in_invite_sent_state_raises():
    session = _new_session(_FakeUdpSocket([]))
    session.send_invite()
    with pytest.raises(SessionError):
        session.send_bye()


def test_callee_wait_for_invite_with_malformed_sdp_sends_488():
    bad_invite, _, _ = build_invite(
        caller_ip="127.0.0.1",
        caller_sip_port=5060,
        callee_ip="127.0.0.1",
        callee_sip_port=5061,
        sdp_body="v=0\r\nm=audio\r\n",
    )
    fake_sock = _FakeUdpSocket([bad_invite.serialize()], addr="127.0.0.1", port=5060)
    session = CalleeSession(
        sock=fake_sock,
        local_ip="127.0.0.1",
        local_sip_port=5061,
        local_sdp=_offer_sdp(),
    )

    assert session.wait_for_invite() is False
    assert session.state == CalleeState.TERMINATED
    assert len(fake_sock.sent) == 1

    err = parse(fake_sock.sent[0][0])
    assert isinstance(err, SipResponse)
    assert err.status_code == 488


def test_callee_wait_for_invite_ignores_unexpected_request_then_accepts_invite():
    noise = SipRequest("OPTIONS", "sip:client2@127.0.0.1:5061")
    noise.set_header("Call-ID", "noise")
    invite, _, _ = build_invite(
        caller_ip="127.0.0.1",
        caller_sip_port=5060,
        callee_ip="127.0.0.1",
        callee_sip_port=5061,
        sdp_body=_valid_sdp(),
    )
    fake_sock = _FakeUdpSocket([noise.serialize(), invite.serialize()], addr="127.0.0.1", port=5060)
    session = CalleeSession(
        sock=fake_sock,
        local_ip="127.0.0.1",
        local_sip_port=5061,
        local_sdp=_offer_sdp(),
    )

    assert session.wait_for_invite() is True
    assert session.state == CalleeState.INVITE_RECEIVED


def test_callee_wait_for_ack_ignores_unexpected_request_then_accepts_ack():
    fake_sock = _FakeUdpSocket([])
    session = _new_session(fake_sock)
    session.send_invite()
    fake_sock._responses = [_build_200_ok("<sip:client2@127.0.0.1:5061>;tag=dialog", session.call_id)]
    assert session.receive_200_ok() is True

    bye = SipRequest("BYE", "sip:client2@127.0.0.1:5061")
    bye.set_header("Call-ID", session.call_id)
    bye.set_header("CSeq", "2 BYE")
    ack = SipRequest("ACK", "sip:client2@127.0.0.1:5061")
    ack.set_header("Call-ID", session.call_id)
    ack.set_header("CSeq", "1 ACK")

    callee_sock = _FakeUdpSocket([bye.serialize(), ack.serialize()], addr="127.0.0.1", port=5060)
    callee = CalleeSession(
        sock=callee_sock,
        local_ip="127.0.0.1",
        local_sip_port=5061,
        local_sdp=_offer_sdp(),
    )
    callee.state = CalleeState.OK_SENT

    assert callee.wait_for_ack() is True
    assert callee.state == CalleeState.ESTABLISHED
