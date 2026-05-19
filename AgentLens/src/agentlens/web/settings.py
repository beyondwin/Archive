"""Runtime configuration for ``agentlens serve``."""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServeSettings(BaseSettings):
    """Settings for the local read-only dashboard server."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTLENS_SERVE_", extra="ignore", protected_namespaces=()
    )

    host: str = "127.0.0.1"
    port: int = 5757
    demo: bool = False
    debug: bool = False
    auto_port: bool = False
    dev_proxy: str | None = None
    allow_origin: tuple[str, ...] = Field(default_factory=tuple)

    def is_loopback_only(self) -> bool:
        """Return true when the bind host is a loopback-only host."""
        return self.host in _LOOPBACK_HOSTS

    @field_validator("dev_proxy")
    @classmethod
    def _validate_dev_proxy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("dev_proxy must be an http(s) URL")
        if parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("dev_proxy must target a loopback host")
        return value.rstrip("/")


__all__ = ["ServeSettings"]
