"""Integration tests — run both client sides in-process using threads.

These tests exercise the full SIP handshake + RTP streaming pipeline on
localhost without requiring real audio hardware.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
import wave
from pathlib import Path

import pytest

from net.udp import UdpSocketAdapter
from rtp.packet import RtpPacket
from rtp.sender import RtpSender
from rtp.receiver import RtpReceiver
from rtp.rtcp import RtcpPacket, _SR_SIZE
from sip.messages import build_invite, build_200_ok, build_ack, build_bye, build_200_ok_bye
from sip.parser import parse
from sip.sdp import SdpDescription
from sip.session import CallerSession, CalleeSession
from media.wav_reader import WavAudioSource


# ---------------------------------------------------------------------------
# Helper: find free UDP ports
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# SIP handshake integration test
# ---------------------------------------------------------------------------

class TestSipHandshake:
    """Runs caller and callee in separate threads; verifies the full SIP flow."""

    def test_full_handshake(self):
        c1_sip = _free_port()
        c2_sip = _free_port()
        c1_rtp = _free_port()
        c2_rtp = _free_port()

        offer_sdp = SdpDescription(
            media_ip="127.0.0.1", rtp_port=c1_rtp,
            payload_type=96, codec_name="L16", clock_rate=8000,
        )
        answer_sdp = SdpDescription(
            media_ip="127.0.0.1", rtp_port=c2_rtp,
            payload_type=96, codec_name="L16", clock_rate=8000,
        )

        caller_ok = threading.Event()
        callee_established = threading.Event()
        callee_terminated = threading.Event()
        errors: list[str] = []

        def run_caller():
            sip_sock = UdpSocketAdapter("127.0.0.1", c1_sip, timeout=5.0)
            sip_sock.open()
            sess = CallerSession(sip_sock, "127.0.0.1", c1_sip, "127.0.0.1", c2_sip, offer_sdp)
            try:
                sess.send_invite()
                if not sess.receive_200_ok():
                    errors.append("Caller: no 200 OK")
                    return
                caller_ok.set()
                # Wait for callee to establish before sending BYE
                callee_established.wait(timeout=5.0)
                time.sleep(0.1)
                sess.send_bye()
                sess.receive_bye_ok()
            except Exception as exc:
                errors.append(f"Caller error: {exc}")
            finally:
                sip_sock.close()

        def run_callee():
            sip_sock = UdpSocketAdapter("127.0.0.1", c2_sip, timeout=5.0)
            sip_sock.open()
            sess = CalleeSession(sip_sock, "127.0.0.1", c2_sip, answer_sdp)
            try:
                if not sess.wait_for_invite():
                    errors.append("Callee: no INVITE")
                    return
                sess.send_200_ok()
                if not sess.wait_for_ack():
                    errors.append("Callee: no ACK")
                    return
                callee_established.set()
                sess.wait_for_bye()
                callee_terminated.set()
            except Exception as exc:
                errors.append(f"Callee error: {exc}")
            finally:
                sip_sock.close()

        t_callee = threading.Thread(target=run_callee, daemon=True)
        t_caller = threading.Thread(target=run_caller, daemon=True)
        t_callee.start()
        time.sleep(0.05)  # Ensure callee is listening first
        t_caller.start()

        t_caller.join(timeout=10.0)
        t_callee.join(timeout=10.0)

        assert not errors, f"Integration errors: {errors}"
        assert caller_ok.is_set(), "Caller never received 200 OK"
        assert callee_established.is_set(), "Callee never reached ESTABLISHED"
        assert callee_terminated.is_set(), "Callee never received BYE"


# ---------------------------------------------------------------------------
# RTP send / receive integration test
# ---------------------------------------------------------------------------

class TestRtpSendReceive:
    """Sends a few RTP frames and verifies the receiver collects them."""

    def test_frames_received(self):
        sender_port = _free_port()
        receiver_port = _free_port()

        frames = [b"\x00\x01" * 160] * 5  # 5 identical 320-byte PCM frames

        recv_sock = UdpSocketAdapter("127.0.0.1", receiver_port)
        recv_sock.open()
        send_sock = UdpSocketAdapter("127.0.0.1", sender_port)
        send_sock.open()

        receiver = RtpReceiver(recv_sock, payload_type=96)
        receiver.start()

        sender = RtpSender(
            send_sock,
            remote_ip="127.0.0.1",
            remote_port=receiver_port,
            payload_type=96,
            frame_duration_ms=5.0,   # fast for test speed
        )
        sender.send_frames(iter(frames))

        time.sleep(0.2)
        receiver.stop()

        assert receiver.packets_received == 5
        assert receiver.bytes_received == 5 * 320

        recv_sock.close()
        send_sock.close()


# ---------------------------------------------------------------------------
# RTCP integration test
# ---------------------------------------------------------------------------

class TestRtcpReporter:
    """Verifies that the RTCP reporter sends at least one SR."""

    def test_sr_received(self):
        rtcp_send_port = _free_port()
        rtcp_recv_port = _free_port()

        received: list[bytes] = []
        stop_recv = threading.Event()

        def _recv():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.bind(("127.0.0.1", rtcp_recv_port))
            while not stop_recv.is_set():
                try:
                    data, _ = sock.recvfrom(1024)
                    received.append(data)
                except socket.timeout:
                    pass
            sock.close()

        recv_thread = threading.Thread(target=_recv, daemon=True)
        recv_thread.start()
        time.sleep(0.05)

        from rtp.rtcp import RtcpReporter
        rtcp_sock = UdpSocketAdapter("127.0.0.1", rtcp_send_port)
        rtcp_sock.open()

        reporter = RtcpReporter(
            sock=rtcp_sock,
            remote_ip="127.0.0.1",
            remote_port=rtcp_recv_port,
            ssrc=0xABCDEF01,
            interval_s=0.2,
            get_stats=lambda: (10, 3200, 160),
        )
        reporter.start()
        time.sleep(0.6)   # Should get at least 2 reports
        reporter.stop()
        stop_recv.set()
        recv_thread.join(timeout=2.0)
        rtcp_sock.close()

        assert len(received) >= 1, f"Expected at least 1 RTCP SR, got {len(received)}"
        sr = RtcpPacket.parse(received[0])
        assert sr.ssrc == 0xABCDEF01
        assert sr.packet_count == 10
        assert sr.octet_count == 3200


# ---------------------------------------------------------------------------
# WAV reader integration test
# ---------------------------------------------------------------------------

class TestWavReader:
    def test_reads_sample_wav(self, tmp_path):
        # Generate a minimal WAV
        wav_path = tmp_path / "test.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00" * 3200)  # 200 ms of silence

        source = WavAudioSource(wav_path, frame_duration_ms=20.0)
        source.open()
        frames = list(source.frames())
        # 200 ms / 20 ms = 10 frames
        assert len(frames) == 10
        for frame in frames:
            assert len(frame) == source.bytes_per_frame

    def test_wrong_sample_rate_raises(self, tmp_path):
        from core.exceptions import MediaError
        wav_path = tmp_path / "bad.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)   # Wrong rate
            wf.writeframes(b"\x00" * 4410)

        source = WavAudioSource(wav_path, strict=True)
        with pytest.raises(MediaError):
            source.open()
