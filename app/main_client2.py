"""Client 2 — Callee / receiver.

Usage:
    python -m app.main_client2

Environment variables (see app/config.py):
    CLIENT1_IP, CLIENT2_IP, CLIENT2_SIP_PORT, CLIENT2_RTP_PORT, OUTPUT_WAV …
"""

from __future__ import annotations

import threading
from pathlib import Path

from app import config as cfg
from core.log import get_logger
from media.playback import AudioPlaybackSink
from net.udp import UdpSocketAdapter
from rtp.jitter_buffer import JitterBuffer
from rtp.receiver import RtpReceiver
from sip.sdp import SdpDescription
from sip.session import CalleeSession

logger = get_logger("app.client2")


def run() -> None:
    logger.info("=== Client 2 (Callee) starting ===")
    logger.info("  SIP  : listening on %s:%d", cfg.CLIENT2_IP, cfg.CLIENT2_SIP_PORT)
    logger.info("  RTP  : listening on %s:%d", cfg.CLIENT2_IP, cfg.CLIENT2_RTP_PORT)
    logger.info("  Output WAV: %s", cfg.OUTPUT_WAV)

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

        if not session.wait_for_invite():
            logger.error("No INVITE received — exiting")
            return

        session.send_200_ok()
        if not session.wait_for_ack():
            logger.error("No ACK received — exiting")
            return

        # Determine the sender's RTP endpoint from the SDP offer
        rtp_src_ip = cfg.CLIENT1_IP
        if session.remote_sdp is not None:
            rtp_src_ip = session.remote_sdp.media_ip

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
        )
        sink.start()
        receiver.start()

        # -----------------------------------------------------------------------
        # Wait for BYE while forwarding received frames to the playback sink
        # -----------------------------------------------------------------------
        def _sip_bye_watcher() -> None:
            try:
                session.wait_for_bye()
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
        if receiver is not None:
            receiver.stop()
        if sink is not None:
            sink.stop()
        if rtp_sock is not None:
            rtp_sock.close()
        if sip_sock is not None:
            sip_sock.close()
        if sip_watcher is not None:
            sip_watcher.join(timeout=1.0)

    logger.info("=== Client 2 done ===")


if __name__ == "__main__":
    run()
