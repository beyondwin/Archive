"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from agentlens.web.errors import install_error_handlers
from agentlens.web.middleware import CommonHeadersMiddleware
from agentlens.web.routers import doctor as doctor_router
from agentlens.web.routers import failures as failures_router
from agentlens.web.routers import meta as meta_router
from agentlens.web.routers import runs as runs_router
from agentlens.web.routers import workspaces as workspaces_router
from agentlens.web.settings import ServeSettings


def create_app(settings: ServeSettings | None = None) -> FastAPI:
    """Construct a fresh AgentLens web app."""
    settings = settings or ServeSettings()
    app = FastAPI(
        title="AgentLens",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    install_error_handlers(app)

    if settings.allow_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allow_origin),
            allow_methods=["GET", "HEAD", "OPTIONS"],
            allow_headers=["*"],
        )
    app.add_middleware(CommonHeadersMiddleware)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.include_router(meta_router.router)
    app.include_router(runs_router.router)
    app.include_router(workspaces_router.router)
    app.include_router(failures_router.router)
    app.include_router(doctor_router.router)

    if settings.dev_proxy:
        from agentlens.web.dev_proxy import mount_dev_proxy

        mount_dev_proxy(app, settings.dev_proxy)
    else:
        from importlib.resources import as_file, files

        from fastapi.staticfiles import StaticFiles

        pkg = files("agentlens.web_assets")
        with as_file(pkg) as path:
            index_html = path / "index.html"
            if index_html.is_file():
                app.state.spa_index = index_html
                app.mount(
                    "/assets",
                    StaticFiles(directory=str(path / "assets"), html=True, check_dir=False),
                    name="web_assets",
                )

                @app.get("/", include_in_schema=False)
                def serve_spa() -> FileResponse:
                    return FileResponse(index_html)
            else:

                @app.get("/", include_in_schema=False)
                def missing_spa() -> JSONResponse:
                    return JSONResponse(
                        {
                            "title": "SPA not built",
                            "detail": "Run `npm --prefix web run build` or use --dev-proxy.",
                        },
                        status_code=503,
                        media_type="application/problem+json",
                    )

    return app


__all__ = ["create_app"]
