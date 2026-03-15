"""Monotonic-clock helpers for paced RTP sending."""

import time


def monotonic_ms() -> float:
    """Return current monotonic time in milliseconds."""
    return time.monotonic() * 1000.0


def sleep_until(target_ms: float) -> None:
    """Sleep until *target_ms* (monotonic milliseconds), handling overshoot."""
    now = monotonic_ms()
    delta = (target_ms - now) / 1000.0
    if delta > 0:
        time.sleep(delta)
