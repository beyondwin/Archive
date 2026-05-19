"""--auto-port: pick the first free port among port..port+3."""
from __future__ import annotations

import socket

import pytest

from agentlens.commands.serve import _select_port


def _bound_socket(port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def test_returns_requested_port_when_free():
    assert _select_port(5757, auto=False) == 5757


def test_auto_port_skips_busy():
    s = _bound_socket(50100)
    try:
        assigned = _select_port(50100, auto=True, max_offset=3)
        assert assigned in {50101, 50102, 50103}
    finally:
        s.close()


def test_no_auto_port_raises():
    s = _bound_socket(50200)
    try:
        with pytest.raises(OSError):
            _select_port(50200, auto=False)
    finally:
        s.close()
