"""Client 1 — Caller.

Usage:
    python -m app.main_client1

Environment variables (see app/config.py):
    CLIENT1_IP, CLIENT2_IP, CLIENT1_SIP_PORT, CLIENT2_SIP_PORT, SAMPLE_WAV …
"""

from __future__ import annotations

import threading
from pathlib import Path

from app import config as cfg
from core.log import get_logger
from media.mic_source import MicrophoneAudioSource
from media.wav_reader import WavAudioSource
from media.playback import AudioPlaybackSink
from net.udp import UdpSocketAdapter
from rtp.rtcp import RtcpReporter
from rtp.receiver import RtpReceiver
from rtp.jitter_buffer import JitterBuffer
from rtp.sender import RtpSender
from sip.sdp import SdpDescription
from sip.session import CallerSession, CallerState

logger = get_logger("app.client1")


def run() -> None:
    logger.info("=== Client 1 (Caller) starting ===")
    logger.info("  SIP  : %s:%d -> %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_SIP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_SIP_PORT)
    logger.info("  RTP  : %s:%d -> %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_RTP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_RTP_PORT)
    logger.info("  RTCP : %s:%d -> %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_RTCP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_RTCP_PORT)
    logger.info("  Audio source: %s", cfg.AUDIO_SOURCE)
    if cfg.AUDIO_SOURCE == "wav":
        logger.info("  Audio file: %s", cfg.SAMPLE_WAV)
    else:
        logger.info("  Mic duration: %.1f s", cfg.MIC_DURATION_S)
    logger.info("  Two-way mode: %s", cfg.TWO_WAY_CALL)
    logger.info("  RTP packet loss (sender): %.2f", cfg.PACKET_LOSS)

    # -----------------------------------------------------------------------
    # Build local audio source (WAV or microphone)
    # -----------------------------------------------------------------------
    if cfg.AUDIO_SOURCE == "mic":
        source = MicrophoneAudioSource(
            sample_rate=cfg.SAMPLE_RATE,
            channels=cfg.CHANNELS,
            frame_duration_ms=cfg.FRAME_DURATION_MS,
            duration_s=cfg.MIC_DURATION_S,
        )
    else:
        wav_path = Path(cfg.SAMPLE_WAV)
        source = WavAudioSource(wav_path, frame_duration_ms=cfg.FRAME_DURATION_MS)
    source.open()

    # -----------------------------------------------------------------------
    # Build caller SDP offer
    # -----------------------------------------------------------------------
    offer_sdp = SdpDescription(
        unicast_addr=cfg.CLIENT1_IP,
        media_ip=cfg.CLIENT1_IP,
        rtp_port=cfg.CLIENT1_RTP_PORT,
        payload_type=cfg.PAYLOAD_TYPE,
        codec_name="L16",
        clock_rate=cfg.SAMPLE_RATE,
    )

    # -----------------------------------------------------------------------
    # SIP handshake
    # -----------------------------------------------------------------------
    sip_sock: UdpSocketAdapter | None = None
    rtp_sock: UdpSocketAdapter | None = None
    rtcp_sock: UdpSocketAdapter | None = None
    reporter: RtcpReporter | None = None
    receiver: RtpReceiver | None = None
    playback_sink: AudioPlaybackSink | None = None
    playback_pump_thread: threading.Thread | None = None
    playback_pump_stop = threading.Event()
    session: CallerSession | None = None
    call_established = False

    try:
        sip_sock = UdpSocketAdapter(cfg.CLIENT1_IP, cfg.CLIENT1_SIP_PORT, timeout=cfg.SIP_TIMEOUT_S)
        sip_sock.open()
        session = CallerSession(
            sock=sip_sock,
            local_ip=cfg.CLIENT1_IP,
            local_sip_port=cfg.CLIENT1_SIP_PORT,
            remote_ip=cfg.CLIENT2_IP,
            remote_sip_port=cfg.CLIENT2_SIP_PORT,
            local_sdp=offer_sdp,
        )

        session.send_invite()
        if not session.receive_200_ok():
            logger.error("SIP handshake failed — aborting")
            return
        call_established = True

        # Determine the remote RTP endpoint from the SDP answer
        rtp_dest_ip = cfg.CLIENT2_IP
        rtp_dest_port = cfg.CLIENT2_RTP_PORT
        if session.remote_sdp is not None:
            rtp_dest_ip = session.remote_sdp.media_ip
            rtp_dest_port = session.remote_sdp.rtp_port

        logger.info("Call established — streaming to %s:%d", rtp_dest_ip, rtp_dest_port)

        # -----------------------------------------------------------------------
        # RTP sender + RTCP reporter
        # -----------------------------------------------------------------------
        rtp_sock = UdpSocketAdapter(cfg.CLIENT1_IP, cfg.CLIENT1_RTP_PORT)
        rtp_sock.open()
        rtcp_sock = UdpSocketAdapter(cfg.CLIENT1_IP, cfg.CLIENT1_RTCP_PORT)
        rtcp_sock.open()

        sender = RtpSender(
            sock=rtp_sock,
            remote_ip=rtp_dest_ip,
            remote_port=rtp_dest_port,
            payload_type=cfg.PAYLOAD_TYPE,
            samples_per_frame=source.samples_per_frame,
            frame_duration_ms=cfg.FRAME_DURATION_MS,
            packet_loss=cfg.PACKET_LOSS,
        )

        stop_event = threading.Event()

        reporter = RtcpReporter(
            sock=rtcp_sock,
            remote_ip=rtp_dest_ip,
            remote_port=rtp_dest_port + 1,  # RTCP = RTP + 1
            ssrc=sender.ssrc,
            interval_s=cfg.RTCP_INTERVAL_S,
            get_stats=sender.get_stats_snapshot,
        )
        reporter.start()

        if cfg.TWO_WAY_CALL:
            playback_sink = AudioPlaybackSink(
                sample_rate=cfg.SAMPLE_RATE,
                channels=cfg.CHANNELS,
                sample_width=cfg.SAMPLE_WIDTH,
                output_path=cfg.OUTPUT_WAV_CALLER,
                enable_live_playback=cfg.LIVE_PLAYBACK,
            )
            receiver = RtpReceiver(
                sock=rtp_sock,
                payload_type=cfg.PAYLOAD_TYPE,
                jitter_buffer=JitterBuffer(max_depth=5),
            )
            playback_sink.start()
            receiver.start()

            def _playback_pump() -> None:
                while not playback_pump_stop.is_set():
                    frame = receiver.get_frame(timeout=0.2)
                    if frame is not None:
                        playback_sink.push(frame)

            playback_pump_thread = threading.Thread(
                target=_playback_pump, daemon=True, name="caller-playback-pump"
            )
            playback_pump_thread.start()

        sender.send_frames(source.frames(), stop_event=stop_event)

    finally:
        if call_established and session is not None and session.state == CallerState.ESTABLISHED:
            try:
                logger.info("Sending BYE…")
                session.send_bye()
                session.receive_bye_ok()
            except Exception as exc:
                logger.warning("BYE teardown failed: %s", exc)

        if reporter is not None:
            try:
                reporter.stop()
            except Exception as exc:
                logger.warning("Failed to stop RTCP reporter cleanly: %s", exc)
        playback_pump_stop.set()
        if playback_pump_thread is not None:
            playback_pump_thread.join(timeout=1.0)
        if receiver is not None:
            try:
                receiver.stop()
            except Exception as exc:
                logger.warning("Failed to stop RTP receiver cleanly: %s", exc)
        if playback_sink is not None:
            try:
                playback_sink.stop()
            except Exception as exc:
                logger.warning("Failed to stop playback sink cleanly: %s", exc)

        if rtp_sock is not None:
            rtp_sock.close()
        if rtcp_sock is not None:
            rtcp_sock.close()
        if sip_sock is not None:
            sip_sock.close()

    logger.info("=== Client 1 done ===")


if __name__ == "__main__":
    run()
