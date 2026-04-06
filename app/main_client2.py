"""Client 2 — Callee / receiver.

Usage:
    python -m app.main_client2

Environment variables (see app/config.py):
    CLIENT1_IP, CLIENT2_IP, CLIENT2_SIP_PORT, CLIENT2_RTP_PORT, OUTPUT_WAV …
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app import config as cfg
from core.log import get_logger
from media.mic_source import MicrophoneAudioSource
from media.playback import AudioPlaybackSink
from media.wav_reader import WavAudioSource
from net.udp import UdpSocketAdapter
from rtp.jitter_buffer import JitterBuffer
from rtp.receiver import RtpReceiver
from rtp.rtcp import RtcpReporter
from rtp.sender import RtpSender
from sip.sdp import SdpDescription
from sip.session import CalleeSession

logger = get_logger("app.client2")


def run() -> None:
    logger.info("=== Client 2 (Callee) starting ===")
    logger.info("  SIP  : listening on %s:%d", cfg.CLIENT2_IP, cfg.CLIENT2_SIP_PORT)
    logger.info("  RTP  : listening on %s:%d", cfg.CLIENT2_IP, cfg.CLIENT2_RTP_PORT)
    logger.info("  Output WAV: %s", cfg.OUTPUT_WAV)
    logger.info("  Two-way mode: %s", cfg.TWO_WAY_CALL)
    logger.info("  RTP packet loss (sender): %.2f", cfg.PACKET_LOSS)

    # -----------------------------------------------------------------------
    # Build callee SDP answer
    # -----------------------------------------------------------------------
    answer_sdp = SdpDescription(
        unicast_addr=cfg.CLIENT2_IP,
        media_ip=cfg.CLIENT2_IP,
        rtp_port=cfg.CLIENT2_RTP_PORT,
        payload_type=cfg.PAYLOAD_TYPE,
        codec_name="L16",
        clock_rate=cfg.SAMPLE_RATE,
    )

    # -----------------------------------------------------------------------
    # SIP handshake
    # -----------------------------------------------------------------------
    sip_sock: UdpSocketAdapter | None = None
    rtp_sock: UdpSocketAdapter | None = None
    receiver: RtpReceiver | None = None
    sink: AudioPlaybackSink | None = None
    reporter: RtcpReporter | None = None
    uplink_sender_thread: threading.Thread | None = None
    uplink_stop = threading.Event()
    rtcp_sock: UdpSocketAdapter | None = None
    sip_watcher: threading.Thread | None = None
    bye_event = threading.Event()

    try:
        sip_sock = UdpSocketAdapter(cfg.CLIENT2_IP, cfg.CLIENT2_SIP_PORT, timeout=cfg.SIP_TIMEOUT_S)
        sip_sock.open()
        session = CalleeSession(
            sock=sip_sock,
            local_ip=cfg.CLIENT2_IP,
            local_sip_port=cfg.CLIENT2_SIP_PORT,
            local_sdp=answer_sdp,
        )

        invite_wait_s = 60.0 if cfg.TWO_WAY_CALL else 30.0
        if not session.wait_for_invite(max_wait_s=invite_wait_s):
            logger.error("No INVITE received — exiting")
            return

        session.send_200_ok()
        if not session.wait_for_ack():
            logger.error("No ACK received — exiting")
            return

        # Determine the sender's RTP endpoint from the SDP offer
        rtp_src_ip = cfg.CLIENT1_IP
        rtp_src_port = cfg.CLIENT1_RTP_PORT
        if session.remote_sdp is not None:
            rtp_src_ip = session.remote_sdp.media_ip
            rtp_src_port = session.remote_sdp.rtp_port

        logger.info("Call established — receiving RTP from %s", rtp_src_ip)

        # -----------------------------------------------------------------------
        # RTP receiver + playback sink
        # -----------------------------------------------------------------------
        rtp_sock = UdpSocketAdapter(cfg.CLIENT2_IP, cfg.CLIENT2_RTP_PORT)
        rtp_sock.open()

        receiver = RtpReceiver(
            sock=rtp_sock,
            payload_type=cfg.PAYLOAD_TYPE,
            jitter_buffer=JitterBuffer(max_depth=5),
        )

        sink = AudioPlaybackSink(
            sample_rate=cfg.SAMPLE_RATE,
            channels=cfg.CHANNELS,
            sample_width=cfg.SAMPLE_WIDTH,
            output_path=cfg.OUTPUT_WAV,
            enable_live_playback=cfg.LIVE_PLAYBACK,
        )
        sink.start()
        receiver.start()

        if cfg.TWO_WAY_CALL:
            if cfg.AUDIO_SOURCE == "mic":
                uplink_source = MicrophoneAudioSource(
                    sample_rate=cfg.SAMPLE_RATE,
                    channels=cfg.CHANNELS,
                    frame_duration_ms=cfg.FRAME_DURATION_MS,
                    duration_s=cfg.MIC_DURATION_S,
                )
            else:
                uplink_source = WavAudioSource(
                    Path(cfg.SAMPLE_WAV),
                    frame_duration_ms=cfg.FRAME_DURATION_MS,
                )
            uplink_source.open()

            sender = RtpSender(
                sock=rtp_sock,
                remote_ip=rtp_src_ip,
                remote_port=rtp_src_port,
                payload_type=cfg.PAYLOAD_TYPE,
                samples_per_frame=uplink_source.samples_per_frame,
                frame_duration_ms=cfg.FRAME_DURATION_MS,
                packet_loss=cfg.PACKET_LOSS,
            )
            rtcp_sock = UdpSocketAdapter(cfg.CLIENT2_IP, cfg.CLIENT2_RTCP_PORT)
            rtcp_sock.open()
            reporter = RtcpReporter(
                sock=rtcp_sock,
                remote_ip=rtp_src_ip,
                remote_port=cfg.CLIENT1_RTCP_PORT,
                ssrc=sender.ssrc,
                interval_s=cfg.RTCP_INTERVAL_S,
                get_stats=sender.get_stats_snapshot,
            )
            reporter.start()

            def _uplink_send() -> None:
                try:
                    sender.send_frames(uplink_source.frames(), stop_event=uplink_stop)
                except Exception as exc:
                    logger.warning("Uplink sender exited with error: %s", exc)

            uplink_sender_thread = threading.Thread(target=_uplink_send, daemon=True, name="uplink-send")
            uplink_sender_thread.start()

        # -----------------------------------------------------------------------
        # Wait for BYE while forwarding received frames to the playback sink
        # -----------------------------------------------------------------------
        def _sip_bye_watcher() -> None:
            try:
                # Poll SIP BYE in chunks and keep waiting while RTP keeps flowing.
                poll_wait_s = max(0.5, min(cfg.SIP_TIMEOUT_S, 5.0))
                idle_grace_s = max(10.0, cfg.SIP_TIMEOUT_S * 2.0)

                # Hard safety cap in case BYE is never sent.
                hard_deadline_s = 180.0
                if cfg.TWO_WAY_CALL or cfg.AUDIO_SOURCE == "mic":
                    hard_deadline_s = max(hard_deadline_s, cfg.MIC_DURATION_S + 90.0)

                started_at = time.monotonic()
                last_progress_at = started_at
                last_packets = receiver.packets_received if receiver is not None else 0

                while True:
                    if session.wait_for_bye(max_wait_s=poll_wait_s, log_timeout=False, log_waiting=False):
                        return

                    now = time.monotonic()
                    if receiver is not None:
                        packets_now = receiver.packets_received
                        if packets_now > last_packets:
                            last_packets = packets_now
                            last_progress_at = now

                    if now - last_progress_at >= idle_grace_s:
                        logger.warning(
                            "Timed out waiting for BYE after %.1f seconds (no SIP BYE and no RTP progress for %.1f s)",
                            now - started_at,
                            idle_grace_s,
                        )
                        return

                    if now - started_at >= hard_deadline_s:
                        logger.warning(
                            "Timed out waiting for BYE after %.1f seconds (hard limit %.1f s)",
                            now - started_at,
                            hard_deadline_s,
                        )
                        return
            finally:
                bye_event.set()

        sip_watcher = threading.Thread(target=_sip_bye_watcher, daemon=True, name="bye-watcher")
        sip_watcher.start()

        logger.info("Forwarding frames to playback — waiting for BYE…")
        while not bye_event.is_set():
            frame = receiver.get_frame(timeout=0.5)
            if frame is not None:
                sink.push(frame)

        # Drain any remaining frames
        while True:
            frame = receiver.get_frame(timeout=0.05)
            if frame is None:
                break
            sink.push(frame)

    finally:
        uplink_stop.set()
        if reporter is not None:
            reporter.stop()
        if uplink_sender_thread is not None:
            uplink_sender_thread.join(timeout=2.0)
        if receiver is not None:
            receiver.stop()
        if sink is not None:
            sink.stop()
        if rtcp_sock is not None:
            rtcp_sock.close()
        if rtp_sock is not None:
            rtp_sock.close()
        if sip_sock is not None:
            sip_sock.close()
        if sip_watcher is not None:
            sip_watcher.join(timeout=1.0)

    logger.info("=== Client 2 done ===")


if __name__ == "__main__":
    run()
