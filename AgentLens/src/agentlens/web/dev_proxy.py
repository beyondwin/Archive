"""Reverse-proxy mount for a Vite dev server."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


def mount_dev_proxy(app: FastAPI, target: str) -> None:
    """Mount a catch-all route that proxies non-API requests to ``target``."""
    client = httpx.AsyncClient(base_url=target.rstrip("/"), timeout=30.0)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def _proxy(path: str, request: Request) -> Response:
        if path.startswith(("api/v1", "healthz", "docs", "openapi.json")):
            raise HTTPException(status_code=404, detail=f"route not found: /{path}")
        upstream = await client.request(
            request.method,
            "/" + path,
            params=dict(request.query_params),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                k: v
                for k, v in upstream.headers.items()
                if k.lower() != "transfer-encoding"
            },
        )


__all__ = ["mount_dev_proxy"]
