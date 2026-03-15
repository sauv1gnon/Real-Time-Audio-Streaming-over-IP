"""Tests for the RTCP Sender Report packet."""

import struct
import pytest
from rtp.rtcp import RtcpPacket, _SR_SIZE, _RTCP_SR_PT


class TestRtcpPacketSerialize:
    def test_length_is_28_bytes(self):
        pkt = RtcpPacket(
            ssrc=1,
            ntp_timestamp_hi=0,
            ntp_timestamp_lo=0,
            rtp_timestamp=0,
            packet_count=10,
            octet_count=3200,
        )
        data = pkt.serialize()
        assert len(data) == 28

    def test_version_bits(self):
        pkt = RtcpPacket(ssrc=1, ntp_timestamp_hi=0, ntp_timestamp_lo=0,
                         rtp_timestamp=0, packet_count=0, octet_count=0)
        data = pkt.serialize()
        version = (data[0] >> 6) & 0x3
        assert version == 2

    def test_payload_type_200(self):
        pkt = RtcpPacket(ssrc=1, ntp_timestamp_hi=0, ntp_timestamp_lo=0,
                         rtp_timestamp=0, packet_count=0, octet_count=0)
        data = pkt.serialize()
        assert data[1] == _RTCP_SR_PT

    def test_ssrc_encoded(self):
        pkt = RtcpPacket(ssrc=0xDEADBEEF, ntp_timestamp_hi=0, ntp_timestamp_lo=0,
                         rtp_timestamp=0, packet_count=0, octet_count=0)
        data = pkt.serialize()
        ssrc = struct.unpack_from("!I", data, 4)[0]
        assert ssrc == 0xDEADBEEF

    def test_packet_and_octet_counts(self):
        pkt = RtcpPacket(ssrc=1, ntp_timestamp_hi=0, ntp_timestamp_lo=0,
                         rtp_timestamp=0, packet_count=42, octet_count=13440)
        data = pkt.serialize()
        pkt_cnt = struct.unpack_from("!I", data, 20)[0]
        oct_cnt = struct.unpack_from("!I", data, 24)[0]
        assert pkt_cnt == 42
        assert oct_cnt == 13440


class TestRtcpPacketParse:
    def _build_raw(self, ssrc=1, pkt_cnt=5, oct_cnt=1600):
        b0 = 0x80
        length_words = (_SR_SIZE // 4) - 1
        return struct.pack(
            "!BBHIIIIII",
            b0, _RTCP_SR_PT, length_words,
            ssrc, 0, 0, 0, pkt_cnt, oct_cnt,
        )

    def test_parse_basic(self):
        raw = self._build_raw(ssrc=99, pkt_cnt=7, oct_cnt=2240)
        pkt = RtcpPacket.parse(raw)
        assert pkt.ssrc == 99
        assert pkt.packet_count == 7
        assert pkt.octet_count == 2240

    def test_parse_too_short_raises(self):
        with pytest.raises(ValueError):
            RtcpPacket.parse(b"\x80\xc8\x00")


class TestRtcpRoundTrip:
    def test_serialize_then_parse(self):
        original = RtcpPacket(
            ssrc=0xABCD,
            ntp_timestamp_hi=3900000000,
            ntp_timestamp_lo=2147483648,
            rtp_timestamp=12800,
            packet_count=80,
            octet_count=25600,
        )
        parsed = RtcpPacket.parse(original.serialize())
        assert parsed.ssrc == original.ssrc
        assert parsed.ntp_timestamp_hi == original.ntp_timestamp_hi
        assert parsed.ntp_timestamp_lo == original.ntp_timestamp_lo
        assert parsed.rtp_timestamp == original.rtp_timestamp
        assert parsed.packet_count == original.packet_count
        assert parsed.octet_count == original.octet_count
