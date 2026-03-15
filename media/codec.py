"""Codec adapter placeholder.

Currently the project uses raw 16-bit PCM (L16) as the RTP payload —
no codec transformation is needed.  This module is a hook for future
G.711 (PCMU/PCMA) support.
"""

from __future__ import annotations


def encode_frame(pcm_bytes: bytes) -> bytes:
    """Encode a raw PCM frame for RTP transmission.

    For the baseline L16 codec this is a no-op.
    """
    return pcm_bytes


def decode_frame(payload: bytes) -> bytes:
    """Decode an RTP payload to raw PCM.

    For the baseline L16 codec this is a no-op.
    """
    return payload
