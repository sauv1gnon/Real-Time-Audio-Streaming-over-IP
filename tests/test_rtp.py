"""Tests for RTP packet builder and parser."""

import struct
import pytest
from rtp.packet import RtpPacket, _HEADER_SIZE
from rtp.sender import RtpSender
from core.exceptions import RtpError


class TestRtpPacketSerialize:
    def test_fixed_header_length(self):
        pkt = RtpPacket(payload_type=96, sequence_number=1, timestamp=160, ssrc=0xDEADBEEF, payload=b"\x00" * 320)
        data = pkt.serialize()
        assert len(data) == _HEADER_SIZE + 320

    def test_version_in_header(self):
        pkt = RtpPacket(payload_type=96, sequence_number=1, timestamp=160, ssrc=0, payload=b"")
        data = pkt.serialize()
        version = (data[0] >> 6) & 0x3
        assert version == 2

    def test_payload_type_encoded(self):
        pkt = RtpPacket(payload_type=96, sequence_number=0, timestamp=0, ssrc=0, payload=b"")
        data = pkt.serialize()
        pt = data[1] & 0x7F
        assert pt == 96

    def test_sequence_number_big_endian(self):
        pkt = RtpPacket(payload_type=0, sequence_number=1000, timestamp=0, ssrc=0, payload=b"")
        data = pkt.serialize()
        seq = struct.unpack_from("!H", data, 2)[0]
        assert seq == 1000

    def test_timestamp_encoded(self):
        pkt = RtpPacket(payload_type=0, sequence_number=0, timestamp=320, ssrc=0, payload=b"")
        data = pkt.serialize()
        ts = struct.unpack_from("!I", data, 4)[0]
        assert ts == 320

    def test_ssrc_encoded(self):
        pkt = RtpPacket(payload_type=0, sequence_number=0, timestamp=0, ssrc=0xCAFEBABE, payload=b"")
        data = pkt.serialize()
        ssrc = struct.unpack_from("!I", data, 8)[0]
        assert ssrc == 0xCAFEBABE

    def test_marker_bit(self):
        pkt = RtpPacket(payload_type=96, sequence_number=0, timestamp=0, ssrc=0, payload=b"", marker=True)
        data = pkt.serialize()
        assert data[1] & 0x80

    def test_payload_appended(self):
        payload = b"\xAB\xCD" * 10
        pkt = RtpPacket(payload_type=96, sequence_number=0, timestamp=0, ssrc=0, payload=payload)
        data = pkt.serialize()
        assert data[_HEADER_SIZE:] == payload


class TestRtpPacketParse:
    def _make_raw(self, version=2, pt=96, seq=1, ts=160, ssrc=42, payload=b"pcmdata"):
        b0 = (version << 6)
        b1 = pt & 0x7F
        return struct.pack("!BBHII", b0, b1, seq, ts, ssrc) + payload

    def test_parse_basic(self):
        raw = self._make_raw()
        pkt = RtpPacket.parse(raw)
        assert pkt.version == 2
        assert pkt.payload_type == 96
        assert pkt.sequence_number == 1
        assert pkt.timestamp == 160
        assert pkt.ssrc == 42
        assert pkt.payload == b"pcmdata"

    def test_parse_wrong_version_raises(self):
        raw = self._make_raw(version=1)
        with pytest.raises(RtpError):
            RtpPacket.parse(raw)

    def test_parse_too_short_raises(self):
        with pytest.raises(RtpError):
            RtpPacket.parse(b"\x80\x60\x00")


class TestRtpRoundTrip:
    def test_serialize_then_parse(self):
        original = RtpPacket(
            payload_type=96,
            sequence_number=12345,
            timestamp=999999,
            ssrc=0xABCD1234,
            payload=b"\x01\x02\x03\x04",
            marker=True,
        )
        parsed = RtpPacket.parse(original.serialize())
        assert parsed.payload_type == original.payload_type
        assert parsed.sequence_number == original.sequence_number
        assert parsed.timestamp == original.timestamp
        assert parsed.ssrc == original.ssrc
        assert parsed.payload == original.payload
        assert parsed.marker == original.marker

    def test_sequence_number_wrap(self):
        pkt = RtpPacket(payload_type=0, sequence_number=0xFFFF, timestamp=0, ssrc=0, payload=b"")
        parsed = RtpPacket.parse(pkt.serialize())
        assert parsed.sequence_number == 0xFFFF


class _DummyUdpSocket:
    def __init__(self):
        self.sent: list[tuple[bytes, str, int]] = []

    def send(self, data: bytes, remote_ip: str, remote_port: int) -> None:
        self.sent.append((data, remote_ip, remote_port))


class TestRtpSenderTimestamp:
    def test_current_timestamp_exposed(self):
        sender = RtpSender(_DummyUdpSocket(), "127.0.0.1", 5004, frame_duration_ms=0.0)
        assert sender.current_timestamp == sender._timestamp

    def test_current_timestamp_increments_after_send(self):
        sender = RtpSender(_DummyUdpSocket(), "127.0.0.1", 5004, frame_duration_ms=0.0)
        initial = sender.current_timestamp

        sender.send_frames(iter([b"\x00\x01" * 160]))

        assert sender.current_timestamp == (initial + sender.samples_per_frame) & 0xFFFFFFFF

    def test_current_timestamp_wraps(self):
        sender = RtpSender(_DummyUdpSocket(), "127.0.0.1", 5004, frame_duration_ms=0.0)
        sender._timestamp = 0xFFFFFFFF - 10

        sender.send_frames(iter([b"\x00\x01" * 160]))

        expected = (0xFFFFFFFF - 10 + sender.samples_per_frame) & 0xFFFFFFFF
        assert sender.current_timestamp == expected
