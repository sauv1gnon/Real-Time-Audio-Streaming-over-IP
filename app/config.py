"""Shared configuration for both clients.

Override defaults by setting environment variables or editing this file.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# IP addressing (LAN or localhost)
# ---------------------------------------------------------------------------

CLIENT1_IP: str = os.getenv("CLIENT1_IP", "127.0.0.1")
CLIENT2_IP: str = os.getenv("CLIENT2_IP", "127.0.0.1")

# ---------------------------------------------------------------------------
# SIP ports
# ---------------------------------------------------------------------------

CLIENT1_SIP_PORT: int = int(os.getenv("CLIENT1_SIP_PORT", "5060"))
CLIENT2_SIP_PORT: int = int(os.getenv("CLIENT2_SIP_PORT", "5061"))

# ---------------------------------------------------------------------------
# RTP / RTCP ports (Client 1 sends, Client 2 receives)
# ---------------------------------------------------------------------------

CLIENT1_RTP_PORT: int = int(os.getenv("CLIENT1_RTP_PORT", "10000"))
CLIENT2_RTP_PORT: int = int(os.getenv("CLIENT2_RTP_PORT", "10002"))

# RTCP is conventionally on RTP port + 1
CLIENT1_RTCP_PORT: int = CLIENT1_RTP_PORT + 1
CLIENT2_RTCP_PORT: int = CLIENT2_RTP_PORT + 1

# ---------------------------------------------------------------------------
# Audio / RTP parameters
# ---------------------------------------------------------------------------

SAMPLE_RATE: int = 8000
CHANNELS: int = 1
SAMPLE_WIDTH: int = 2             # bytes (16-bit PCM)
FRAME_DURATION_MS: float = 20.0
PAYLOAD_TYPE: int = 96            # dynamic PT for L16

# ---------------------------------------------------------------------------
# RTCP interval
# ---------------------------------------------------------------------------

RTCP_INTERVAL_S: float = float(os.getenv("RTCP_INTERVAL_S", "5"))

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

SAMPLE_WAV: str = os.getenv("SAMPLE_WAV", "assets/sample.wav")
OUTPUT_WAV: str = os.getenv("OUTPUT_WAV", "received_audio.wav")

# ---------------------------------------------------------------------------
# SIP socket timeout (seconds)
# ---------------------------------------------------------------------------

SIP_TIMEOUT_S: float = float(os.getenv("SIP_TIMEOUT_S", "10"))
