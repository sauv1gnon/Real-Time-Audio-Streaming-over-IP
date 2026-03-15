"""Tests for the RTCP Sender Report packet."""

import struct
import time
import pytest
from rtp.rtcp import RtcpPacket, RtcpReporter, _SR_SIZE, _RTCP_SR_PT


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

    def test_parse_wrong_version_raises(self):
        raw = bytearray(self._build_raw())
        raw[0] = 0x40
        with pytest.raises(ValueError, match="version"):
            RtcpPacket.parse(bytes(raw))

    def test_parse_wrong_packet_type_raises(self):
        raw = bytearray(self._build_raw())
        raw[1] = 201
        with pytest.raises(ValueError, match="packet type"):
            RtcpPacket.parse(bytes(raw))

    def test_parse_wrong_length_field_raises(self):
        raw = bytearray(self._build_raw())
        struct.pack_into("!H", raw, 2, 0)
        with pytest.raises(ValueError, match="length"):
            RtcpPacket.parse(bytes(raw))


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


class _DummyRtcpSocket:
    def __init__(self):
        self.sent = 0

    def send(self, *_args, **_kwargs):
        self.sent += 1


def test_reporter_skips_invalid_stats():
    sock = _DummyRtcpSocket()
    reporter = RtcpReporter(
        sock=sock,
        remote_ip="127.0.0.1",
        remote_port=5005,
        ssrc=123,
        interval_s=0.05,
        get_stats=lambda: (-1, 100, 10),
    )

    reporter.start()
    time.sleep(0.15)
    reporter.stop()

    assert sock.sent == 0


def test_reporter_handles_stats_callback_exception():
    sock = _DummyRtcpSocket()

    def _boom():
        raise RuntimeError("bad callback")

    reporter = RtcpReporter(
        sock=sock,
        remote_ip="127.0.0.1",
        remote_port=5005,
        ssrc=123,
        interval_s=0.05,
        get_stats=_boom,
    )

    reporter.start()
    time.sleep(0.15)
    reporter.stop()

    assert sock.sent == 0
