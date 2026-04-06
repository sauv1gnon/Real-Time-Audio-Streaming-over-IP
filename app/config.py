"""Shared configuration for both clients.

Override defaults by setting environment variables or editing this file.
"""

from __future__ import annotations

import math
import os


def _env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
	raw = os.getenv(name)
	if raw is None or raw.strip() == "":
		return default
	try:
		value = int(raw)
	except ValueError as exc:
		raise ValueError(f"Invalid integer value for {name}: {raw!r}") from exc
	if min_value is not None and value < min_value:
		raise ValueError(f"{name} must be >= {min_value}, got {value}")
	if max_value is not None and value > max_value:
		raise ValueError(f"{name} must be <= {max_value}, got {value}")
	return value


def _env_float(
	name: str,
	default: float,
	min_value: float | None = None,
	max_value: float | None = None,
) -> float:
	raw = os.getenv(name)
	if raw is None or raw.strip() == "":
		return default
	try:
		value = float(raw)
	except ValueError as exc:
		raise ValueError(f"Invalid float value for {name}: {raw!r}") from exc
	if not math.isfinite(value):
		raise ValueError(f"{name} must be finite, got {value!r}")
	if min_value is not None and value < min_value:
		raise ValueError(f"{name} must be >= {min_value}, got {value}")
	if max_value is not None and value > max_value:
		raise ValueError(f"{name} must be <= {max_value}, got {value}")
	return value


def _env_bool(name: str, default: bool = False) -> bool:
	raw = os.getenv(name)
	if raw is None or raw.strip() == "":
		return default
	return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

# ---------------------------------------------------------------------------
# IP addressing (LAN or localhost)
# ---------------------------------------------------------------------------

CLIENT1_IP: str = os.getenv("CLIENT1_IP", "127.0.0.1")
CLIENT2_IP: str = os.getenv("CLIENT2_IP", "127.0.0.1")

# ---------------------------------------------------------------------------
# SIP ports
# ---------------------------------------------------------------------------

CLIENT1_SIP_PORT: int = _env_int("CLIENT1_SIP_PORT", 5060, min_value=1, max_value=65535)
CLIENT2_SIP_PORT: int = _env_int("CLIENT2_SIP_PORT", 5061, min_value=1, max_value=65535)

# ---------------------------------------------------------------------------
# RTP / RTCP ports (Client 1 sends, Client 2 receives)
# ---------------------------------------------------------------------------

CLIENT1_RTP_PORT: int = _env_int("CLIENT1_RTP_PORT", 10000, min_value=1, max_value=65534)
CLIENT2_RTP_PORT: int = _env_int("CLIENT2_RTP_PORT", 10002, min_value=1, max_value=65534)

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

RTCP_INTERVAL_S: float = _env_float("RTCP_INTERVAL_S", 5.0, min_value=0.1)

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

SAMPLE_WAV: str = os.getenv("SAMPLE_WAV", "assets/sample.wav")
OUTPUT_WAV: str = os.getenv("OUTPUT_WAV", "received_audio.wav")
OUTPUT_WAV_CALLER: str = os.getenv("OUTPUT_WAV_CALLER", "received_audio_client1.wav")

# Audio source:
#   wav = use SAMPLE_WAV
#   mic = use microphone capture (bonus)
AUDIO_SOURCE: str = os.getenv("AUDIO_SOURCE", "wav").strip().lower()
if AUDIO_SOURCE not in {"wav", "mic"}:
	raise ValueError(f"AUDIO_SOURCE must be 'wav' or 'mic', got {AUDIO_SOURCE!r}")

# Bonus mode controls
MIC_DURATION_S: float = _env_float("MIC_DURATION_S", 5.0, min_value=0.2)
TWO_WAY_CALL: bool = _env_bool("TWO_WAY_CALL", False)
# Keep false by default for stable demo runs on systems where native
# sounddevice playback can crash in high-rate two-way mode.
LIVE_PLAYBACK: bool = _env_bool("LIVE_PLAYBACK", False)

# ---------------------------------------------------------------------------
# SIP socket timeout (seconds)
# ---------------------------------------------------------------------------

SIP_TIMEOUT_S: float = _env_float("SIP_TIMEOUT_S", 10.0, min_value=0.1)
