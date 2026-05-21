"""Tests for the agentlens.commands.serve Typer command."""
from __future__ import annotations

from typer.testing import CliRunner

from agentlens.cli import app


def test_serve_help_lists_options():
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    for token in (
        "--host",
        "--port",
        "--demo",
        "--debug",
        "--auto-port",
        "--dev-proxy",
        "--allow-origin",
    ):
        assert token in result.stdout


def test_serve_env_port_reaches_uvicorn_when_cli_flag_absent(monkeypatch):
    captured = {}

    def fake_run(app_obj, *, host, port, log_level):
        captured.update({"app": app_obj, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr("agentlens.commands.serve.uvicorn.run", fake_run)
    monkeypatch.setattr("agentlens.commands.serve._select_port", lambda port, *, auto: port)

    result = CliRunner().invoke(
        app,
        ["serve"],
        env={"AGENTLENS_SERVE_PORT": "9999", "AGENTLENS_SERVE_HOST": "127.0.0.1"},
    )

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999


def test_serve_cli_flags_override_env(monkeypatch):
    captured = {}

    def fake_run(app_obj, *, host, port, log_level):
        captured.update({"app": app_obj, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr("agentlens.commands.serve.uvicorn.run", fake_run)
    monkeypatch.setattr("agentlens.commands.serve._select_port", lambda port, *, auto: port)

    result = CliRunner().invoke(
        app,
        ["serve", "--port", "8888"],
        env={"AGENTLENS_SERVE_PORT": "9999"},
    )

    assert result.exit_code == 0
    assert captured["port"] == 8888
