"""Tests for RTP packet builder and parser."""

import struct
import pytest
from rtp.packet import RtpPacket, _HEADER_SIZE
from rtp.jitter_buffer import JitterBuffer
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


class _FailingUdpSocket:
    def send(self, data: bytes, remote_ip: str, remote_port: int) -> None:
        raise OSError("simulated send failure")


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

    def test_send_failure_is_counted_and_stops_cleanly(self):
        sender = RtpSender(_FailingUdpSocket(), "127.0.0.1", 5004, frame_duration_ms=0.0)

        sender.send_frames(iter([b"\x00\x01" * 160]))

        assert sender.send_errors == 1
        assert sender.packets_sent == 0
        assert sender.bytes_sent == 0

    def test_simulated_packet_loss_drops_all_frames(self):
        sock = _DummyUdpSocket()
        sender = RtpSender(
            sock,
            "127.0.0.1",
            5004,
            frame_duration_ms=0.0,
            packet_loss=1.0,
            random_func=lambda: 0.0,
        )
        initial_timestamp = sender.current_timestamp

        sender.send_frames(iter([b"\x00\x01" * 160] * 3))

        assert len(sock.sent) == 0
        assert sender.packets_sent == 0
        assert sender.bytes_sent == 0
        assert sender.simulated_drops == 3
        assert sender.current_timestamp == (initial_timestamp + 3 * sender.samples_per_frame) & 0xFFFFFFFF

    def test_simulated_packet_loss_preserves_rtp_sequence_progression(self):
        sock = _DummyUdpSocket()
        random_values = iter([0.9, 0.1, 0.9])

        sender = RtpSender(
            sock,
            "127.0.0.1",
            5004,
            frame_duration_ms=0.0,
            packet_loss=0.5,
            random_func=lambda: next(random_values),
        )

        sender.send_frames(iter([b"\x00\x01" * 160] * 3))

        assert sender.packets_sent == 2
        assert sender.simulated_drops == 1

        first_pkt = RtpPacket.parse(sock.sent[0][0])
        second_pkt = RtpPacket.parse(sock.sent[1][0])
        assert second_pkt.sequence_number == (first_pkt.sequence_number + 2) & 0xFFFF

    def test_invalid_packet_loss_probability_raises_value_error(self):
        with pytest.raises(ValueError, match="packet_loss"):
            RtpSender(_DummyUdpSocket(), "127.0.0.1", 5004, packet_loss=1.5)


class TestJitterBuffer:
    def test_flush_preserves_wraparound_order(self):
        jb = JitterBuffer(max_depth=3)

        assert jb.push(65533, b"a") == [b"a"]
        assert jb.push(65535, b"c") == []
        assert jb.push(0, b"d") == []
        flushed = jb.push(1, b"e")

        assert flushed == [b"c", b"d", b"e"]

    def test_flush_with_sequence_preserves_wraparound_order(self):
        jb = JitterBuffer(max_depth=3)

        assert jb.push_with_sequence(65533, b"a") == [(65533, b"a")]
        assert jb.push_with_sequence(65535, b"c") == []
        assert jb.push_with_sequence(0, b"d") == []
        flushed = jb.push_with_sequence(1, b"e")

        assert flushed == [(65535, b"c"), (0, b"d"), (1, b"e")]
