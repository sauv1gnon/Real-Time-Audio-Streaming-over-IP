"""Tests for the SIP parser."""

import pytest
from sip.parser import parse
from sip.messages import SipRequest, SipResponse, build_invite, build_200_ok, build_ack, build_bye
from core.exceptions import SipParseError


class TestParseRequest:
    def test_parse_invite(self):
        raw = (
            b"INVITE sip:bob@127.0.0.1:5061 SIP/2.0\r\n"
            b"Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest\r\n"
            b"From: <sip:alice@127.0.0.1>;tag=abc\r\n"
            b"To: <sip:bob@127.0.0.1>\r\n"
            b"Call-ID: callid001\r\n"
            b"CSeq: 1 INVITE\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipRequest)
        assert msg.method == "INVITE"
        assert msg.get_header("Call-ID") == "callid001"

    def test_parse_ack(self):
        raw = (
            b"ACK sip:bob@127.0.0.1:5061 SIP/2.0\r\n"
            b"Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest\r\n"
            b"Call-ID: callid001\r\n"
            b"CSeq: 1 ACK\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipRequest)
        assert msg.method == "ACK"

    def test_parse_bye(self):
        raw = (
            b"BYE sip:bob@127.0.0.1:5061 SIP/2.0\r\n"
            b"Call-ID: callid001\r\n"
            b"CSeq: 2 BYE\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipRequest)
        assert msg.method == "BYE"

    def test_parse_with_body(self):
        body = "v=0\r\nm=audio 10000 RTP/AVP 96\r\n"
        body_b = body.encode()
        raw = (
            b"INVITE sip:bob@127.0.0.1:5061 SIP/2.0\r\n"
            b"Content-Type: application/sdp\r\n"
            b"Content-Length: " + str(len(body_b)).encode() + b"\r\n"
            b"\r\n" + body_b
        )
        msg = parse(raw)
        assert msg.body == body


class TestParseResponse:
    def test_parse_200_ok(self):
        raw = (
            b"SIP/2.0 200 OK\r\n"
            b"Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bKtest\r\n"
            b"Call-ID: callid001\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipResponse)
        assert msg.status_code == 200

    def test_parse_404(self):
        raw = (
            b"SIP/2.0 404 Not Found\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipResponse)
        assert msg.status_code == 404
        assert msg.reason == "Not Found"

    def test_parse_200_ok_missing_to_tag(self):
        raw = (
            b"SIP/2.0 200 OK\r\n"
            b"To: <sip:bob@127.0.0.1:5061>\r\n"
            b"Call-ID: callid001\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipResponse)
        assert msg.get_header("To") == "<sip:bob@127.0.0.1:5061>"

    def test_parse_200_ok_empty_to_tag(self):
        raw = (
            b"SIP/2.0 200 OK\r\n"
            b"To: <sip:bob@127.0.0.1:5061>;tag=\r\n"
            b"Call-ID: callid001\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )
        msg = parse(raw)
        assert isinstance(msg, SipResponse)
        assert msg.get_header("To") == "<sip:bob@127.0.0.1:5061>;tag="


class TestParseErrors:
    def test_empty_bytes_raises(self):
        with pytest.raises(SipParseError):
            parse(b"")

    def test_malformed_response_status_code(self):
        raw = b"SIP/2.0 NOTANUMBER Reason\r\n\r\n"
        with pytest.raises(SipParseError):
            parse(raw)

    def test_malformed_request_too_few_parts(self):
        raw = b"INVITE\r\n\r\n"
        with pytest.raises(SipParseError):
            parse(raw)

    def test_rejects_non_sip2_request(self):
        raw = b"INVITE sip:bob@127.0.0.1 SIP/1.0\r\n\r\n"
        with pytest.raises(SipParseError, match="Unsupported SIP version"):
            parse(raw)

    def test_rejects_status_code_out_of_range(self):
        raw = b"SIP/2.0 9999 Invalid\r\n\r\n"
        with pytest.raises(SipParseError, match="out of range"):
            parse(raw)

    def test_rejects_negative_content_length(self):
        raw = b"SIP/2.0 200 OK\r\nContent-Length: -1\r\n\r\n"
        with pytest.raises(SipParseError, match="Content-Length out of range"):
            parse(raw)

    def test_rejects_content_length_larger_than_body(self):
        raw = b"SIP/2.0 200 OK\r\nContent-Length: 10\r\n\r\nabc"
        with pytest.raises(SipParseError, match="exceeds available body"):
            parse(raw)


class TestRoundTrip:
    """Ensure that serialised messages can be parsed back correctly."""

    def test_invite_round_trip(self):
        req, call_id, from_tag = build_invite(
            "127.0.0.1", 5060, "127.0.0.1", 5061, "v=0\r\n"
        )
        parsed = parse(req.serialize())
        assert isinstance(parsed, SipRequest)
        assert parsed.method == "INVITE"
        assert parsed.get_header("Call-ID") == call_id

    def test_bye_round_trip(self):
        bye = build_bye("127.0.0.1", 5060, "127.0.0.1", 5061, "c1", "f1", "t1")
        parsed = parse(bye.serialize())
        assert isinstance(parsed, SipRequest)
        assert parsed.method == "BYE"
