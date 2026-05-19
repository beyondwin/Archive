"""Common response middleware."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CommonHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security/cache headers and the non-loopback warning header."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")

        settings = request.app.state.settings
        if not settings.is_loopback_only():
            response.headers["X-AgentLens-Warning"] = "bound-to-non-loopback"
        return response


__all__ = ["CommonHeadersMiddleware"]
