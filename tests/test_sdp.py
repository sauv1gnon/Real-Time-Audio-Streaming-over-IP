"""Tests for SDP builder and parser."""

import pytest
from sip.sdp import SdpDescription
from core.exceptions import SdpError


class TestSdpBuild:
    def test_build_contains_required_fields(self):
        sdp = SdpDescription(
            media_ip="192.168.1.10",
            rtp_port=10000,
            payload_type=96,
            codec_name="L16",
            clock_rate=8000,
        )
        text = sdp.build()
        assert "v=0" in text
        assert "o=" in text
        assert "s=" in text
        assert "c=IN IP4 192.168.1.10" in text
        assert "t=0 0" in text
        assert "m=audio 10000 RTP/AVP 96" in text
        assert "a=rtpmap:96 L16/8000" in text

    def test_build_crlf_lines(self):
        sdp = SdpDescription()
        text = sdp.build()
        assert "\r\n" in text

    def test_extra_attrs_included(self):
        sdp = SdpDescription(extra_attrs=["sendonly"])
        text = sdp.build()
        assert "a=sendonly" in text


class TestSdpParse:
    def _sample_sdp(self, ip="127.0.0.1", port=10000, pt=96, codec="L16", rate=8000):
        return (
            f"v=0\r\n"
            f"o=- 12345 1 IN IP4 {ip}\r\n"
            f"s=Test Session\r\n"
            f"c=IN IP4 {ip}\r\n"
            f"t=0 0\r\n"
            f"m=audio {port} RTP/AVP {pt}\r\n"
            f"a=rtpmap:{pt} {codec}/{rate}\r\n"
        )

    def test_parse_basic(self):
        text = self._sample_sdp()
        desc = SdpDescription.parse(text)
        assert desc.media_ip == "127.0.0.1"
        assert desc.rtp_port == 10000
        assert desc.payload_type == 96
        assert desc.codec_name == "L16"
        assert desc.clock_rate == 8000

    def test_parse_custom_ip_and_port(self):
        text = self._sample_sdp(ip="10.0.0.5", port=20000)
        desc = SdpDescription.parse(text)
        assert desc.media_ip == "10.0.0.5"
        assert desc.rtp_port == 20000

    def test_parse_origin(self):
        text = self._sample_sdp()
        desc = SdpDescription.parse(text)
        assert desc.session_id == "12345"

    def test_parse_session_name(self):
        text = self._sample_sdp()
        desc = SdpDescription.parse(text)
        assert desc.session_name == "Test Session"

    def test_malformed_media_line_raises(self):
        bad_sdp = "v=0\r\nm=audio\r\n"  # Missing port
        with pytest.raises(SdpError):
            SdpDescription.parse(bad_sdp)

    def test_unsupported_media_type_raises(self):
        bad_sdp = "v=0\r\nm=video 5000 RTP/AVP 96\r\n"
        with pytest.raises(SdpError):
            SdpDescription.parse(bad_sdp)

    def test_invalid_rtp_port_raises(self):
        bad_sdp = "v=0\r\nm=audio notaport RTP/AVP 96\r\n"
        with pytest.raises(SdpError):
            SdpDescription.parse(bad_sdp)

    def test_invalid_connection_ip_raises(self):
        bad_sdp = "v=0\r\nc=IN IP4 not-an-ip\r\n"
        with pytest.raises(SdpError, match="Invalid IPv4"):
            SdpDescription.parse(bad_sdp)

    def test_missing_payload_type_raises(self):
        bad_sdp = "v=0\r\nm=audio 10000 RTP/AVP\r\n"
        with pytest.raises(SdpError, match="Malformed m="):
            SdpDescription.parse(bad_sdp)

    def test_invalid_rtpmap_rate_raises(self):
        bad_sdp = (
            "v=0\r\n"
            "m=audio 10000 RTP/AVP 96\r\n"
            "a=rtpmap:96 L16/notanumber\r\n"
        )
        with pytest.raises(SdpError, match="Invalid codec rate"):
            SdpDescription.parse(bad_sdp)

    def test_malformed_origin_line_raises(self):
        bad_sdp = (
            "v=0\r\n"
            "o=- 12345\r\n"
            "s=Test Session\r\n"
            "c=IN IP4 127.0.0.1\r\n"
            "m=audio 10000 RTP/AVP 96\r\n"
            "a=rtpmap:96 L16/8000\r\n"
        )
        with pytest.raises(SdpError, match="Malformed o="):
            SdpDescription.parse(bad_sdp)

    def test_payload_type_mismatch_between_m_and_rtpmap_raises(self):
        bad_sdp = (
            "v=0\r\n"
            "o=- 12345 1 IN IP4 127.0.0.1\r\n"
            "s=Test Session\r\n"
            "c=IN IP4 127.0.0.1\r\n"
            "m=audio 10000 RTP/AVP 96\r\n"
            "a=rtpmap:97 L16/8000\r\n"
        )
        with pytest.raises(SdpError, match="Payload type mismatch"):
            SdpDescription.parse(bad_sdp)


class TestSdpRoundTrip:
    def test_build_then_parse(self):
        original = SdpDescription(
            media_ip="192.168.50.1",
            rtp_port=12000,
            payload_type=96,
            codec_name="L16",
            clock_rate=8000,
        )
        parsed = SdpDescription.parse(original.build())
        assert parsed.media_ip == "192.168.50.1"
        assert parsed.rtp_port == 12000
        assert parsed.payload_type == 96
        assert parsed.codec_name == "L16"
        assert parsed.clock_rate == 8000
