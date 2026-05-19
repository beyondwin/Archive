"""RFC 7807 ProblemDetails error mapping."""
from __future__ import annotations

import logging
import secrets
import traceback
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("agentlens.web")
PROBLEM_MEDIA = "application/problem+json"


def _problem(
    *,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    instance: str | None = None,
    correlation_id: str | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    body = {"type": type_, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    if correlation_id is not None:
        body["correlation_id"] = correlation_id
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA)


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers that produce ``application/problem+json`` responses."""

    def _spa_fallback(request: Request, exc: StarletteHTTPException) -> FileResponse | None:
        path = request.url.path
        if exc.status_code != 404 or request.method not in {"GET", "HEAD"}:
            return None
        if path.startswith(("/api/", "/healthz", "/docs", "/openapi.json", "/assets/")):
            return None
        spa_index = getattr(request.app.state, "spa_index", None)
        if spa_index is None or not spa_index.is_file():
            return None
        return FileResponse(spa_index)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse | FileResponse:
        title = HTTPStatus(exc.status_code).phrase
        return _problem(
            status=exc.status_code,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
            instance=str(request.url.path),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exc(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse | FileResponse:
        fallback = _spa_fallback(request, exc)
        if fallback is not None:
            return fallback
        title = HTTPStatus(exc.status_code).phrase
        return _problem(
            status=exc.status_code,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
            instance=str(request.url.path),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            status=422,
            title="Unprocessable Entity",
            detail="Request validation failed.",
            instance=str(request.url.path),
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = secrets.token_hex(8)
        logger.error(
            "unhandled exception correlation_id=%s path=%s\n%s",
            correlation_id,
            request.url.path,
            traceback.format_exc(),
        )
        detail = str(exc) if getattr(request.app.state.settings, "debug", False) else None
        return _problem(
            status=500,
            title="Internal Server Error",
            detail=detail,
            instance=str(request.url.path),
            correlation_id=correlation_id,
        )


__all__ = ["PROBLEM_MEDIA", "install_error_handlers"]
