"""Tests for SIP message builder and serialization."""

import pytest
from sip.messages import (
    SipRequest,
    SipResponse,
    build_invite,
    build_200_ok,
    build_ack,
    build_bye,
    build_200_ok_bye,
    build_error_response,
)


class TestSipRequest:
    def test_serialize_basic(self):
        req = SipRequest("INVITE", "sip:bob@192.168.1.2:5060")
        req.set_header("Via", "SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest")
        req.set_header("From", "<sip:alice@127.0.0.1>;tag=abc123")
        req.set_header("To", "<sip:bob@192.168.1.2>")
        req.set_header("Call-ID", "callid001")
        req.set_header("CSeq", "1 INVITE")
        req.set_header("Max-Forwards", "70")
        req.body = ""
        data = req.serialize()
        assert data.startswith(b"INVITE sip:bob@192.168.1.2:5060 SIP/2.0")
        assert b"Via:" in data
        assert b"From:" in data
        assert b"Call-ID: callid001" in data

    def test_content_length_set_automatically(self):
        req = SipRequest("ACK", "sip:bob@10.0.0.1:5061")
        req.body = "hello"
        data = req.serialize()
        assert b"Content-Length: 5" in data
        assert b"hello" in data

    def test_empty_body_content_length_zero(self):
        req = SipRequest("BYE", "sip:bob@10.0.0.1:5061")
        data = req.serialize()
        assert b"Content-Length: 0" in data


class TestSipResponse:
    def test_serialize_200_ok(self):
        resp = SipResponse(200, "OK")
        resp.set_header("Call-ID", "xyz")
        data = resp.serialize()
        assert data.startswith(b"SIP/2.0 200 OK")
        assert b"Call-ID: xyz" in data

    def test_serialize_4xx(self):
        resp = SipResponse(404, "Not Found")
        data = resp.serialize()
        assert b"404 Not Found" in data


class TestBuildInvite:
    def test_returns_request_and_ids(self):
        req, call_id, from_tag = build_invite(
            caller_ip="127.0.0.1",
            caller_sip_port=5060,
            callee_ip="127.0.0.1",
            callee_sip_port=5061,
            sdp_body="v=0\r\n",
        )
        assert req.method == "INVITE"
        assert call_id
        assert from_tag
        assert req.get_header("Call-ID") == call_id
        assert from_tag in req.get_header("From")

    def test_all_required_headers_present(self):
        req, _, _ = build_invite("127.0.0.1", 5060, "127.0.0.1", 5061, "v=0\r\n")
        for header in ("Via", "From", "To", "Call-ID", "CSeq", "Contact", "Max-Forwards"):
            assert req.get_header(header), f"Missing header: {header}"

    def test_sdp_body_embedded(self):
        sdp = "v=0\r\nm=audio 10000 RTP/AVP 96\r\n"
        req, _, _ = build_invite("127.0.0.1", 5060, "127.0.0.1", 5061, sdp)
        assert req.body == sdp
        assert req.get_header("Content-Type") == "application/sdp"


class TestBuild200Ok:
    def _make_invite(self):
        req, call_id, from_tag = build_invite(
            "127.0.0.1", 5060, "127.0.0.1", 5061, "v=0\r\n"
        )
        return req, call_id, from_tag

    def test_copies_dialog_headers(self):
        invite, call_id, _ = self._make_invite()
        resp = build_200_ok(invite, "127.0.0.1", 5061, "v=0\r\n")
        assert resp.get_header("Call-ID") == call_id
        assert resp.status_code == 200

    def test_to_tag_added(self):
        invite, _, _ = self._make_invite()
        resp = build_200_ok(invite, "127.0.0.1", 5061, "v=0\r\n")
        assert ";tag=" in resp.get_header("To")

    def test_sdp_embedded(self):
        invite, _, _ = self._make_invite()
        sdp = "v=0\r\nm=audio 10002 RTP/AVP 96\r\n"
        resp = build_200_ok(invite, "127.0.0.1", 5061, sdp)
        assert resp.body == sdp


class TestBuildAck:
    def test_ack_method_and_headers(self):
        ack = build_ack("127.0.0.1", 5060, "127.0.0.1", 5061, "call1", "ftag", "ttag")
        assert ack.method == "ACK"
        assert "call1" in ack.get_header("Call-ID")
        assert "1 ACK" in ack.get_header("CSeq")


class TestBuildBye:
    def test_bye_method_and_cseq(self):
        bye = build_bye("127.0.0.1", 5060, "127.0.0.1", 5061, "c1", "f1", "t1")
        assert bye.method == "BYE"
        assert "2 BYE" in bye.get_header("CSeq")

    def test_custom_cseq(self):
        bye = build_bye("127.0.0.1", 5060, "127.0.0.1", 5061, "c1", "f1", "t1", cseq=5)
        assert "5 BYE" in bye.get_header("CSeq")


class TestBuildErrorResponse:
    def test_404_response(self):
        req = SipRequest("INVITE", "sip:unknown@10.0.0.1")
        req.set_header("Via", "SIP/2.0/UDP 10.0.0.1:5060;branch=z9hG4bKtest")
        req.set_header("From", "<sip:alice@10.0.0.1>")
        req.set_header("To", "<sip:bob@10.0.0.2>")
        req.set_header("Call-ID", "abc")
        req.set_header("CSeq", "1 INVITE")
        resp = build_error_response(req, 404, "Not Found")
        assert resp.status_code == 404
        assert resp.get_header("Call-ID") == "abc"
