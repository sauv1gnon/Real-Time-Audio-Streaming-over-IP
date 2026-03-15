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
from media.packetizer import AudioFramePacketizer
from media.wav_reader import WavAudioSource
from net.udp import UdpSocketAdapter
from rtp.rtcp import RtcpReporter
from rtp.sender import RtpSender
from sip.sdp import SdpDescription
from sip.session import CallerSession

logger = get_logger("app.client1")


def run() -> None:
    logger.info("=== Client 1 (Caller) starting ===")
    logger.info("  SIP  : %s:%d → %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_SIP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_SIP_PORT)
    logger.info("  RTP  : %s:%d → %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_RTP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_RTP_PORT)
    logger.info("  RTCP : %s:%d → %s:%d", cfg.CLIENT1_IP, cfg.CLIENT1_RTCP_PORT,
                cfg.CLIENT2_IP, cfg.CLIENT2_RTCP_PORT)
    logger.info("  Audio: %s", cfg.SAMPLE_WAV)

    # -----------------------------------------------------------------------
    # Load and validate WAV
    # -----------------------------------------------------------------------
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
        sip_sock.close()
        return

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

    packetizer = AudioFramePacketizer(source)
    try:
        sender.send_frames(packetizer.frame_iterator(), stop_event=stop_event)
    finally:
        reporter.stop()
        rtp_sock.close()
        rtcp_sock.close()

    # -----------------------------------------------------------------------
    # BYE teardown
    # -----------------------------------------------------------------------
    logger.info("Sending BYE…")
    session.send_bye()
    session.receive_bye_ok()
    sip_sock.close()
    logger.info("=== Client 1 done ===")


if __name__ == "__main__":
    run()
