"""Tests for agentlens.web.settings.ServeSettings."""
from __future__ import annotations

import pytest

from agentlens.web.settings import ServeSettings


def test_defaults():
    s = ServeSettings()
    assert s.host == "127.0.0.1"
    assert s.port == 5757
    assert s.demo is False
    assert s.debug is False
    assert s.auto_port is False
    assert s.dev_proxy is None
    assert s.allow_origin == ()


def test_explicit_values():
    s = ServeSettings(host="0.0.0.0", port=9000, demo=True, debug=True)
    assert s.host == "0.0.0.0"
    assert s.port == 9000
    assert s.demo is True
    assert s.debug is True


def test_is_loopback_only():
    assert ServeSettings(host="127.0.0.1").is_loopback_only() is True
    assert ServeSettings(host="localhost").is_loopback_only() is True
    assert ServeSettings(host="::1").is_loopback_only() is True
    assert ServeSettings(host="0.0.0.0").is_loopback_only() is False
    assert ServeSettings(host="192.168.1.10").is_loopback_only() is False


def test_dev_proxy_validates_loopback_only():
    with pytest.raises(ValueError, match="loopback"):
        ServeSettings(dev_proxy="http://example.com:5173")
    s = ServeSettings(dev_proxy="http://127.0.0.1:5173")
    assert s.dev_proxy == "http://127.0.0.1:5173"
