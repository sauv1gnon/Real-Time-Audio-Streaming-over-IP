"""Tests for codec no-op contract."""

from __future__ import annotations

from media.codec import decode_frame, encode_frame


def test_encode_frame_noop_returns_same_bytes():
    frame = b"\x00\x01\x02\x03"

    encoded = encode_frame(frame)

    assert encoded == frame


def test_decode_frame_noop_returns_same_bytes():
    payload = b"\x10\x20\x30\x40"

    decoded = decode_frame(payload)

    assert decoded == payload


def test_encode_decode_round_trip_for_large_payload():
    frame = (b"\xAA\x55" * 8000)

    assert decode_frame(encode_frame(frame)) == frame
