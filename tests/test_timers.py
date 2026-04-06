"""Tests for monotonic timing helpers."""

from __future__ import annotations

import core.timers as timers


def test_monotonic_ms_increases_over_time():
    first = timers.monotonic_ms()
    second = timers.monotonic_ms()

    assert second >= first


def test_sleep_until_future_calls_sleep(monkeypatch):
    recorded: list[float] = []

    monkeypatch.setattr(timers, "monotonic_ms", lambda: 1000.0)
    monkeypatch.setattr(timers.time, "sleep", lambda delta: recorded.append(delta))

    timers.sleep_until(1200.0)

    assert len(recorded) == 1
    assert 0.19 <= recorded[0] <= 0.21


def test_sleep_until_past_does_not_sleep(monkeypatch):
    recorded: list[float] = []

    monkeypatch.setattr(timers, "monotonic_ms", lambda: 1000.0)
    monkeypatch.setattr(timers.time, "sleep", lambda delta: recorded.append(delta))

    timers.sleep_until(900.0)

    assert recorded == []
