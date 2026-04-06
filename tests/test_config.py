"""Tests for environment-driven app configuration parsing."""

from __future__ import annotations

import importlib
import os

import pytest


def _reload_config_module(*, clear_env_file: bool = True):
    if clear_env_file:
        os.environ.pop("ENV_FILE", None)
    import app.config as cfg

    return importlib.reload(cfg)


def test_invalid_client1_sip_port_raises_value_error(monkeypatch):
    monkeypatch.setenv("CLIENT1_SIP_PORT", "not-a-port")

    with pytest.raises(ValueError, match="CLIENT1_SIP_PORT"):
        _reload_config_module()


def test_invalid_sip_timeout_raises_value_error(monkeypatch):
    monkeypatch.setenv("SIP_TIMEOUT_S", "inf")

    with pytest.raises(ValueError, match="SIP_TIMEOUT_S"):
        _reload_config_module()


def test_rtp_port_must_allow_rtcp_pair(monkeypatch):
    monkeypatch.setenv("CLIENT1_RTP_PORT", "65535")

    with pytest.raises(ValueError, match="CLIENT1_RTP_PORT"):
        _reload_config_module()


def test_blank_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("CLIENT1_SIP_PORT", " ")
    monkeypatch.setenv("RTCP_INTERVAL_S", "")

    cfg = _reload_config_module()

    assert cfg.CLIENT1_SIP_PORT == 5060
    assert cfg.RTCP_INTERVAL_S == 5.0


def test_env_file_overrides_existing_process_env(monkeypatch, tmp_path):
    profile = tmp_path / "profile.env"
    profile.write_text("CLIENT1_SIP_PORT=6060\n", encoding="utf-8")

    monkeypatch.setenv("CLIENT1_SIP_PORT", "9999")
    monkeypatch.setenv("ENV_FILE", str(profile))

    cfg = _reload_config_module(clear_env_file=False)

    assert cfg.CLIENT1_SIP_PORT == 6060
