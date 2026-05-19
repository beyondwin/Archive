# AgentLens Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AgentLens read-only web viewer (`agentlens serve`) as specified in `AgentLens/docs/spec/2026-05-19-agentlens-dashboard-design.md`. The viewer surfaces runs, failures, risks, transcripts, and the agent-outcome ↔ evaluator-status discrepancy through a single FastAPI process that serves an embedded React SPA on `localhost:5757`.

**Architecture:** Reuse the existing `agentlens.store.query` read facade as the sole source of truth. Backend = FastAPI behind `agentlens serve` (a new Typer subcommand). Frontend = Vite-built React SPA whose build artifact is embedded into the Python wheel under `src/agentlens/web_assets/`. Identical JSON shapes between API and CLI `--format json` (driven by `tests/fixtures/format_snapshots/*.json` as joint contract truth).

**Tech Stack:**
- **Backend:** FastAPI, uvicorn, pydantic-settings, Python 3.11+. Existing deps: typer, jsonschema, pyyaml.
- **Frontend:** React 19, Vite, TypeScript 5, Tailwind CSS 3, Radix UI primitives (shadcn-style components copied into repo), TanStack Query v5, React Router v6, lucide-react, zod.
- **Tests:** pytest (backend), Vitest + MSW (frontend), Playwright (e2e smoke).
- **Packaging:** setuptools wheel including `web_assets/` via `package-data`.

**Milestones:**
- M0 Project skeleton (Tasks 1–3)
- M1 Common infrastructure (Tasks 4–6)
- M2 Read API routers (Tasks 7–14)
- M3 Demo data + edge cases (Tasks 15–18)
- M4 Frontend scaffold (Tasks 19–22)
- M5 Frontend pages (Tasks 23–28)
- M6 Frontend tests (Tasks 29–31)
- M7 Packaging + CI + docs (Tasks 32–34)

---

## Deep Review Update (2026-05-19)

This plan is still the right implementation direction, but the review found several contract mismatches that would make a literal task-by-task execution fail or publish the wrong API. The corrections below are binding: when a later task conflicts with this section, this section wins.

### P0 corrections before implementation

1. **Manifest API shape.** Current `manifest.schema.json` exposes `files:[{path, sha256}]`; it does not expose `artifacts`, `manifest_sha256`, `integrity`, `size`, or `kind`. Implement `/verify` with `agentlens.store.manifest.verify(run_dir)`, and expose `manifest_seal.manifest_digest` only as a server-computed sha256 of the `manifest.json` bytes.
2. **Fixture copy semantics.** `tests/fixtures/*_run/` directory names are fixture labels, not run IDs. Any test/demo setup that copies a fixture under `runs/<ws>/<fixture_name>` is wrong for routes that use `run_id`. Read `run.json`, then copy to `runs/<workspace_id>/<run_id>/`.
3. **Run schema version detection.** Detect `agentlens.run.v1` from the `schema` field. Do not test or implement `schema_version` inside `run.json`.
4. **API projection boundary.** Do not return raw `store.query.get_run()` dictionaries. Use `project_run_row`, `project_failure`, `project_risk`, and a shared show/detail projector so API and CLI JSON contracts stay aligned.
5. **`web_assets` packaging.** Create `src/agentlens/web_assets/__init__.py`; a `.gitkeep` directory is not importable through `importlib.resources.files("agentlens.web_assets")`.
6. **Doctor collector.** Preserve the existing CLI signature: `doctor(scope="all", fmt="text")`. Extract `collect_doctor_report(scope: str = "all")`, and add `warnings: []` in the shared report or a web-specific wrapper without breaking current JSON tests.
7. **CORS flag.** `--allow-origin` is currently only parsed in the plan. Add `CORSMiddleware` when the tuple is non-empty, and test both "absent by default" and "explicit origin allowed".
8. **License gate.** Do not silently change `license = { text = "Proprietary" }` to MIT unless the owner confirms public licensing and a matching `LICENSE` file is added.

### Shared fixture helper required for API tests and demo data

Use this helper pattern in each affected test file, or put it in a shared test helper imported by Tasks 8-17 and Task 31, instead of copying fixture directories by their fixture label:

```python
import json
import shutil
from pathlib import Path


def copy_fixture_as_run_id(fixtures: Path, fixture_name: str, runs_root: Path) -> tuple[str, str]:
    src = fixtures / fixture_name
    run_doc = json.loads((src / "run.json").read_text(encoding="utf-8"))
    run_id = run_doc["run_id"]
    workspace_id = run_doc["workspace_id"]
    workspace_dir = runs_root / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    dest = workspace_dir / run_id
    shutil.copytree(src, dest)
    return workspace_id, run_id
```

For demo data, preserve the same invariant:

```bash
cd AgentLens
for fixture in minimal_run failed_command_run residual_risk_run missing_final_run corrupt_manifest_run; do
  run_id=$(.venv/bin/python -c 'import json, pathlib, sys; print(json.loads((pathlib.Path("tests/fixtures")/sys.argv[1]/"run.json").read_text())["run_id"])' "$fixture")
  workspace_id=$(.venv/bin/python -c 'import json, pathlib, sys; print(json.loads((pathlib.Path("tests/fixtures")/sys.argv[1]/"run.json").read_text())["workspace_id"])' "$fixture")
  mkdir -p "src/agentlens/demo_data/runs/$workspace_id"
  cp -R "tests/fixtures/$fixture" "src/agentlens/demo_data/runs/$workspace_id/$run_id"
done
find src/agentlens/demo_data -name expected_eval.json -delete
```

### API implementation overrides

- Extend `store.query.list_runs` or filter in the web adapter for `agent` (`agent_name`) and `since_days`; current `list_runs` only understands `workspace_id`, `agent_outcome`, and `eval_status`.
- Keep `/api/v1/runs` `since_days` optional; the default list must show all runs so bundled demo fixtures and older local runs are not hidden on first launch.
- Sort run lists by `started_at` descending before pagination, so cursor pages are stable and the default list shows newest first.
- Apply projectors before returning: `project_run_row` for `/runs` and workspace `recent_runs`, `project_failure` for failures, `project_risk` for risks.
- For `X-AgentLens-Index: fallback`, either add explicit fallback metadata to the query facade or defer the header. Do not emit it just because a response came from `list_runs`.
- For artifact download, locate a manifest entry whose `sha256` matches and whose `path` starts with `artifacts/`; read `run_dir / path`. Do not construct `run_dir / "artifacts" / sha256`.
- Remove `--open` from docs unless the serve command actually implements it.

---

## M0 — Project Skeleton

### Task 1: Add web backend dependencies and scaffold the `web/` Python package

**Files:**
- Modify: `AgentLens/pyproject.toml`
- Create: `AgentLens/src/agentlens/web/__init__.py`
- Create: `AgentLens/src/agentlens/web/routers/__init__.py`
- Create: `AgentLens/src/agentlens/demo_data/.gitkeep`
- Create: `AgentLens/src/agentlens/web_assets/__init__.py`

- [ ] **Step 1: Write the failing test for new dependencies**

Create `AgentLens/tests/unit/test_web_imports.py`:

```python
"""Smoke test: web backend modules import without error."""
from __future__ import annotations


def test_web_package_importable():
    import agentlens.web  # noqa: F401


def test_fastapi_installed():
    import fastapi  # noqa: F401


def test_uvicorn_installed():
    import uvicorn  # noqa: F401


def test_pydantic_settings_installed():
    import pydantic_settings  # noqa: F401
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_web_imports.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.web'` (and/or `fastapi`).

- [ ] **Step 3: Update pyproject.toml dependencies**

Replace the `dependencies = [...]` block in `AgentLens/pyproject.toml`:

```toml
dependencies = [
    "jsonschema>=4",
    "typer",
    "pyyaml",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic-settings>=2.2",
]
```

- [ ] **Step 4: Create empty `agentlens.web` package**

`AgentLens/src/agentlens/web/__init__.py`:

```python
"""AgentLens web viewer (spec: docs/spec/2026-05-19-agentlens-dashboard-design.md).

Read-only HTTP layer over ``agentlens.store.query``. Public surface:
:func:`agentlens.web.app.create_app` and the Typer command
``agentlens.commands.serve.serve``.
"""
```

`AgentLens/src/agentlens/web/routers/__init__.py`:

```python
"""FastAPI routers grouped by resource (runs, workspaces, failures, doctor, meta)."""
```

`AgentLens/src/agentlens/demo_data/.gitkeep` — empty file (the curated fixture set is populated in Task 15).

`AgentLens/src/agentlens/web_assets/__init__.py`:

```python
"""Built dashboard SPA assets packaged with AgentLens."""
```

- [ ] **Step 5: Install dependencies and verify the test passes**

```bash
cd AgentLens && uv pip install -e . pytest && .venv/bin/python -m pytest tests/unit/test_web_imports.py -v
```
Expected: PASS for all 4 tests.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/pyproject.toml AgentLens/src/agentlens/web/ AgentLens/src/agentlens/demo_data/.gitkeep AgentLens/src/agentlens/web_assets/__init__.py AgentLens/tests/unit/test_web_imports.py
git commit -m "feat(agentlens-dashboard): add fastapi/uvicorn deps and scaffold web package"
```

---

### Task 2: Implement `web/settings.py` with pydantic-settings

**Files:**
- Create: `AgentLens/src/agentlens/web/settings.py`
- Create: `AgentLens/tests/unit/test_web_settings.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/unit/test_web_settings.py`:

```python
"""Tests for agentlens.web.settings.ServeSettings."""
from __future__ import annotations

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
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        ServeSettings(dev_proxy="http://example.com:5173")
    # 127.0.0.1 is fine
    s = ServeSettings(dev_proxy="http://127.0.0.1:5173")
    assert s.dev_proxy == "http://127.0.0.1:5173"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_web_settings.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'agentlens.web.settings'`.

- [ ] **Step 3: Implement settings**

`AgentLens/src/agentlens/web/settings.py`:

```python
"""Runtime configuration for ``agentlens serve``.

Backed by pydantic-settings so values can be passed via CLI flags
(``--port``, ``--host``), env vars (``AGENTLENS_SERVE_PORT`` etc.),
or kwargs to :class:`ServeSettings`.
"""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServeSettings(BaseSettings):
    """Settings consumed by the FastAPI app factory and CLI."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTLENS_SERVE_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 5757
    demo: bool = False
    debug: bool = False
    auto_port: bool = False
    dev_proxy: str | None = None
    allow_origin: tuple[str, ...] = ()

    @field_validator("dev_proxy")
    @classmethod
    def _validate_dev_proxy_loopback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        host = parsed.hostname or ""
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"--dev-proxy must point at a loopback host (got {host!r}); "
                "allowed: 127.0.0.1, localhost, ::1"
            )
        return value

    def is_loopback_only(self) -> bool:
        return self.host in _LOOPBACK_HOSTS


__all__ = ["ServeSettings"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_web_settings.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/settings.py AgentLens/tests/unit/test_web_settings.py
git commit -m "feat(agentlens-dashboard): add ServeSettings (host/port/demo/debug/auto_port/dev_proxy/allow_origin)"
```

---

### Task 3: FastAPI app factory + `/healthz` + Typer `serve` subcommand

**Files:**
- Create: `AgentLens/src/agentlens/web/app.py`
- Create: `AgentLens/src/agentlens/commands/serve.py`
- Modify: `AgentLens/src/agentlens/cli.py` (register serve)
- Create: `AgentLens/tests/integration/test_web_e2e_healthz.py`
- Create: `AgentLens/tests/unit/test_web_serve_command.py`

- [ ] **Step 1: Write failing integration test for `/healthz`**

`AgentLens/tests/integration/test_web_e2e_healthz.py`:

```python
"""Boot the FastAPI app via TestClient and hit /healthz."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_healthz_returns_ok():
    app = create_app(ServeSettings())
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Write failing unit test for the Typer command**

`AgentLens/tests/unit/test_web_serve_command.py`:

```python
"""Tests for the agentlens.commands.serve Typer command."""
from __future__ import annotations

from typer.testing import CliRunner

from agentlens.cli import app


def test_serve_help_lists_options():
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    for token in ("--host", "--port", "--demo", "--debug", "--auto-port", "--dev-proxy"):
        assert token in result.stdout
```

- [ ] **Step 3: Run to verify both fail**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_healthz.py tests/unit/test_web_serve_command.py -v
```
Expected: FAIL — `cannot import name 'create_app'` and `serve` not in CLI.

- [ ] **Step 4: Implement the app factory**

`AgentLens/src/agentlens/web/app.py`:

```python
"""FastAPI application factory (spec §4, §6)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agentlens.web.settings import ServeSettings


def create_app(settings: ServeSettings | None = None) -> FastAPI:
    """Construct the FastAPI app. Each call returns a fresh instance."""
    settings = settings or ServeSettings()
    app = FastAPI(
        title="AgentLens",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app


__all__ = ["create_app"]
```

- [ ] **Step 5: Implement the serve command**

`AgentLens/src/agentlens/commands/serve.py`:

```python
"""``agentlens serve`` — boot the dashboard (spec §4, §9)."""
from __future__ import annotations

import sys

import typer
import uvicorn

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host (default: loopback)."),
    port: int = typer.Option(5757, "--port", help="TCP port (default: 5757)."),
    demo: bool = typer.Option(False, "--demo", help="Load bundled demo data into a temp HOME."),
    debug: bool = typer.Option(False, "--debug", help="Expose tracebacks in error responses."),
    auto_port: bool = typer.Option(False, "--auto-port", help="If port is in use, try port+1, +2, +3."),
    dev_proxy: str | None = typer.Option(
        None, "--dev-proxy", help="Reverse-proxy static assets to this URL (loopback only; dev only)."
    ),
    allow_origin: list[str] = typer.Option(
        [], "--allow-origin", help="Add a CORS Access-Control-Allow-Origin entry (repeatable)."
    ),
) -> None:
    """Spawn the AgentLens web viewer on the chosen host:port."""
    settings = ServeSettings(
        host=host,
        port=port,
        demo=demo,
        debug=debug,
        auto_port=auto_port,
        dev_proxy=dev_proxy,
        allow_origin=tuple(allow_origin),
    )

    if not settings.is_loopback_only():
        typer.secho(
            "agentlens: bound to a non-loopback host — no authentication is enabled. "
            "Expose only on networks you trust.",
            fg=typer.colors.RED,
            err=True,
        )

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


__all__ = ["serve"]
```

- [ ] **Step 6: Register the serve command in cli.py**

Add to imports at the top of `AgentLens/src/agentlens/cli.py`:

```python
from .commands import serve as serve_cmd
```

Add the registration line near the other `app.command(...)` calls (alphabetical with the verbs already there):

```python
app.command(name="serve")(serve_cmd.serve)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_healthz.py tests/unit/test_web_serve_command.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 8: Manual smoke**

```bash
cd AgentLens && .venv/bin/python -m agentlens.cli serve --help
```
Expected: prints help with all six options listed.

- [ ] **Step 9: Commit**

```bash
git add AgentLens/src/agentlens/web/app.py \
        AgentLens/src/agentlens/commands/serve.py \
        AgentLens/src/agentlens/cli.py \
        AgentLens/tests/integration/test_web_e2e_healthz.py \
        AgentLens/tests/unit/test_web_serve_command.py
git commit -m "feat(agentlens-dashboard): create_app() + /healthz + serve subcommand"
```

---

## M1 — Common Infrastructure

### Task 4: RFC 7807 ProblemDetails error handler

**Files:**
- Create: `AgentLens/src/agentlens/web/errors.py`
- Modify: `AgentLens/src/agentlens/web/app.py` (register handlers)
- Create: `AgentLens/tests/integration/test_web_e2e_errors.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_errors.py`:

```python
"""ProblemDetails error mapping (spec §6, §8)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _client(settings: ServeSettings) -> TestClient:
    app = create_app(settings)
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise RuntimeError("intentional")

    @router.get("/notfound")
    def notfound():
        raise HTTPException(status_code=404, detail="missing thing")

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_500_is_problem_json_without_traceback():
    c = _client(ServeSettings(debug=False))
    r = c.get("/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert "correlation_id" in body
    assert "intentional" not in body.get("detail", "")  # no traceback leakage


def test_debug_mode_includes_detail():
    c = _client(ServeSettings(debug=True))
    r = c.get("/boom")
    assert r.status_code == 500
    assert "intentional" in r.json()["detail"]


def test_httpexception_is_mapped():
    c = _client(ServeSettings())
    r = c.get("/notfound")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Not Found"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_errors.py -v
```
Expected: FAIL — content-type is `application/json`, not `application/problem+json`.

- [ ] **Step 3: Implement errors module**

`AgentLens/src/agentlens/web/errors.py`:

```python
"""RFC 7807 ProblemDetails error mapping (spec §6, §8)."""
from __future__ import annotations

import logging
import secrets
import traceback
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("agentlens.web")

PROBLEM_MEDIA = "application/problem+json"


def _new_correlation_id() -> str:
    return secrets.token_hex(8)


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
    body = {
        "type": type_,
        "title": title,
        "status": status,
    }
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
    """Register handlers that produce application/problem+json responses."""

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:  # noqa: ARG001
        title = HTTPStatus(exc.status_code).phrase
        return _problem(
            status=exc.status_code,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
            instance=str(request.url.path),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ARG001
        return _problem(
            status=422,
            title="Unprocessable Entity",
            detail="Request validation failed.",
            instance=str(request.url.path),
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = _new_correlation_id()
        logger.error(
            "unhandled exception correlation_id=%s path=%s\n%s",
            correlation_id,
            request.url.path,
            traceback.format_exc(),
        )
        settings = request.app.state.settings
        detail = str(exc) if getattr(settings, "debug", False) else None
        return _problem(
            status=500,
            title="Internal Server Error",
            detail=detail,
            instance=str(request.url.path),
            correlation_id=correlation_id,
        )


__all__ = ["install_error_handlers", "PROBLEM_MEDIA"]
```

- [ ] **Step 4: Wire handlers into create_app**

In `AgentLens/src/agentlens/web/app.py`, add the import and call:

```python
from agentlens.web.errors import install_error_handlers
```

And inside `create_app` after `app.state.settings = settings`:

```python
    install_error_handlers(app)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_errors.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/errors.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_errors.py
git commit -m "feat(agentlens-dashboard): RFC 7807 ProblemDetails error handlers"
```

---

### Task 5: Common security headers + non-loopback warning header

**Review correction:** this task must also cover the already-planned `--allow-origin` flag. Default responses should have no CORS allow-origin header. When `ServeSettings.allow_origin` is non-empty, install FastAPI/Starlette `CORSMiddleware` with that explicit allowlist and add an integration test for a matching Origin.

**Files:**
- Create: `AgentLens/src/agentlens/web/middleware.py`
- Modify: `AgentLens/src/agentlens/web/app.py`
- Create: `AgentLens/tests/integration/test_web_e2e_headers.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_headers.py`:

```python
"""Common response headers (spec §6)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _client(settings: ServeSettings) -> TestClient:
    return TestClient(create_app(settings))


def test_security_headers_present_on_healthz():
    r = _client(ServeSettings()).get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cache-control"] == "no-store"


def test_warning_header_absent_on_loopback():
    r = _client(ServeSettings(host="127.0.0.1")).get("/healthz")
    assert "x-agentlens-warning" not in r.headers


def test_warning_header_present_on_non_loopback():
    r = _client(ServeSettings(host="0.0.0.0")).get("/healthz")
    assert r.headers.get("x-agentlens-warning") == "bound-to-non-loopback"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_headers.py -v
```
Expected: FAIL — headers missing.

- [ ] **Step 3: Implement middleware**

`AgentLens/src/agentlens/web/middleware.py`:

```python
"""Common-response middleware (spec §6)."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CommonHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers and a host-warning header to every response."""

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
```

- [ ] **Step 4: Wire middleware into create_app**

In `AgentLens/src/agentlens/web/app.py`, add the import:

```python
from agentlens.web.middleware import CommonHeadersMiddleware
```

And inside `create_app` after `install_error_handlers(app)`:

```python
    app.add_middleware(CommonHeadersMiddleware)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_headers.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/middleware.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_headers.py
git commit -m "feat(agentlens-dashboard): common security headers + non-loopback warning header"
```

---

### Task 6: `web/deps.py` — AGENTLENS_HOME dependency

**Files:**
- Create: `AgentLens/src/agentlens/web/deps.py`
- Create: `AgentLens/tests/unit/test_web_deps.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/unit/test_web_deps.py`:

```python
"""Tests for agentlens.web.deps."""
from __future__ import annotations

from pathlib import Path

from agentlens.web.deps import resolve_home, store_exists


def test_resolve_home_uses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    assert resolve_home() == tmp_path


def test_store_exists_false_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path / "does-not-exist"))
    assert store_exists() is False


def test_store_exists_true_when_runs_dir_present(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    (tmp_path / "runs").mkdir()
    assert store_exists() is True
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_web_deps.py -v
```
Expected: FAIL — `cannot import name 'resolve_home'`.

- [ ] **Step 3: Implement deps**

`AgentLens/src/agentlens/web/deps.py`:

```python
"""FastAPI dependencies for the web layer (spec §4, §5)."""
from __future__ import annotations

from pathlib import Path

from agentlens.store.paths import agentlens_home


def resolve_home() -> Path:
    """Return ``$AGENTLENS_HOME`` (or default ``~/.agentlens``)."""
    return agentlens_home()


def store_exists() -> bool:
    """Return ``True`` if the runs dir exists under HOME."""
    return (resolve_home() / "runs").is_dir()


__all__ = ["resolve_home", "store_exists"]
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_web_deps.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/deps.py AgentLens/tests/unit/test_web_deps.py
git commit -m "feat(agentlens-dashboard): resolve_home() + store_exists() web dependencies"
```

---

## M2 — Read API Routers

### Task 7: `/api/v1/meta` endpoint

**Files:**
- Create: `AgentLens/src/agentlens/web/routers/meta.py`
- Modify: `AgentLens/src/agentlens/web/app.py` (register router)
- Create: `AgentLens/tests/integration/test_web_e2e_meta.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_meta.py`:

```python
"""Tests for /api/v1/meta."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_meta_empty_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["agentlens_version"]  # non-empty string
    assert body["schema_version"] == "v1"
    assert body["store_path"] == str(tmp_path)
    assert body["store_exists"] is False
    assert body["demo_mode"] is False


def test_meta_existing_store(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    (tmp_path / "runs").mkdir()
    r = TestClient(create_app(ServeSettings(demo=True))).get("/api/v1/meta")
    body = r.json()
    assert body["store_exists"] is True
    assert body["demo_mode"] is True
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_meta.py -v
```
Expected: FAIL — 404 on `/api/v1/meta`.

- [ ] **Step 3: Implement meta router**

`AgentLens/src/agentlens/web/routers/meta.py`:

```python
"""/api/v1/meta — viewer/version/store info (spec §6)."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agentlens.web.deps import resolve_home, store_exists

router = APIRouter(prefix="/api/v1", tags=["meta"])

SCHEMA_VERSION = "v1"


def _agentlens_version() -> str:
    try:
        return version("agentlens")
    except PackageNotFoundError:
        return "0.0.0+dev"


@router.get("/meta")
def meta(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse(
        {
            "agentlens_version": _agentlens_version(),
            "schema_version": SCHEMA_VERSION,
            "store_path": str(resolve_home()),
            "store_exists": store_exists(),
            "demo_mode": bool(settings.demo),
        }
    )


__all__ = ["router"]
```

- [ ] **Step 4: Register the router in create_app**

In `AgentLens/src/agentlens/web/app.py`, add the import:

```python
from agentlens.web.routers import meta as meta_router
```

And inside `create_app` after `app.add_middleware(...)`:

```python
    app.include_router(meta_router.router)
```

- [ ] **Step 5: Run to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_meta.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/meta.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_meta.py
git commit -m "feat(agentlens-dashboard): /api/v1/meta endpoint"
```

---

### Task 8: `/api/v1/runs` list endpoint with cursor pagination and filters

**Files:**
- Create: `AgentLens/src/agentlens/web/routers/runs.py`
- Modify: `AgentLens/src/agentlens/web/app.py` (register router)
- Create: `AgentLens/tests/integration/test_web_e2e_runs_list.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_runs_list.py`:

```python
"""Tests for /api/v1/runs."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def populated_home(monkeypatch, tmp_path):
    for name in ("minimal_run", "failed_command_run", "residual_risk_run"):
        copy_fixture_as_run_id(FIXTURES, name, tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_runs_list_returns_items(populated_home):
    c = TestClient(create_app(ServeSettings()))
    r = c.get("/api/v1/runs?since_days=36500")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None  # all fit in one page


def test_runs_list_pagination(populated_home):
    c = TestClient(create_app(ServeSettings()))
    r = c.get("/api/v1/runs?limit=2&since_days=36500")
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    r2 = c.get(f"/api/v1/runs?cursor={body['next_cursor']}&limit=2&since_days=36500")
    body2 = r2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None


def test_runs_list_filter_eval_status(populated_home):
    c = TestClient(create_app(ServeSettings()))
    r = c.get("/api/v1/runs?eval_status=failed&since_days=36500")
    body = r.json()
    for item in body["items"]:
        assert item["eval_status"] == "failed"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_runs_list.py -v
```
Expected: FAIL — 404 on `/api/v1/runs`.

- [ ] **Step 3: Implement runs router (list endpoint only for now)**

`AgentLens/src/agentlens/web/routers/runs.py`:

```python
"""/api/v1/runs/* (spec §6)."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from agentlens.commands._format import project_run_row
from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()))["o"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid cursor: {exc}") from None


@router.get("")
def list_runs(
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    workspace_id: str | None = Query(None),
    agent: str | None = Query(None),
    eval_status: str | None = Query(None),
    agent_outcome: str | None = Query(None),
    since_days: int | None = Query(None, ge=1, le=36500),
) -> JSONResponse:
    home = resolve_home()
    offset = _decode_cursor(cursor)
    filters = {
        k: v
        for k, v in {
            "workspace_id": workspace_id,
            "agent": agent,
            "eval_status": eval_status,
            "agent_outcome": agent_outcome,
            "since_days": since_days,
        }.items()
        if v is not None
    }
    rows = store_query.list_runs(home, filters=filters)
    if agent is not None:
        rows = [r for r in rows if r.get("agent_name") == agent]
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        rows = [
            r for r in rows
            if (dt := _parse_iso(r.get("started_at"))) is None or dt >= cutoff
        ]
    rows = sorted(rows, key=lambda r: r.get("started_at") or "", reverse=True)
    page = [project_run_row(r) for r in rows[offset : offset + limit]]
    next_cursor = _encode_cursor(offset + limit) if offset + limit < len(rows) else None
    return JSONResponse({"items": page, "next_cursor": next_cursor})


__all__ = ["router"]
```

- [ ] **Step 4: Register router in app**

In `AgentLens/src/agentlens/web/app.py`, add the import:

```python
from agentlens.web.routers import runs as runs_router
```

And add the include after the meta router:

```python
    app.include_router(runs_router.router)
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_runs_list.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_runs_list.py
git commit -m "feat(agentlens-dashboard): /api/v1/runs list with cursor pagination + filters"
```

---

### Task 9: Run detail endpoint + manifest_seal + verify

**Review correction:** the implementation below must use the real manifest contract. `manifest.json` has `files`, not `artifacts`, and no `manifest_sha256` field. Use `agentlens.store.manifest.verify(run_dir)` for integrity and compute any `manifest_digest` from the manifest file bytes. Tests should request the actual run ID from `run.json`, not the fixture directory name.

**Files:**
- Modify: `AgentLens/src/agentlens/web/routers/runs.py`
- Create: `AgentLens/tests/integration/test_web_e2e_run_detail.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_run_detail.py`:

```python
"""Tests for /api/v1/runs/{id} and /api/v1/runs/{id}/verify."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home_with_minimal(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "minimal_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_run_detail_present(home_with_minimal):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == run_id
    assert "agent_outcome" in body
    assert "eval_status" in body
    assert "manifest_seal" in body


def test_run_detail_404(home_with_minimal):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_run_verify(home_with_minimal):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/verify")
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body
    assert "mismatches" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_detail.py -v
```
Expected: FAIL — endpoints don't exist.

- [ ] **Step 3: Add detail and verify endpoints**

Append to `AgentLens/src/agentlens/web/routers/runs.py`:

```python
import hashlib
import json as _json
from pathlib import Path

from agentlens.store import manifest as manifest_store


def _run_dir_for(home, run_id: str) -> Path | None:
    runs_root = Path(home) / "runs"
    for ws_dir in runs_root.iterdir() if runs_root.exists() else []:
        candidate = ws_dir / run_id
        if candidate.is_dir():
            return candidate
    return None


def _load_manifest(home, run_id: str) -> dict | None:
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None:
        return None
    manifest = run_dir / "manifest.json"
    if manifest.is_file():
        return _json.loads(manifest.read_text())
    return None


def _manifest_digest(run_dir: Path) -> str | None:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    return "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _enrich_with_manifest(row: dict, home) -> dict:
    run_dir = _run_dir_for(home, row["run_id"])
    seal = {"phase": row.get("sealed_phase")}
    if run_dir is not None and (manifest := _load_manifest(home, row["run_id"])):
        mismatches = manifest_store.verify(run_dir)
        seal["sealed_at"] = manifest.get("sealed_at")
        seal["manifest_digest"] = _manifest_digest(run_dir)
        seal["integrity"] = "ok" if not mismatches else "broken"
        seal["mismatches_count"] = len(mismatches)
    row["manifest_seal"] = seal
    return row


@router.get("/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    home = resolve_home()
    row = store_query.get_run(home, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return JSONResponse(_enrich_with_manifest(dict(row), home))


@router.get("/{run_id}/verify")
def verify_run(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None or not (run_dir / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    manifest = _json.loads((run_dir / "manifest.json").read_text())
    expected = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    mismatches = [
        {"path": m.path, "expected": expected.get(m.path), "actual": m.sha256 or None}
        for m in manifest_store.verify(run_dir)
    ]
    return JSONResponse({"ok": not mismatches, "mismatches": mismatches})
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_detail.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py AgentLens/tests/integration/test_web_e2e_run_detail.py
git commit -m "feat(agentlens-dashboard): /api/v1/runs/{id} detail + /verify endpoint"
```

---

### Task 10: NDJSON events stream endpoint

**Files:**
- Modify: `AgentLens/src/agentlens/web/routers/runs.py`
- Create: `AgentLens/tests/integration/test_web_e2e_run_events.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_run_events.py`:

```python
"""Tests for /api/v1/runs/{id}/events (NDJSON)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "minimal_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_events_returns_ndjson(home):
    run_id = json.loads((FIXTURES / "minimal_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    # Every line is valid JSON.
    for line in lines:
        assert isinstance(json.loads(line), dict)


def test_events_malformed_line_becomes_error_marker(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo" / "broken_run"
    runs.mkdir(parents=True)
    (runs / "events.jsonl").write_text(
        '{"type":"start"}\nNOT JSON HERE\n{"type":"final"}\n'
    )
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/broken_run/events")
    lines = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    assert lines[0]["type"] == "start"
    assert lines[1].get("_error") == "parse"
    assert lines[1]["line"] == 2
    assert lines[2]["type"] == "final"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_events.py -v
```
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Implement events endpoint**

Append to `AgentLens/src/agentlens/web/routers/runs.py`:

```python
from fastapi.responses import StreamingResponse


def _find_events_path(home, run_id: str) -> Path | None:
    runs_root = Path(home) / "runs"
    for ws_dir in runs_root.iterdir() if runs_root.exists() else []:
        events = ws_dir / run_id / "events.jsonl"
        if events.is_file():
            return events
    return None


def _iter_events(path: Path):
    with path.open() as f:
        for i, raw in enumerate(f, start=1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            try:
                _json.loads(raw)
                yield raw + "\n"
            except _json.JSONDecodeError:
                yield _json.dumps({"_error": "parse", "line": i}) + "\n"


@router.get("/{run_id}/events")
def run_events(run_id: str) -> StreamingResponse:
    home = resolve_home()
    events_path = _find_events_path(home, run_id)
    if events_path is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return StreamingResponse(_iter_events(events_path), media_type="application/x-ndjson")
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_events.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py AgentLens/tests/integration/test_web_e2e_run_events.py
git commit -m "feat(agentlens-dashboard): /api/v1/runs/{id}/events NDJSON stream with parse markers"
```

---

### Task 11: Per-run failures / risks / artifacts endpoints

**Review correction:** per-run failures and risks cannot come from `query.get_run(...).get("failures")` or `.get("risks")`; `get_run` merges top-level JSON files and does not build those arrays. Filter `query.failures(home, since_days=36500)` and `query.risks(home, since_days=36500)` by `run_id`, then apply `project_failure` / `project_risk`. Artifact listing must derive from `manifest.files`, and raw download is allowed only for entries whose relative path starts with `artifacts/`.

**Files:**
- Modify: `AgentLens/src/agentlens/web/routers/runs.py`
- Create: `AgentLens/tests/integration/test_web_e2e_run_aux.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_run_aux.py`:

```python
"""Tests for per-run failures/risks/artifacts endpoints."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "failed_command_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_per_run_failures(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(
        f"/api/v1/runs/{run_id}/failures"
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)


def test_per_run_risks(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(
        f"/api/v1/runs/{run_id}/risks"
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_per_run_artifacts(home):
    run_id = json.loads((FIXTURES / "failed_command_run" / "run.json").read_text())["run_id"]
    r = TestClient(create_app(ServeSettings())).get(
        f"/api/v1/runs/{run_id}/artifacts"
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_aux.py -v
```
Expected: FAIL — endpoints missing (404).

- [ ] **Step 3: Implement endpoints**

Append to `AgentLens/src/agentlens/web/routers/runs.py`:

```python
from agentlens.commands._format import project_failure, project_risk


@router.get("/{run_id}/failures")
def run_failures(run_id: str) -> JSONResponse:
    home = resolve_home()
    if _run_dir_for(home, run_id) is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    rows = [f for f in store_query.failures(home, since_days=36500) if f.get("run_id") == run_id]
    return JSONResponse([project_failure(f) for f in rows])


@router.get("/{run_id}/risks")
def run_risks(run_id: str) -> JSONResponse:
    home = resolve_home()
    if _run_dir_for(home, run_id) is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    rows = [r for r in store_query.risks(home, since_days=36500) if r.get("run_id") == run_id]
    return JSONResponse([project_risk(r) for r in rows])


@router.get("/{run_id}/artifacts")
def run_artifacts(run_id: str) -> JSONResponse:
    home = resolve_home()
    manifest = _load_manifest(home, run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    artifacts = manifest.get("files") or []
    return JSONResponse([
        {
            "path": a.get("path"),
            "sha256": a.get("sha256"),
            "downloadable": str(a.get("path", "")).startswith("artifacts/"),
        }
        for a in artifacts
    ])
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_aux.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Add the per-artifact download endpoint (test first)**

Append to `AgentLens/tests/integration/test_web_e2e_run_aux.py`:

```python
def test_artifact_download_redacted_header(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo" / "art_run"
    runs.mkdir(parents=True)
    (runs / "manifest.json").write_text(
        '{"files":[{"path":"artifacts/out.txt","sha256":"sha256:' + '0' * 64 + '"}]}'
    )
    artifacts_dir = runs / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "out.txt").write_bytes(b"hello")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))

    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/runs/art_run/artifacts/sha256:" + "0" * 64
    )
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers.get("x-agentlens-redacted") == "true"
```

Append to `AgentLens/src/agentlens/web/routers/runs.py`:

```python
from fastapi.responses import Response


@router.get("/{run_id}/artifacts/{sha256}")
def download_artifact(run_id: str, sha256: str) -> Response:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    manifest = _load_manifest(home, run_id)
    if run_dir is None or manifest is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    for entry in manifest.get("files") or []:
        rel = str(entry.get("path", ""))
        if entry.get("sha256") == sha256 and rel.startswith("artifacts/"):
            candidate = run_dir / rel
            if candidate.is_file():
                return Response(
                    content=candidate.read_bytes(),
                    media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": f'attachment; filename="{Path(rel).name}"',
                        "X-AgentLens-Redacted": "true",
                    },
                )
    raise HTTPException(status_code=404, detail=f"artifact not found: {sha256}")
```

- [ ] **Step 6: Run to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_aux.py -v
```
Expected: PASS (4 tests now).

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py AgentLens/tests/integration/test_web_e2e_run_aux.py
git commit -m "feat(agentlens-dashboard): per-run failures/risks/artifacts + artifact download"
```

---

### Task 12: Workspaces router (list + detail with aggregations)

**Files:**
- Create: `AgentLens/src/agentlens/web/routers/workspaces.py`
- Modify: `AgentLens/src/agentlens/web/app.py`
- Create: `AgentLens/tests/integration/test_web_e2e_workspaces.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_workspaces.py`:

```python
"""Tests for /api/v1/workspaces[/{id}]."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "minimal_run", tmp_path / "runs")
    copy_fixture_as_run_id(FIXTURES, "failed_command_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_workspaces_list(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/workspaces")
    assert r.status_code == 200
    ids = {w["workspace_id"] for w in r.json()}
    assert ids == {"ws_0000000000000001", "ws_0000000000000002"}


def test_workspace_detail(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/workspaces/ws_0000000000000001")
    body = r.json()
    assert body["workspace_id"] == "ws_0000000000000001"
    assert "run_count" in body
    assert "recent_runs" in body
    assert "eval_pass_rate_30d" in body


def test_workspace_detail_404(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/workspaces/ws_missing")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_workspaces.py -v
```
Expected: FAIL — 404 on all (router missing).

- [ ] **Step 3: Implement workspaces router**

`AgentLens/src/agentlens/web/routers/workspaces.py`:

```python
"""/api/v1/workspaces (spec §6)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def _workspace_dirs(home):
    runs_root = Path(home) / "runs"
    if not runs_root.exists():
        return []
    return sorted([p for p in runs_root.iterdir() if p.is_dir()])


def _runs_for_workspace(home, workspace_id: str):
    return store_query.list_runs(home, filters={"workspace_id": workspace_id})


@router.get("")
def list_workspaces() -> JSONResponse:
    home = resolve_home()
    items = []
    for ws_dir in _workspace_dirs(home):
        ws_id = ws_dir.name
        rows = _runs_for_workspace(home, ws_id)
        latest = max((r.get("started_at") or "" for r in rows), default=None)
        items.append(
            {
                "workspace_id": ws_id,
                "workspace_short": ws_id[:11],
                "id_basis": "git" if ws_id.startswith("ws_") else "path",
                "run_count": len(rows),
                "latest_started_at": latest,
            }
        )
    return JSONResponse(items)


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    recent_limit: int = Query(20, ge=1, le=200),
) -> JSONResponse:
    home = resolve_home()
    rows = _runs_for_workspace(home, workspace_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")

    passed = sum(1 for r in rows if r.get("eval_status") == "passed")
    total_evaluated = sum(1 for r in rows if r.get("eval_status") in {"passed", "failed"})
    pass_rate = (passed / total_evaluated) if total_evaluated else None

    agents = Counter(r.get("agent_name") for r in rows if r.get("agent_name"))

    return JSONResponse(
        {
            "workspace_id": workspace_id,
            "workspace_short": workspace_id[:11],
            "id_basis": "git" if workspace_id.startswith("ws_") else "path",
            "run_count": len(rows),
            "recent_runs": rows[:recent_limit],
            "eval_pass_rate_30d": pass_rate,
            "agent_breakdown": dict(agents),
        }
    )


__all__ = ["router"]
```

- [ ] **Step 4: Register router**

In `AgentLens/src/agentlens/web/app.py`, add the import and include:

```python
from agentlens.web.routers import workspaces as workspaces_router
```

```python
    app.include_router(workspaces_router.router)
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_workspaces.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/workspaces.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_workspaces.py
git commit -m "feat(agentlens-dashboard): /api/v1/workspaces list + detail with pass-rate aggregations"
```

---

### Task 13: Global failures/risks router

**Files:**
- Create: `AgentLens/src/agentlens/web/routers/failures.py`
- Modify: `AgentLens/src/agentlens/web/app.py`
- Create: `AgentLens/tests/integration/test_web_e2e_failures_global.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_failures_global.py`:

```python
"""Tests for /api/v1/failures and /api/v1/risks (global)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    copy_fixture_as_run_id(FIXTURES, "failed_command_run", tmp_path / "runs")
    copy_fixture_as_run_id(FIXTURES, "residual_risk_run", tmp_path / "runs")
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_global_failures(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/failures")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_global_risks(home):
    r = TestClient(create_app(ServeSettings())).get("/api/v1/risks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_global_failures_filter(home):
    r = TestClient(create_app(ServeSettings())).get(
        "/api/v1/failures?workspace_id=ws_0000000000000002&since_days=36500"
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_failures_global.py -v
```
Expected: FAIL — router missing.

- [ ] **Step 3: Implement failures router**

`AgentLens/src/agentlens/web/routers/failures.py`:

```python
"""/api/v1/failures and /api/v1/risks (spec §6)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agentlens.store import query as store_query
from agentlens.web.deps import resolve_home

router = APIRouter(prefix="/api/v1", tags=["failures-risks"])


@router.get("/failures")
def list_failures(
    workspace_id: str | None = Query(None),
    since_days: int = Query(30, ge=1, le=3650),
) -> JSONResponse:
    home = resolve_home()
    rows = store_query.failures(home, since_days=since_days)
    if workspace_id is not None:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return JSONResponse(rows)


@router.get("/risks")
def list_risks(
    workspace_id: str | None = Query(None),
    since_days: int = Query(30, ge=1, le=3650),
) -> JSONResponse:
    home = resolve_home()
    rows = store_query.risks(home, since_days=since_days)
    if workspace_id is not None:
        rows = [r for r in rows if r.get("workspace_id") == workspace_id]
    return JSONResponse(rows)


__all__ = ["router"]
```

- [ ] **Step 4: Register router**

In `AgentLens/src/agentlens/web/app.py`:

```python
from agentlens.web.routers import failures as failures_router
```

```python
    app.include_router(failures_router.router)
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_failures_global.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/failures.py AgentLens/src/agentlens/web/app.py AgentLens/tests/integration/test_web_e2e_failures_global.py
git commit -m "feat(agentlens-dashboard): /api/v1/failures + /api/v1/risks global endpoints"
```

---

### Task 14: Doctor router (parity with CLI)

**Review correction:** preserve the existing CLI API: `doctor(scope: str = "all", fmt: str = "--format")`. Do not replace it with `doctor(format=...)`. Extract `collect_doctor_report(scope: str = "all")` from the existing JSON-building logic, preserve current `integrations` / `paths` behaviour, and add `warnings: []` as an additive key for dashboard consumers.

**Files:**
- Create: `AgentLens/src/agentlens/web/routers/doctor.py`
- Modify: `AgentLens/src/agentlens/web/app.py`
- Create: `AgentLens/tests/integration/test_web_e2e_doctor.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_doctor.py`:

```python
"""Test that /api/v1/doctor mirrors the CLI doctor JSON output."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_doctor_returns_structured_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    r = TestClient(create_app(ServeSettings())).get("/api/v1/doctor")
    assert r.status_code == 200
    body = r.json()
    # Doctor JSON shape per CLI: at minimum these keys.
    for key in ("integrations", "paths", "warnings"):
        assert key in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_doctor.py -v
```
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Refactor `commands/doctor.py` to expose `collect_doctor_report()`**

Read `AgentLens/src/agentlens/commands/doctor.py`. Identify the block that builds the JSON payload returned when `--format json` is passed. Extract that block into a new module-level function:

```python
def collect_doctor_report(scope: str = "all") -> dict[str, object]:
    """Return the structured doctor report (same shape as ``doctor --format json``)."""
    # Move the existing scoped JSON-building logic verbatim into this function.
    # Preserve scope in {"integrations", "paths", "all"}.
    report.setdefault("warnings", [])
    return report
```

Then change the existing `doctor()` Typer command to call this helper:

```python
def doctor(
    scope: str = typer.Argument("all", help="What to inspect: integrations | paths | all."),
    fmt: str = typer.Option("text", "--format", help="Output format: text | json."),
) -> None:
    if scope not in {"integrations", "paths", "all"}:
        raise typer.BadParameter(f"invalid scope {scope!r}; expected integrations | paths | all")
    if fmt not in {"text", "json"}:
        raise typer.BadParameter(f"invalid --format {fmt!r}; expected text | json")
    report = collect_doctor_report(scope)
    if fmt == "json":
        typer.echo(json.dumps(report, sort_keys=True))
        return
    # unchanged text rendering, using only blocks present for the requested scope
```

Run the existing CLI test to confirm no behaviour drift:

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_install_doctor.py -v
```
Expected: PASS (unchanged).

- [ ] **Step 4: Implement doctor router**

`AgentLens/src/agentlens/web/routers/doctor.py`:

```python
"""/api/v1/doctor — wraps the CLI doctor logic (spec §6)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agentlens.commands.doctor import collect_doctor_report

router = APIRouter(prefix="/api/v1", tags=["doctor"])


@router.get("/doctor")
def doctor() -> JSONResponse:
    return JSONResponse(collect_doctor_report("all"))


__all__ = ["router"]
```

- [ ] **Step 5: Register router**

In `AgentLens/src/agentlens/web/app.py`:

```python
from agentlens.web.routers import doctor as doctor_router
```

```python
    app.include_router(doctor_router.router)
```

- [ ] **Step 6: Run to verify it passes**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_doctor.py tests/integration/test_install_doctor.py -v
```
Expected: PASS (both new test and existing CLI doctor tests).

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/doctor.py AgentLens/src/agentlens/web/app.py AgentLens/src/agentlens/commands/doctor.py AgentLens/tests/integration/test_web_e2e_doctor.py
git commit -m "feat(agentlens-dashboard): /api/v1/doctor + refactor CLI doctor to share collector"
```

---

## M3 — Demo Data + Edge Cases

### Task 15: Bundle curated demo fixtures into `src/agentlens/demo_data/`

**Files:**
- Create: `AgentLens/src/agentlens/demo_data/__init__.py`
- Create: `AgentLens/src/agentlens/demo_data/runs/<workspace_id>/<run_id>/...` (copy from `tests/fixtures`, preserving IDs from each fixture's `run.json`)
- Modify: `AgentLens/pyproject.toml` (package-data)
- Create: `AgentLens/tests/unit/test_demo_data.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/unit/test_demo_data.py`:

```python
"""Tests for bundled demo data."""
from __future__ import annotations

from agentlens.demo_data import demo_root


def test_demo_root_exists():
    root = demo_root()
    assert root.is_dir()


def test_demo_root_contains_runs():
    root = demo_root()
    runs_dir = root / "runs"
    assert runs_dir.is_dir()
    ws_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert len(ws_dirs) >= 1
    # At least the false-success demo run is present.
    has_false_success = False
    for ws in ws_dirs:
        for run in ws.iterdir():
            if (run / "eval.json").is_file():
                import json

                eval_doc = json.loads((run / "eval.json").read_text())
                if eval_doc.get("status") == "failed":
                    has_false_success = True
    assert has_false_success, "demo data should include at least one failed-eval run"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_demo_data.py -v
```
Expected: FAIL — `demo_data` package empty.

- [ ] **Step 3: Create demo_data accessor**

`AgentLens/src/agentlens/demo_data/__init__.py`:

```python
"""Bundled demo runs used by ``agentlens serve --demo``.

The runs are a curated subset of ``tests/fixtures/*_run`` packaged
into the wheel via ``[tool.setuptools.package-data]``.
"""
from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def demo_root() -> Path:
    """Return the bundled demo data root (resolved on disk)."""
    pkg = files("agentlens.demo_data")
    with as_file(pkg) as p:
        return Path(p)


__all__ = ["demo_root"]
```

- [ ] **Step 4: Populate demo runs**

Copy these fixtures from `AgentLens/tests/fixtures/` into `AgentLens/src/agentlens/demo_data/runs/<workspace_id>/<run_id>/`, reading both IDs from each fixture's `run.json`:

```bash
cd AgentLens
for fixture in minimal_run failed_command_run residual_risk_run missing_final_run corrupt_manifest_run; do
  read workspace_id run_id <<< "$(.venv/bin/python -c 'import json, pathlib, sys; d=json.loads((pathlib.Path("tests/fixtures")/sys.argv[1]/"run.json").read_text()); print(d["workspace_id"], d["run_id"])' "$fixture")"
  mkdir -p "src/agentlens/demo_data/runs/$workspace_id"
  cp -R "tests/fixtures/$fixture" "src/agentlens/demo_data/runs/$workspace_id/$run_id"
done
# Remove the expected_eval.json files (they're test artifacts, not part of a real run).
find src/agentlens/demo_data -name expected_eval.json -delete
```

- [ ] **Step 5: Update pyproject package-data**

Replace the `[tool.setuptools.package-data]` block in `AgentLens/pyproject.toml`:

```toml
[tool.setuptools.package-data]
"agentlens.schema.jsonschema" = ["*.schema.json"]
"agentlens.demo_data" = ["**/*.json", "**/*.jsonl"]
```

- [ ] **Step 6: Run tests to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_demo_data.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add AgentLens/src/agentlens/demo_data/ AgentLens/pyproject.toml AgentLens/tests/unit/test_demo_data.py
git commit -m "feat(agentlens-dashboard): bundle curated demo runs for --demo flag"
```

---

### Task 16: `--demo` flag implementation

**Files:**
- Modify: `AgentLens/src/agentlens/commands/serve.py`
- Modify: `AgentLens/src/agentlens/web/app.py` (banner state)
- Modify: `AgentLens/src/agentlens/web/routers/meta.py` (expose demo_mode — already done in Task 7; verify)
- Create: `AgentLens/tests/integration/test_web_e2e_demo.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_demo.py`:

```python
"""--demo flag: store points at a temp copy of bundled demo data."""
from __future__ import annotations

from typer.testing import CliRunner

from agentlens.cli import app


def test_demo_flag_seeds_temp_home(monkeypatch, tmp_path):
    # The demo helper should set AGENTLENS_HOME to a directory populated
    # from agentlens.demo_data and signal demo mode in the settings.
    from agentlens.commands.serve import _materialise_demo_home

    home, marker = _materialise_demo_home()
    try:
        assert home.is_dir()
        assert (home / "runs").is_dir()
        assert marker.exists()
    finally:
        import shutil

        shutil.rmtree(home, ignore_errors=True)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_demo.py -v
```
Expected: FAIL — `_materialise_demo_home` missing.

- [ ] **Step 3: Update serve command with demo helper**

Replace the entire body of `AgentLens/src/agentlens/commands/serve.py` with:

```python
"""``agentlens serve`` — boot the dashboard (spec §4, §9)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import typer
import uvicorn

from agentlens.demo_data import demo_root
from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def _materialise_demo_home() -> tuple[Path, Path]:
    """Copy bundled demo data into a fresh temp dir; return (home, marker)."""
    home = Path(tempfile.mkdtemp(prefix="agentlens-demo-"))
    src_runs = demo_root() / "runs"
    if src_runs.exists():
        shutil.copytree(src_runs, home / "runs")
    marker = home / ".demo"
    marker.write_text("agentlens demo home\n")
    return home, marker


def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(5757, "--port"),
    demo: bool = typer.Option(False, "--demo"),
    debug: bool = typer.Option(False, "--debug"),
    auto_port: bool = typer.Option(False, "--auto-port"),
    dev_proxy: str | None = typer.Option(None, "--dev-proxy"),
    allow_origin: list[str] = typer.Option([], "--allow-origin"),
) -> None:
    """Spawn the AgentLens web viewer."""
    settings = ServeSettings(
        host=host,
        port=port,
        demo=demo,
        debug=debug,
        auto_port=auto_port,
        dev_proxy=dev_proxy,
        allow_origin=tuple(allow_origin),
    )

    if demo:
        demo_home, _ = _materialise_demo_home()
        os.environ["AGENTLENS_HOME"] = str(demo_home)
        typer.secho(
            f"agentlens: demo mode — using temp home at {demo_home}",
            fg=typer.colors.YELLOW,
            err=True,
        )

    if not settings.is_loopback_only():
        typer.secho(
            "agentlens: bound to a non-loopback host — no authentication is enabled. "
            "Expose only on networks you trust.",
            fg=typer.colors.RED,
            err=True,
        )

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


__all__ = ["serve"]
```

- [ ] **Step 4: Run tests to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_demo.py tests/integration/test_web_e2e_meta.py -v
```
Expected: PASS for both files.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/commands/serve.py AgentLens/tests/integration/test_web_e2e_demo.py
git commit -m "feat(agentlens-dashboard): --demo flag materialises bundled demo data into temp HOME"
```

---

### Task 17: Edge cases — schema_version mismatch and partial runs

**Review correction:** there is no `schema_version` field in `run.json`. The test fixture for a future run should write `{"schema":"agentlens.run.v2", ...}` with enough required fields to be a plausible future artifact, and the handler should reject by parsing the `schema` value. Corrupt manifest detection should use `manifest.verify(run_dir)`, not a non-existent `manifest_sha256` field.

**Files:**
- Modify: `AgentLens/src/agentlens/web/routers/runs.py`
- Create: `AgentLens/tests/integration/test_web_e2e_run_edge_cases.py`

- [ ] **Step 1: Write the failing test**

`AgentLens/tests/integration/test_web_e2e_run_edge_cases.py`:

```python
"""Edge cases: partial runs, schema_version mismatch, corrupt manifest."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def home(monkeypatch, tmp_path):
    runs = tmp_path / "runs" / "ws_demo"
    runs.mkdir(parents=True)
    monkeypatch.setenv("AGENTLENS_HOME", str(tmp_path))
    return tmp_path


def test_partial_run_returns_200_with_marker(home, tmp_path):
    runs = tmp_path / "runs" / "ws_demo"
    run_id = copy_fixture_as_run_id(FIXTURES, "missing_final_run", tmp_path / "runs")[1]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    assert r.json().get("partial") is True


def test_unknown_schema_version_returns_412(home, tmp_path):
    rd = tmp_path / "runs" / "ws_demo" / "future_run"
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(json.dumps({
        "schema": "agentlens.run.v2",
        "run_id": "future_run",
        "workspace_id": "ws_demo",
        "started_at": "2026-01-01T00:00:00Z",
    }))
    (rd / "events.jsonl").write_text("")
    r = TestClient(create_app(ServeSettings())).get("/api/v1/runs/future_run")
    assert r.status_code == 412
    body = r.json()
    assert body["title"] == "Precondition Failed"


def test_corrupt_manifest_flagged_but_200(home, tmp_path):
    runs = tmp_path / "runs" / "ws_demo"
    run_id = copy_fixture_as_run_id(FIXTURES, "corrupt_manifest_run", tmp_path / "runs")[1]
    r = TestClient(create_app(ServeSettings())).get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    seal = r.json().get("manifest_seal") or {}
    assert seal.get("integrity") == "broken"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_edge_cases.py -v
```
Expected: FAIL — partial/schema/corrupt not yet handled.

- [ ] **Step 3: Update the detail handler**

In `AgentLens/src/agentlens/web/routers/runs.py`, replace the `get_run` function and helpers:

```python
def _run_dir_for(home, run_id: str) -> Path | None:
    runs_root = Path(home) / "runs"
    for ws_dir in runs_root.iterdir() if runs_root.exists() else []:
        candidate = ws_dir / run_id
        if candidate.is_dir():
            return candidate
    return None


def _detect_schema_version(run_dir: Path) -> str:
    rj = run_dir / "run.json"
    if rj.is_file():
        try:
            data = _json.loads(rj.read_text())
            schema = str(data.get("schema") or "agentlens.run.v1")
            return schema.rsplit(".", 1)[-1]
        except _json.JSONDecodeError:
            return "v1"
    return "v1"


def _detect_partial(run_dir: Path) -> bool:
    """A run is 'partial' when final.json is absent or manifest is unsealed."""
    return not (run_dir / "final.json").is_file() or not (run_dir / "manifest.json").is_file()


def _enrich_with_manifest(row: dict, home) -> dict:
    run_dir = _run_dir_for(home, row["run_id"])
    seal = {"phase": row.get("sealed_phase")}
    if run_dir is not None and (manifest := _load_manifest(home, row["run_id"])):
        mismatches = manifest_store.verify(run_dir)
        seal["sealed_at"] = manifest.get("sealed_at")
        seal["manifest_digest"] = _manifest_digest(run_dir)
        seal["integrity"] = "ok" if not mismatches else "broken"
        seal["mismatches_count"] = len(mismatches)
    row["manifest_seal"] = seal
    return row


@router.get("/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    home = resolve_home()
    run_dir = _run_dir_for(home, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    schema_version = _detect_schema_version(run_dir)
    if schema_version != "v1":
        raise HTTPException(
            status_code=412,
            detail=f"unsupported run schema {schema_version!r}; viewer supports v1",
        )
    row = store_query.get_run(home, run_id) or {"run_id": run_id, "workspace_id": run_dir.parent.name}
    row = _enrich_with_manifest(dict(row), home)
    if _detect_partial(run_dir):
        row["partial"] = True
    return JSONResponse(row)
```

- [ ] **Step 4: Run tests to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/integration/test_web_e2e_run_edge_cases.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/src/agentlens/web/routers/runs.py AgentLens/tests/integration/test_web_e2e_run_edge_cases.py
git commit -m "feat(agentlens-dashboard): partial-run marker + schema mismatch 412 + integrity check"
```

---

### Task 18: `--auto-port` fallback and `--dev-proxy` mount

**Files:**
- Modify: `AgentLens/src/agentlens/commands/serve.py`
- Modify: `AgentLens/src/agentlens/web/app.py` (StaticFiles or dev_proxy mount)
- Create: `AgentLens/tests/unit/test_serve_port_fallback.py`
- Create: `AgentLens/tests/integration/test_web_e2e_dev_proxy.py`

- [ ] **Step 1: Write the failing tests**

`AgentLens/tests/unit/test_serve_port_fallback.py`:

```python
"""--auto-port: pick the first free port among port..port+3."""
from __future__ import annotations

import socket

from agentlens.commands.serve import _select_port


def _bound_socket(port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def test_returns_requested_port_when_free():
    assert _select_port(5757, auto=False) == 5757


def test_auto_port_skips_busy(monkeypatch):
    # Bind 50100 and then ask --auto-port starting from 50100 → expect 50101.
    s = _bound_socket(50100)
    try:
        assigned = _select_port(50100, auto=True, max_offset=3)
        assert assigned in {50101, 50102, 50103}
    finally:
        s.close()


def test_no_auto_port_raises(monkeypatch):
    import pytest

    s = _bound_socket(50200)
    try:
        with pytest.raises(OSError):
            _select_port(50200, auto=False)
    finally:
        s.close()
```

`AgentLens/tests/integration/test_web_e2e_dev_proxy.py`:

```python
"""--dev-proxy: when set, GET / is proxied. Smoke-only test (mounts work)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentlens.web.app import create_app
from agentlens.web.settings import ServeSettings


def test_dev_proxy_does_not_fail_to_mount():
    # We don't actually round-trip the proxy, but we verify the app builds.
    s = ServeSettings(dev_proxy="http://127.0.0.1:5173")
    app = create_app(s)
    r = TestClient(app).get("/api/v1/meta")
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_serve_port_fallback.py tests/integration/test_web_e2e_dev_proxy.py -v
```
Expected: FAIL — `_select_port` missing; settings.dev_proxy unwired.

- [ ] **Step 3: Add port selection helper**

Append to `AgentLens/src/agentlens/commands/serve.py` (above `serve`):

```python
import socket


def _select_port(port: int, *, auto: bool, max_offset: int = 3) -> int:
    def _is_free(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return True
            except OSError:
                return False

    if _is_free(port):
        return port
    if not auto:
        raise OSError(f"port {port} is already in use; pass --auto-port to try {port + 1}..{port + max_offset}")
    for offset in range(1, max_offset + 1):
        if _is_free(port + offset):
            return port + offset
    raise OSError(f"no free port in range {port}..{port + max_offset}")
```

Replace the `uvicorn.run(...)` call in `serve()` with:

```python
    chosen = _select_port(settings.port, auto=settings.auto_port)
    if chosen != settings.port:
        typer.secho(f"agentlens: port {settings.port} busy → using {chosen}", err=True)
    uvicorn.run(app, host=settings.host, port=chosen, log_level="info")
```

- [ ] **Step 4: Wire dev_proxy in app factory**

In `AgentLens/src/agentlens/web/app.py`, append inside `create_app` (after router includes):

```python
    # Static / dev-proxy mount is the *last* route — runs after /api/v1 and /healthz.
    if settings.dev_proxy:
        from agentlens.web.dev_proxy import mount_dev_proxy

        mount_dev_proxy(app, settings.dev_proxy)
```

Create `AgentLens/src/agentlens/web/dev_proxy.py`:

```python
"""Reverse-proxy mount for the Vite dev server (loopback only)."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response


def mount_dev_proxy(app: FastAPI, target: str) -> None:
    client = httpx.AsyncClient(base_url=target.rstrip("/"), timeout=30.0)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def _proxy(path: str, request: Request) -> Response:
        if path.startswith(("api/v1", "healthz", "docs", "openapi.json")):
            raise RuntimeError("Proxy should not handle API routes")
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
                k: v for k, v in upstream.headers.items() if k.lower() != "transfer-encoding"
            },
        )
```

Add `httpx` to `pyproject.toml` deps:

```toml
dependencies = [
    "jsonschema>=4",
    "typer",
    "pyyaml",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic-settings>=2.2",
    "httpx>=0.27",
]
```

Reinstall: `cd AgentLens && uv pip install -e .`.

- [ ] **Step 5: Run tests to verify**

```bash
cd AgentLens && .venv/bin/python -m pytest tests/unit/test_serve_port_fallback.py tests/integration/test_web_e2e_dev_proxy.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/src/agentlens/commands/serve.py AgentLens/src/agentlens/web/app.py AgentLens/src/agentlens/web/dev_proxy.py AgentLens/pyproject.toml AgentLens/tests/unit/test_serve_port_fallback.py AgentLens/tests/integration/test_web_e2e_dev_proxy.py
git commit -m "feat(agentlens-dashboard): --auto-port fallback + --dev-proxy reverse proxy mount"
```

---

## M4 — Frontend Scaffold

### Task 19: Frontend project scaffolding

**Review correction:** Vite must not delete `src/agentlens/web_assets/__init__.py`. Either set `emptyOutDir:false` and clean generated files with a command that preserves `__init__.py`, or build into a child directory such as `src/agentlens/web_assets/static/` and mount that child directory. Do not use `emptyOutDir:true` directly against the Python package root.

**Files:**
- Create: `AgentLens/web/package.json`
- Create: `AgentLens/web/vite.config.ts`
- Create: `AgentLens/web/tsconfig.json`
- Create: `AgentLens/web/tailwind.config.ts`
- Create: `AgentLens/web/postcss.config.js`
- Create: `AgentLens/web/index.html`
- Create: `AgentLens/web/src/main.tsx`
- Create: `AgentLens/web/src/index.css`
- Create: `AgentLens/web/.gitignore`

- [ ] **Step 1: Write package.json**

`AgentLens/web/package.json`:

```json
{
  "name": "@agentlens/web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint src --max-warnings 0",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "gen-types": "tsx scripts/gen-types.ts"
  },
  "dependencies": {
    "@radix-ui/react-collapsible": "^1.1.1",
    "@radix-ui/react-dialog": "^1.1.1",
    "@radix-ui/react-tabs": "^1.1.1",
    "@radix-ui/react-tooltip": "^1.1.1",
    "@tanstack/react-query": "^5.59.0",
    "classnames": "^2.5.1",
    "lucide-react": "^0.456.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^6.28.0",
    "zod": "^3.23.8"
  },
  "devDependencies": {
    "@playwright/test": "^1.48.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/node": "^22.7.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "eslint": "^9.13.0",
    "jsdom": "^25.0.1",
    "msw": "^2.6.0",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.14",
    "tsx": "^4.19.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.10",
    "vitest": "^2.1.3"
  }
}
```

- [ ] **Step 2: Write Vite config**

`AgentLens/web/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../src/agentlens/web_assets"),
    emptyOutDir: false,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5757",
      "/healthz": "http://127.0.0.1:5757",
      "/openapi.json": "http://127.0.0.1:5757",
      "/docs": "http://127.0.0.1:5757",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
});
```

- [ ] **Step 3: Write TypeScript and Tailwind config**

`AgentLens/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "jsx": "react-jsx",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": false,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src", "scripts"]
}
```

`AgentLens/web/tailwind.config.ts`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sidebar: {
          bg: "#1a1d22",
          fg: "#cfd2d7",
          active: "#2b3038",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`AgentLens/web/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 4: Write the entry files**

`AgentLens/web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AgentLens</title>
  </head>
  <body class="bg-white text-zinc-900">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`AgentLens/web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; }
```

`AgentLens/web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`AgentLens/web/src/test-setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`AgentLens/web/.gitignore`:

```
node_modules/
dist/
playwright-report/
test-results/
coverage/
.vite/
```

- [ ] **Step 5: Install & verify it builds (placeholder App.tsx)**

`AgentLens/web/src/App.tsx` (placeholder; replaced in Task 22):

```tsx
export function App() {
  return <div className="p-4">AgentLens (scaffold)</div>;
}
```

```bash
cd AgentLens/web && npm install && npm run build
```
Expected: build succeeds and produces files under `AgentLens/src/agentlens/web_assets/`.

- [ ] **Step 6: Commit**

```bash
git add AgentLens/web/
git commit -m "feat(agentlens-dashboard): scaffold Vite + React 19 + TS + Tailwind frontend"
```

---

### Task 20: Type codegen from `format_snapshots/*.json`

**Files:**
- Create: `AgentLens/web/scripts/gen-types.ts`
- Create: `AgentLens/web/src/types/api.ts` (generated)
- Modify: CI later to drift-guard

- [ ] **Step 1: Write the generator**

`AgentLens/web/scripts/gen-types.ts`:

```ts
/**
 * Reads tests/fixtures/format_snapshots/*.json and emits TypeScript types
 * + zod schemas into src/types/api.ts. Run via `npm run gen-types`.
 *
 * The generator is intentionally simple — it infers from the JSON shape.
 * For full schema fidelity, run-detail consumers should also import
 * agentlens.schema.jsonschema/run.schema.json (post-v1 task).
 */
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const FIXTURES = resolve(
  process.cwd(),
  "../tests/fixtures/format_snapshots",
);
const OUT = resolve(process.cwd(), "src/types/api.ts");

type J = unknown;

function zodFor(value: J, indent = 0): string {
  const pad = "  ".repeat(indent);
  if (value === null) return "z.null()";
  if (Array.isArray(value)) {
    return value.length === 0
      ? "z.array(z.unknown())"
      : `z.array(${zodFor(value[0], indent)})`;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, J>;
    const lines = Object.entries(obj).map(
      ([k, v]) => `${pad}  ${JSON.stringify(k)}: ${zodFor(v, indent + 1)},`,
    );
    return `z.object({\n${lines.join("\n")}\n${pad}})`;
  }
  switch (typeof value) {
    case "string": return "z.string()";
    case "number": return "z.number()";
    case "boolean": return "z.boolean()";
    default: return "z.unknown()";
  }
}

function pascalCase(name: string): string {
  return name.replace(/(^|[-_])(.)/g, (_, __, c) => c.toUpperCase());
}

function main() {
  const files = readdirSync(FIXTURES).filter((f) => f.endsWith(".json"));
  const lines: string[] = [
    "// AUTOGENERATED by web/scripts/gen-types.ts. Do not edit by hand.",
    "// Run `npm run gen-types` after changing tests/fixtures/format_snapshots/*.",
    "",
    'import { z } from "zod";',
    "",
  ];
  for (const f of files) {
    const base = f.replace(/\.json$/, "");
    const name = pascalCase(base);
    const data = JSON.parse(readFileSync(join(FIXTURES, f), "utf8"));
    lines.push(`export const ${name}Schema = ${zodFor(data)};`);
    lines.push(`export type ${name} = z.infer<typeof ${name}Schema>;`);
    lines.push("");
  }
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, lines.join("\n"));
  console.log(`wrote ${OUT}`);
}

main();
```

- [ ] **Step 2: Run the generator**

```bash
cd AgentLens/web && npm run gen-types
```
Expected: `src/types/api.ts` written with one schema/type per fixture.

- [ ] **Step 3: Quick smoke test (Vitest)**

`AgentLens/web/src/types/api.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { ShowSchema } from "./api";
import fixture from "../../../tests/fixtures/format_snapshots/show.json";

describe("generated ShowSchema", () => {
  it("parses the fixture", () => {
    expect(() => ShowSchema.parse(fixture)).not.toThrow();
  });
});
```

```bash
cd AgentLens/web && npx vitest run src/types/api.test.ts
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add AgentLens/web/scripts/gen-types.ts AgentLens/web/src/types/api.ts AgentLens/web/src/types/api.test.ts
git commit -m "feat(agentlens-dashboard): zod type codegen from format_snapshots/*.json"
```

---

### Task 21: shadcn-style UI primitives

**Files:**
- Create: `AgentLens/web/src/components/ui/button.tsx`
- Create: `AgentLens/web/src/components/ui/card.tsx`
- Create: `AgentLens/web/src/components/ui/badge.tsx`
- Create: `AgentLens/web/src/components/ui/tabs.tsx`
- Create: `AgentLens/web/src/components/ui/dialog.tsx`
- Create: `AgentLens/web/src/components/ui/table.tsx`
- Create: `AgentLens/web/src/lib/cn.ts`

- [ ] **Step 1: Class-name helper**

`AgentLens/web/src/lib/cn.ts`:

```ts
import classNames from "classnames";

export const cn = classNames;
```

- [ ] **Step 2: Button**

`AgentLens/web/src/components/ui/button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "ghost" | "outline";

export function Button({
  variant = "default",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm transition",
        variant === "default" &&
          "bg-zinc-900 text-white hover:bg-zinc-800 disabled:opacity-50",
        variant === "ghost" && "hover:bg-zinc-100",
        variant === "outline" && "border border-zinc-200 hover:bg-zinc-50",
        className,
      )}
      {...props}
    />
  );
}
```

- [ ] **Step 3: Card**

`AgentLens/web/src/components/ui/card.tsx`:

```tsx
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-zinc-200 bg-white shadow-sm",
        className,
      )}
      {...p}
    />
  );
}

export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...p} />;
}
```

- [ ] **Step 4: Badge**

`AgentLens/web/src/components/ui/badge.tsx`:

```tsx
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Tone = "default" | "success" | "warning" | "danger" | "info" | "muted";

const toneClass: Record<Tone, string> = {
  default: "bg-zinc-100 text-zinc-700",
  success: "bg-green-100 text-green-800",
  warning: "bg-amber-100 text-amber-800",
  danger: "bg-red-100 text-red-800",
  info: "bg-indigo-100 text-indigo-800",
  muted: "bg-zinc-200 text-zinc-600",
};

export function Badge({
  tone = "default",
  className,
  ...p
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        toneClass[tone],
        className,
      )}
      {...p}
    />
  );
}
```

- [ ] **Step 5: Tabs (Radix wrapper)**

`AgentLens/web/src/components/ui/tabs.tsx`:

```tsx
import * as RT from "@radix-ui/react-tabs";
import { cn } from "@/lib/cn";

export const Tabs = RT.Root;

export function TabsList({ className, ...p }: RT.TabsListProps) {
  return (
    <RT.List
      className={cn("flex gap-1 border-b border-zinc-200", className)}
      {...p}
    />
  );
}

export function TabsTrigger({ className, ...p }: RT.TabsTriggerProps) {
  return (
    <RT.Trigger
      className={cn(
        "px-3 py-2 text-sm text-zinc-600 hover:text-zinc-900",
        "data-[state=active]:text-zinc-900 data-[state=active]:border-b-2 data-[state=active]:border-zinc-900 -mb-px",
        className,
      )}
      {...p}
    />
  );
}

export function TabsContent({ className, ...p }: RT.TabsContentProps) {
  return <RT.Content className={cn("py-3", className)} {...p} />;
}
```

- [ ] **Step 6: Dialog (Radix wrapper)**

`AgentLens/web/src/components/ui/dialog.tsx`:

```tsx
import * as RD from "@radix-ui/react-dialog";
import { cn } from "@/lib/cn";

export const Dialog = RD.Root;
export const DialogTrigger = RD.Trigger;
export const DialogClose = RD.Close;

export function DialogContent({ className, children, ...p }: RD.DialogContentProps) {
  return (
    <RD.Portal>
      <RD.Overlay className="fixed inset-0 bg-black/30" />
      <RD.Content
        className={cn(
          "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
          "bg-white rounded-lg shadow-lg p-4 max-w-lg w-[90vw]",
          className,
        )}
        {...p}
      >
        {children}
      </RD.Content>
    </RD.Portal>
  );
}
```

- [ ] **Step 7: Table**

`AgentLens/web/src/components/ui/table.tsx`:

```tsx
import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return (
    <table className={cn("w-full border-collapse text-sm", className)} {...p} />
  );
}
export function THead(p: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="bg-zinc-50 text-xs uppercase text-zinc-500" {...p} />;
}
export function TBody(p: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...p} />;
}
export function TR({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-t border-zinc-100", className)} {...p} />;
}
export function TH({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("text-left px-3 py-2 font-medium", className)} {...p} />;
}
export function TD({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-2", className)} {...p} />;
}
```

- [ ] **Step 8: Smoke test build**

```bash
cd AgentLens/web && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add AgentLens/web/src/components/ui/ AgentLens/web/src/lib/cn.ts
git commit -m "feat(agentlens-dashboard): shadcn-style UI primitives (Button/Card/Badge/Tabs/Dialog/Table)"
```

---

### Task 22: AppShell + Sidebar + Router + QueryClient

**Files:**
- Create: `AgentLens/web/src/components/layout/app-shell.tsx`
- Create: `AgentLens/web/src/components/layout/sidebar.tsx`
- Create: `AgentLens/web/src/components/layout/top-bar.tsx`
- Modify: `AgentLens/web/src/App.tsx`

- [ ] **Step 1: AppShell + Sidebar + TopBar**

`AgentLens/web/src/components/layout/sidebar.tsx`:

```tsx
import { Link } from "react-router-dom";

export function Sidebar() {
  return (
    <aside className="w-[230px] bg-sidebar-bg text-sidebar-fg flex flex-col p-3">
      <div className="font-bold">AgentLens</div>
      <div className="text-[10px] opacity-50 mb-4">v0.1.0 · schema v1</div>
      <nav className="flex flex-col gap-1 text-sm">
        <Link className="hover:underline" to="/">Runs</Link>
        <Link className="hover:underline" to="/failures">Failures</Link>
        <Link className="hover:underline" to="/risks">Risks</Link>
      </nav>
      <div className="mt-auto pt-3 border-t border-zinc-700 text-[11px] opacity-70">
        doctor: <span className="text-green-400">●</span> OK
      </div>
    </aside>
  );
}
```

`AgentLens/web/src/components/layout/top-bar.tsx`:

```tsx
export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200">
      <div>
        <div className="text-lg font-semibold">{title}</div>
        {subtitle && <div className="text-xs text-zinc-500">{subtitle}</div>}
      </div>
    </div>
  );
}
```

`AgentLens/web/src/components/layout/app-shell.tsx`:

```tsx
import { Outlet } from "react-router-dom";
import { Sidebar } from "./sidebar";

export function AppShell() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 bg-zinc-50 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Replace placeholder App.tsx with real router**

`AgentLens/web/src/App.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
} from "react-router-dom";
import { AppShell } from "./components/layout/app-shell";

const qc = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 2, refetchOnWindowFocus: false },
  },
});

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <div className="p-6">Runs list (todo)</div> },
      { path: "/runs/:runId", element: <div className="p-6">Run detail (todo)</div> },
      { path: "/workspaces/:wsId", element: <div className="p-6">Workspace (todo)</div> },
      { path: "/empty", element: <div className="p-6">Empty (todo)</div> },
      { path: "*", element: <Navigate to="/" /> },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: Build smoke**

```bash
cd AgentLens/web && npm run build
```
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add AgentLens/web/src/components/layout/ AgentLens/web/src/App.tsx
git commit -m "feat(agentlens-dashboard): AppShell + Sidebar + TopBar + QueryClient + Router"
```

---

## M5 — Frontend Pages

### Task 23: `api/client.ts` and per-resource hooks

**Files:**
- Create: `AgentLens/web/src/api/client.ts`
- Create: `AgentLens/web/src/api/meta.ts`
- Create: `AgentLens/web/src/api/runs.ts`
- Create: `AgentLens/web/src/api/workspaces.ts`
- Create: `AgentLens/web/src/api/failures.ts`
- Create: `AgentLens/web/src/api/doctor.ts`

- [ ] **Step 1: HTTP client**

`AgentLens/web/src/api/client.ts`:

```ts
export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  const ct = r.headers.get("content-type") ?? "";
  if (!r.ok) {
    const detail = ct.includes("problem+json") ? await r.json().catch(() => null) : null;
    throw new ApiError(r.status, `${r.status} ${r.statusText}`, detail);
  }
  if (ct.includes("application/x-ndjson")) {
    const text = await r.text();
    return text
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => JSON.parse(l)) as unknown as T;
  }
  return (await r.json()) as T;
}
```

- [ ] **Step 2: Per-resource hooks**

`AgentLens/web/src/api/meta.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";

export type Meta = {
  agentlens_version: string;
  schema_version: string;
  store_path: string;
  store_exists: boolean;
  demo_mode: boolean;
};

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => apiGet<Meta>("/api/v1/meta") });
}
```

`AgentLens/web/src/api/runs.ts`:

```ts
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";

export type RunRow = {
  run_id: string;
  workspace_id: string;
  workspace_short?: string;
  agent_name?: string;
  agent_outcome?: string;
  eval_status?: string;
  sealed_phase?: string;
  started_at?: string;
  ended_at?: string;
};

export type RunsPage = { items: RunRow[]; next_cursor: string | null };

export type RunsFilters = {
  workspace_id?: string;
  agent?: string;
  eval_status?: string;
  agent_outcome?: string;
  since_days?: number;
  limit?: number;
};

function qs(p: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  });
  const out = search.toString();
  return out ? `?${out}` : "";
}

export function useRuns(filters: RunsFilters = {}) {
  return useInfiniteQuery({
    queryKey: ["runs", filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      apiGet<RunsPage>(`/api/v1/runs${qs({ ...filters, cursor: pageParam })}`),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    enabled: !!runId,
    queryFn: () => apiGet<Record<string, unknown>>(`/api/v1/runs/${runId}`),
  });
}

export function useRunEvents(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-events", runId],
    enabled: !!runId,
    queryFn: () =>
      apiGet<Array<Record<string, unknown>>>(`/api/v1/runs/${runId}/events`),
  });
}

export function useRunFailures(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-failures", runId],
    enabled: !!runId,
    queryFn: () =>
      apiGet<Array<Record<string, unknown>>>(`/api/v1/runs/${runId}/failures`),
  });
}
```

`AgentLens/web/src/api/workspaces.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";

export type Workspace = {
  workspace_id: string;
  workspace_short: string;
  id_basis: string;
  run_count: number;
  latest_started_at: string | null;
};

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => apiGet<Workspace[]>("/api/v1/workspaces"),
  });
}

export function useWorkspace(id: string | undefined) {
  return useQuery({
    queryKey: ["workspace", id],
    enabled: !!id,
    queryFn: () =>
      apiGet<Record<string, unknown>>(`/api/v1/workspaces/${id}`),
  });
}
```

`AgentLens/web/src/api/failures.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";

export function useGlobalFailures(workspace_id?: string) {
  return useQuery({
    queryKey: ["failures", workspace_id],
    queryFn: () =>
      apiGet<Array<Record<string, unknown>>>(
        `/api/v1/failures${workspace_id ? `?workspace_id=${workspace_id}` : ""}`,
      ),
  });
}

export function useGlobalRisks(workspace_id?: string) {
  return useQuery({
    queryKey: ["risks", workspace_id],
    queryFn: () =>
      apiGet<Array<Record<string, unknown>>>(
        `/api/v1/risks${workspace_id ? `?workspace_id=${workspace_id}` : ""}`,
      ),
  });
}
```

`AgentLens/web/src/api/doctor.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";

export function useDoctor() {
  return useQuery({
    queryKey: ["doctor"],
    refetchInterval: 30_000,
    queryFn: () => apiGet<Record<string, unknown>>("/api/v1/doctor"),
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add AgentLens/web/src/api/
git commit -m "feat(agentlens-dashboard): typed API client + TanStack Query hooks per resource"
```

---

### Task 24: Empty state route (3-card onboarding)

**Files:**
- Create: `AgentLens/web/src/routes/empty.tsx`
- Modify: `AgentLens/web/src/App.tsx`

- [ ] **Step 1: Implement empty route**

`AgentLens/web/src/routes/empty.tsx`:

```tsx
import { Card, CardBody } from "@/components/ui/card";
import { Play, Plug, Stethoscope } from "lucide-react";

export function EmptyRoute() {
  return (
    <div className="min-h-full flex flex-col items-center justify-center px-6">
      <div className="text-3xl font-light text-zinc-700">Your store is empty</div>
      <div className="text-zinc-500 mb-8">
        Record your first agent run, or load demo data to look around.
      </div>
      <div className="flex flex-wrap gap-4 justify-center max-w-3xl">
        <Card className="w-56 cursor-pointer hover:shadow">
          <CardBody className="text-center">
            <Play className="mx-auto mb-2" />
            <div className="font-semibold mb-1">Load demo data</div>
            <div className="text-xs text-zinc-500">
              Restart with <code>--demo</code> or click here
            </div>
          </CardBody>
        </Card>
        <Card className="w-56">
          <CardBody className="text-center">
            <Plug className="mx-auto mb-2" />
            <div className="font-semibold mb-1">Install shim</div>
            <div className="text-xs text-zinc-500">
              <code>agentlens install claude</code>
            </div>
          </CardBody>
        </Card>
        <Card className="w-56">
          <CardBody className="text-center">
            <Stethoscope className="mx-auto mb-2" />
            <div className="font-semibold mb-1">Run doctor</div>
            <div className="text-xs text-zinc-500">check integrations</div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire route in App**

Replace the `/empty` placeholder in `AgentLens/web/src/App.tsx`:

```tsx
{ path: "/empty", element: <EmptyRoute /> },
```

Add import at top:

```tsx
import { EmptyRoute } from "./routes/empty";
```

- [ ] **Step 3: Smoke build**

```bash
cd AgentLens/web && npm run build
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add AgentLens/web/src/routes/empty.tsx AgentLens/web/src/App.tsx
git commit -m "feat(agentlens-dashboard): empty-state route with 3-card onboarding"
```

---

### Task 25: Runs list route — table with filters and false-success highlight

**Files:**
- Create: `AgentLens/web/src/routes/runs-list.tsx`
- Create: `AgentLens/web/src/components/run-list-table.tsx`
- Create: `AgentLens/web/src/lib/format.ts`
- Modify: `AgentLens/web/src/App.tsx`

- [ ] **Step 1: Format helpers**

`AgentLens/web/src/lib/format.ts`:

```ts
export function relativeFromNow(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function durationOf(startedAt?: string, endedAt?: string): string {
  if (!startedAt || !endedAt) return "—";
  const sec = Math.max(0, Math.floor((Date.parse(endedAt) - Date.parse(startedAt)) / 1000));
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${(sec % 60).toString().padStart(2, "0")}s`;
}
```

- [ ] **Step 2: Run list table**

`AgentLens/web/src/components/run-list-table.tsx`:

```tsx
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table";
import { durationOf, relativeFromNow } from "@/lib/format";
import type { RunRow } from "@/api/runs";

function isFalseSuccess(r: RunRow): boolean {
  return r.agent_outcome === "success" && r.eval_status === "failed";
}

export function RunListTable({ runs }: { runs: RunRow[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Started</TH>
          <TH>Agent</TH>
          <TH>Outcome</TH>
          <TH>Eval</TH>
          <TH>Duration</TH>
          <TH>Run</TH>
        </TR>
      </THead>
      <TBody>
        {runs.map((r) => (
          <TR
            key={r.run_id}
            className={isFalseSuccess(r) ? "bg-red-50" : ""}
          >
            <TD>{relativeFromNow(r.started_at)}</TD>
            <TD><Badge tone="info">{r.agent_name ?? "unknown"}</Badge></TD>
            <TD>{r.agent_outcome ?? "—"}</TD>
            <TD className={r.eval_status === "failed" ? "text-red-700 font-semibold" : ""}>
              {r.eval_status ?? "—"}
            </TD>
            <TD>{durationOf(r.started_at, r.ended_at)}</TD>
            <TD className="font-mono text-xs text-zinc-500">
              <Link to={`/runs/${r.run_id}`} className="hover:underline">{r.run_id}</Link>
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
```

- [ ] **Step 3: Runs list route**

`AgentLens/web/src/routes/runs-list.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import { useRuns, type RunsFilters } from "@/api/runs";
import { useMeta } from "@/api/meta";
import { RunListTable } from "@/components/run-list-table";
import { Navigate } from "react-router-dom";
import { useState } from "react";

export function RunsListRoute() {
  const meta = useMeta();
  const [filters] = useState<RunsFilters>({});
  const runs = useRuns(filters);

  if (meta.data && !meta.data.store_exists) return <Navigate to="/empty" replace />;

  if (runs.isLoading) return <div className="p-6">Loading…</div>;
  if (runs.error) return <div className="p-6 text-red-600">Failed to load runs.</div>;

  const items = runs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-3">
        <div className="text-lg font-semibold">Runs</div>
        <div className="text-xs text-zinc-500">
          showing {items.length}
          {runs.hasNextPage ? "+" : ""}
        </div>
      </div>
      <RunListTable runs={items} />
      {runs.hasNextPage && (
        <div className="mt-3 text-center">
          <Button onClick={() => runs.fetchNextPage()} variant="outline">
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire route**

Replace the `/` placeholder in `AgentLens/web/src/App.tsx`:

```tsx
{ path: "/", element: <RunsListRoute /> },
```

```tsx
import { RunsListRoute } from "./routes/runs-list";
```

- [ ] **Step 5: Smoke build**

```bash
cd AgentLens/web && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add AgentLens/web/src/routes/runs-list.tsx AgentLens/web/src/components/run-list-table.tsx AgentLens/web/src/lib/format.ts AgentLens/web/src/App.tsx
git commit -m "feat(agentlens-dashboard): runs list page with false-success row highlight"
```

---

### Task 26: outcome ↔ eval pills + failures panel components

**Files:**
- Create: `AgentLens/web/src/components/outcome-eval-pills.tsx`
- Create: `AgentLens/web/src/components/failures-panel.tsx`

- [ ] **Step 1: Outcome/Eval pills**

`AgentLens/web/src/components/outcome-eval-pills.tsx`:

```tsx
import { Card, CardBody } from "@/components/ui/card";

export function OutcomeEvalPills({
  agentOutcome,
  evalStatus,
  reason,
  failureCount,
}: {
  agentOutcome?: string;
  evalStatus?: string;
  reason?: string;
  failureCount?: number;
}) {
  const success = agentOutcome === "success";
  const failed = evalStatus === "failed";
  return (
    <Card>
      <CardBody className="flex gap-6">
        <div className="flex-1 border-r border-zinc-200 pr-6">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            Agent claims
          </div>
          <div
            className={`text-xl font-semibold mt-1 ${
              success ? "text-green-700" : "text-red-700"
            }`}
          >
            {success ? "✅ SUCCESS" : `❌ ${agentOutcome ?? "unknown"}`}
          </div>
          {reason && <div className="text-xs text-zinc-500 mt-1">reason: {reason}</div>}
        </div>
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            Evaluator says
          </div>
          <div
            className={`text-xl font-semibold mt-1 ${
              failed ? "text-red-700" : "text-green-700"
            }`}
          >
            {failed ? "❌ FAILED" : `✅ ${evalStatus ?? "unknown"}`}
          </div>
          {failureCount !== undefined && failed && (
            <div className="text-xs text-red-700 mt-1">
              {failureCount} failures · discrepancy
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 2: Failures panel**

`AgentLens/web/src/components/failures-panel.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";

type Failure = {
  category?: string;
  severity?: string;
  confidence?: number;
  blame_scope?: string;
  recoverability?: string;
  summary?: string;
  evidence?: string[];
};

function severityTone(s?: string): "danger" | "warning" | "muted" {
  if (s === "high") return "danger";
  if (s === "medium") return "warning";
  return "muted";
}

export function FailuresPanel({
  failures,
  onEvidenceClick,
}: {
  failures: Failure[];
  onEvidenceClick?: (sha: string) => void;
}) {
  if (failures.length === 0) {
    return <div className="text-sm text-zinc-500">No failures.</div>;
  }
  return (
    <div className="flex flex-col gap-3">
      {failures.map((f, i) => (
        <div
          key={i}
          className={`border-l-4 pl-3 py-2 ${
            f.severity === "high"
              ? "border-red-600 bg-red-50"
              : f.severity === "medium"
                ? "border-amber-600 bg-amber-50"
                : "border-zinc-300 bg-zinc-50"
          }`}
        >
          <div className="flex flex-wrap gap-2 items-center mb-1">
            <Badge tone={severityTone(f.severity)}>{f.severity?.toUpperCase()}</Badge>
            <code className="text-xs">{f.category}</code>
            {f.confidence !== undefined && (
              <span className="text-xs text-zinc-500">confidence {f.confidence}</span>
            )}
            {f.blame_scope && (
              <span className="text-xs text-zinc-500">blame: {f.blame_scope}</span>
            )}
            {f.recoverability && (
              <span className="text-xs text-zinc-500">recovery: {f.recoverability}</span>
            )}
          </div>
          {f.summary && <div className="text-sm">{f.summary}</div>}
          {f.evidence && f.evidence.length > 0 && (
            <div className="text-xs text-zinc-600 mt-1">
              evidence:{" "}
              {f.evidence.map((e, j) => (
                <button
                  key={j}
                  type="button"
                  className="font-mono text-indigo-600 hover:underline mr-2"
                  onClick={() => onEvidenceClick?.(e)}
                >
                  {e.slice(0, 24)}…
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Smoke build**

```bash
cd AgentLens/web && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add AgentLens/web/src/components/outcome-eval-pills.tsx AgentLens/web/src/components/failures-panel.tsx
git commit -m "feat(agentlens-dashboard): OutcomeEvalPills + FailuresPanel components"
```

---

### Task 27: Transcript view (NDJSON)

**Files:**
- Create: `AgentLens/web/src/components/transcript-view.tsx`

- [ ] **Step 1: Implement**

`AgentLens/web/src/components/transcript-view.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";

type Event = Record<string, unknown> & { type?: string; _error?: string; line?: number };

const typeTone: Record<string, "success" | "info" | "warning" | "danger" | "muted"> = {
  start: "success",
  final: "success",
  seal: "warning",
  mark: "info",
  "cmd.start": "info",
  "cmd.end": "muted",
};

function relTime(idx: number): string {
  // Placeholder: in v1 we don't compute true relative time per event without
  // a base anchor. Use index for now; replace with timestamp delta in v1.x.
  return `#${idx + 1}`;
}

export function TranscriptView({
  events,
  highlightSha,
}: {
  events: Event[];
  highlightSha?: string;
}) {
  return (
    <div className="font-mono text-xs leading-relaxed">
      {events.map((e, idx) => {
        if (e._error === "parse") {
          return (
            <div key={idx} className="text-red-700 py-1 border-b border-zinc-100">
              ⚠ unparseable line {String(e.line ?? "?")}
            </div>
          );
        }
        const t = String(e.type ?? "event");
        const isHit =
          highlightSha && JSON.stringify(e).includes(highlightSha);
        return (
          <div
            key={idx}
            className={`flex gap-2 items-center py-1 border-b border-zinc-100 ${
              isHit ? "bg-yellow-50" : ""
            }`}
          >
            <span className="w-12 text-zinc-400">{relTime(idx)}</span>
            <Badge tone={typeTone[t] ?? "muted"}>{t}</Badge>
            <span className="truncate text-zinc-700">
              {JSON.stringify(
                Object.fromEntries(
                  Object.entries(e).filter(([k]) => k !== "type" && k !== "_error" && k !== "line"),
                ),
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Smoke build**

```bash
cd AgentLens/web && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add AgentLens/web/src/components/transcript-view.tsx
git commit -m "feat(agentlens-dashboard): TranscriptView (NDJSON renderer with parse-error markers + evidence highlight)"
```

---

### Task 28: Run detail route + Workspace route + doctor footer

**Files:**
- Create: `AgentLens/web/src/routes/run-detail.tsx`
- Create: `AgentLens/web/src/routes/workspace.tsx`
- Create: `AgentLens/web/src/components/doctor-footer.tsx`
- Create: `AgentLens/web/src/components/redaction-badge.tsx`
- Modify: `AgentLens/web/src/components/layout/sidebar.tsx` (add doctor footer)
- Modify: `AgentLens/web/src/App.tsx`

- [ ] **Step 1: Run detail route**

`AgentLens/web/src/routes/run-detail.tsx`:

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useRun, useRunEvents, useRunFailures } from "@/api/runs";
import { OutcomeEvalPills } from "@/components/outcome-eval-pills";
import { FailuresPanel } from "@/components/failures-panel";
import { TranscriptView } from "@/components/transcript-view";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

export function RunDetailRoute() {
  const { runId } = useParams();
  const run = useRun(runId);
  const events = useRunEvents(runId);
  const failures = useRunFailures(runId);
  const [highlightSha, setHighlightSha] = useState<string | undefined>();
  const [tab, setTab] = useState<string>();

  if (run.isLoading) return <div className="p-6">Loading…</div>;
  if (run.error) return <div className="p-6 text-red-600">Run not found.</div>;

  const r = run.data as Record<string, any>;
  const failureList = (r?.failures ?? failures.data ?? []) as Array<Record<string, any>>;
  const defaultTab = failureList.length > 0 ? "failures" : "transcript";
  const seal = r?.manifest_seal ?? {};

  return (
    <div className="p-6">
      <div className="text-xs text-zinc-500">workspaces / {r?.workspace_short ?? r?.workspace_id}</div>
      <div className="font-mono text-base mt-1">{runId}</div>

      <div className="mt-3">
        <OutcomeEvalPills
          agentOutcome={r?.agent_outcome}
          evalStatus={r?.eval_status}
          reason={r?.reason}
          failureCount={failureList.length}
        />
      </div>

      <div className="flex gap-4 mt-3 text-xs text-zinc-600">
        <span><b className="text-zinc-900">{r?.agent_name ?? "unknown"}</b></span>
        <span>sealed: {seal.phase ?? "—"}</span>
        {seal.manifest_digest && (
          <span>
            manifest: <code className="text-[10px]">{String(seal.manifest_digest).slice(0, 24)}…</code>{" "}
            {seal.integrity === "broken" && (
              <span className="text-amber-700">⚠ integrity broken</span>
            )}
          </span>
        )}
        {r?.partial && <span className="text-amber-700">partial run</span>}
      </div>

      <Tabs value={tab ?? defaultTab} onValueChange={setTab} className="mt-5">
        <TabsList>
          <TabsTrigger value="failures">Failures ({failureList.length})</TabsTrigger>
          <TabsTrigger value="risks">Risks ({(r?.risks ?? []).length})</TabsTrigger>
          <TabsTrigger value="transcript">Transcript</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>
        <TabsContent value="failures">
          <FailuresPanel
            failures={failureList}
            onEvidenceClick={(sha) => {
              setHighlightSha(sha);
              setTab("transcript");
            }}
          />
        </TabsContent>
        <TabsContent value="risks">
          <FailuresPanel failures={(r?.risks ?? []) as Array<Record<string, any>>} />
        </TabsContent>
        <TabsContent value="transcript">
          {events.isLoading ? (
            <div>Loading events…</div>
          ) : (
            <TranscriptView events={(events.data as Array<Record<string, unknown>>) ?? []} highlightSha={highlightSha} />
          )}
        </TabsContent>
        <TabsContent value="metadata">
          <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(r, null, 2)}</pre>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 2: Workspace route**

`AgentLens/web/src/routes/workspace.tsx`:

```tsx
import { useParams } from "react-router-dom";
import { useWorkspace } from "@/api/workspaces";
import { RunListTable } from "@/components/run-list-table";

export function WorkspaceRoute() {
  const { wsId } = useParams();
  const ws = useWorkspace(wsId);

  if (ws.isLoading) return <div className="p-6">Loading…</div>;
  if (ws.error) return <div className="p-6 text-red-600">Workspace not found.</div>;

  const w = ws.data as Record<string, any>;
  return (
    <div className="p-6">
      <div className="text-lg font-semibold">{w.workspace_short ?? w.workspace_id}</div>
      <div className="text-xs text-zinc-500 mb-4">
        {w.id_basis} · {w.run_count} runs · pass rate{" "}
        {w.eval_pass_rate_30d !== null ? `${Math.round(w.eval_pass_rate_30d * 100)}%` : "—"}
      </div>
      <RunListTable runs={(w.recent_runs ?? []) as any} />
    </div>
  );
}
```

- [ ] **Step 3: Doctor footer + redaction badge**

`AgentLens/web/src/components/doctor-footer.tsx`:

```tsx
import { useDoctor } from "@/api/doctor";

export function DoctorFooter() {
  const d = useDoctor();
  if (d.isLoading) return <div className="text-[11px] opacity-70">doctor: …</div>;
  if (d.error) return <div className="text-[11px] text-red-400">doctor: error</div>;
  const warnings = (d.data?.warnings as unknown[]) ?? [];
  const dot = warnings.length === 0 ? "text-green-400" : "text-amber-400";
  return (
    <div className="text-[11px]">
      <span className={dot}>●</span> doctor: {warnings.length === 0 ? "OK" : `${warnings.length} warnings`}
    </div>
  );
}
```

`AgentLens/web/src/components/redaction-badge.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";

export function RedactionBadge({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <Badge tone="warning">redacted view</Badge>;
}
```

- [ ] **Step 4: Wire DoctorFooter into Sidebar**

Replace the doctor placeholder line in `AgentLens/web/src/components/layout/sidebar.tsx`:

```tsx
import { DoctorFooter } from "@/components/doctor-footer";
// ...
      <div className="mt-auto pt-3 border-t border-zinc-700">
        <DoctorFooter />
      </div>
```

- [ ] **Step 5: Wire routes in App**

In `AgentLens/web/src/App.tsx` replace placeholder elements:

```tsx
import { RunDetailRoute } from "./routes/run-detail";
import { WorkspaceRoute } from "./routes/workspace";
```

```tsx
{ path: "/runs/:runId", element: <RunDetailRoute /> },
{ path: "/workspaces/:wsId", element: <WorkspaceRoute /> },
```

- [ ] **Step 6: Smoke build**

```bash
cd AgentLens/web && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add AgentLens/web/src/routes/ AgentLens/web/src/components/doctor-footer.tsx AgentLens/web/src/components/redaction-badge.tsx AgentLens/web/src/components/layout/sidebar.tsx AgentLens/web/src/App.tsx
git commit -m "feat(agentlens-dashboard): run detail + workspace routes + doctor footer + redaction badge"
```

---

## M6 — Frontend Tests

### Task 29: Vitest component unit tests

**Files:**
- Create: `AgentLens/web/src/lib/format.test.ts`
- Create: `AgentLens/web/src/components/outcome-eval-pills.test.tsx`
- Create: `AgentLens/web/src/components/failures-panel.test.tsx`
- Create: `AgentLens/web/src/components/transcript-view.test.tsx`

- [ ] **Step 1: Write tests**

`AgentLens/web/src/lib/format.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { durationOf, relativeFromNow } from "./format";

describe("format.relativeFromNow", () => {
  it("returns em-dash for empty input", () => {
    expect(relativeFromNow(null)).toBe("—");
    expect(relativeFromNow(undefined)).toBe("—");
  });
  it("returns seconds for recent times", () => {
    const iso = new Date(Date.now() - 10_000).toISOString();
    expect(relativeFromNow(iso)).toMatch(/\d+s ago/);
  });
});

describe("format.durationOf", () => {
  it("returns em-dash when fields missing", () => {
    expect(durationOf()).toBe("—");
  });
  it("computes seconds when under a minute", () => {
    expect(durationOf("2026-01-01T00:00:00Z", "2026-01-01T00:00:30Z")).toBe("30s");
  });
  it("formats Xm0Ys", () => {
    expect(durationOf("2026-01-01T00:00:00Z", "2026-01-01T00:01:30Z")).toBe("1m30s");
  });
});
```

`AgentLens/web/src/components/outcome-eval-pills.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OutcomeEvalPills } from "./outcome-eval-pills";

describe("OutcomeEvalPills", () => {
  it("shows discrepancy when outcome=success but eval=failed", () => {
    render(<OutcomeEvalPills agentOutcome="success" evalStatus="failed" failureCount={2} />);
    expect(screen.getByText(/SUCCESS/)).toBeInTheDocument();
    expect(screen.getByText(/FAILED/)).toBeInTheDocument();
    expect(screen.getByText(/discrepancy/)).toBeInTheDocument();
  });

  it("does not show discrepancy when both pass", () => {
    render(<OutcomeEvalPills agentOutcome="success" evalStatus="passed" />);
    expect(screen.queryByText(/discrepancy/)).not.toBeInTheDocument();
  });
});
```

`AgentLens/web/src/components/failures-panel.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FailuresPanel } from "./failures-panel";

describe("FailuresPanel", () => {
  it("renders empty state", () => {
    render(<FailuresPanel failures={[]} />);
    expect(screen.getByText(/No failures/)).toBeInTheDocument();
  });

  it("invokes onEvidenceClick when sha link is clicked", () => {
    const onEvidenceClick = vi.fn();
    render(
      <FailuresPanel
        failures={[
          { category: "X", severity: "high", summary: "boom", evidence: ["sha256:abc"] },
        ]}
        onEvidenceClick={onEvidenceClick}
      />,
    );
    fireEvent.click(screen.getByText(/sha256:abc/));
    expect(onEvidenceClick).toHaveBeenCalledWith("sha256:abc");
  });
});
```

`AgentLens/web/src/components/transcript-view.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TranscriptView } from "./transcript-view";

describe("TranscriptView", () => {
  it("renders parse-error markers inline", () => {
    render(
      <TranscriptView
        events={[{ type: "start" }, { _error: "parse", line: 2 }, { type: "final" }]}
      />,
    );
    expect(screen.getByText(/unparseable line 2/)).toBeInTheDocument();
    expect(screen.getByText("start")).toBeInTheDocument();
    expect(screen.getByText("final")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests**

```bash
cd AgentLens/web && npx vitest run
```
Expected: PASS for all four files.

- [ ] **Step 3: Commit**

```bash
git add AgentLens/web/src/lib/format.test.ts AgentLens/web/src/components/*.test.tsx
git commit -m "test(agentlens-dashboard): vitest unit tests for format/pills/panel/transcript"
```

---

### Task 30: MSW integration tests for routes

**Files:**
- Create: `AgentLens/web/src/test-mocks/handlers.ts`
- Create: `AgentLens/web/src/integration/runs-list.test.tsx`
- Create: `AgentLens/web/src/integration/empty-state.test.tsx`

- [ ] **Step 1: MSW handlers**

`AgentLens/web/src/test-mocks/handlers.ts`:

```ts
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export function startMockServer(meta: Record<string, unknown>, items: any[] = []) {
  const server = setupServer(
    http.get("/api/v1/meta", () => HttpResponse.json(meta)),
    http.get("/api/v1/runs", () => HttpResponse.json({ items, next_cursor: null })),
    http.get("/api/v1/doctor", () =>
      HttpResponse.json({ integrations: {}, paths: {}, warnings: [] }),
    ),
  );
  server.listen({ onUnhandledRequest: "bypass" });
  return server;
}
```

- [ ] **Step 2: Runs list integration test**

`AgentLens/web/src/integration/runs-list.test.tsx`:

```tsx
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { RunsListRoute } from "@/routes/runs-list";
import { startMockServer } from "@/test-mocks/handlers";

const meta = { store_exists: true, demo_mode: false, agentlens_version: "x", schema_version: "v1", store_path: "/tmp" };
const items = [
  { run_id: "run_a", workspace_id: "ws", agent_name: "claude", agent_outcome: "success", eval_status: "passed", started_at: new Date().toISOString() },
  { run_id: "run_b", workspace_id: "ws", agent_name: "claude", agent_outcome: "success", eval_status: "failed", started_at: new Date().toISOString() },
];

const server = startMockServer(meta, items);
beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterAll(() => server.close());

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RunsListRoute", () => {
  it("renders rows and highlights the false-success row", async () => {
    render(wrap(<RunsListRoute />));
    await waitFor(() => expect(screen.getByText("run_a")).toBeInTheDocument());
    const falseRow = screen.getByText("run_b").closest("tr");
    expect(falseRow?.className).toMatch(/bg-red-50/);
  });
});
```

- [ ] **Step 3: Empty-state redirect test**

`AgentLens/web/src/integration/empty-state.test.tsx`:

```tsx
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { RunsListRoute } from "@/routes/runs-list";
import { EmptyRoute } from "@/routes/empty";
import { startMockServer } from "@/test-mocks/handlers";

const server = startMockServer(
  { store_exists: false, demo_mode: false, agentlens_version: "x", schema_version: "v1", store_path: "/tmp" },
);
beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterAll(() => server.close());

describe("Empty-store routing", () => {
  it("redirects from / to /empty when store_exists=false", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<RunsListRoute />} />
            <Route path="/empty" element={<EmptyRoute />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText(/Your store is empty/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd AgentLens/web && npx vitest run src/integration
```
Expected: PASS (2 files).

- [ ] **Step 5: Commit**

```bash
git add AgentLens/web/src/test-mocks/ AgentLens/web/src/integration/
git commit -m "test(agentlens-dashboard): MSW integration tests for runs list + empty state"
```

---

### Task 31: Playwright e2e smoke test (signature scenario)

**Files:**
- Create: `AgentLens/web/playwright.config.ts`
- Create: `AgentLens/web/tests/e2e/signature.spec.ts`
- Create: `AgentLens/web/tests/e2e/global-setup.ts`

- [ ] **Step 1: Playwright config**

`AgentLens/web/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:5757", trace: "on-first-retry" },
  webServer: {
    command:
      "cd .. && .venv/bin/python -m agentlens.cli serve --demo --port 5757 --host 127.0.0.1",
    url: "http://127.0.0.1:5757/healthz",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
```

- [ ] **Step 2: The signature scenario**

`AgentLens/web/tests/e2e/signature.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

test("signature: list → false-success → detail → evidence → transcript", async ({ page }) => {
  await page.goto("/");
  // List loads and contains at least one row marked failed
  const failedRow = page.locator("tr", { hasText: "failed" }).first();
  await expect(failedRow).toBeVisible();
  await failedRow.locator("a").click();
  // Detail page: outcome and eval pills
  await expect(page.getByText("Agent claims", { exact: false })).toBeVisible();
  await expect(page.getByText("Evaluator says", { exact: false })).toBeVisible();
  // Failures panel default
  await expect(page.getByText(/Failures/)).toBeVisible();
  // Click first sha link → transcript shows the highlighted row
  const evidenceBtn = page.locator("button", { hasText: "sha256:" }).first();
  if (await evidenceBtn.count()) {
    await evidenceBtn.click();
    await expect(page.locator(".bg-yellow-50").first()).toBeVisible();
  }
  await page.screenshot({ path: "test-results/signature.png", fullPage: true });
});
```

- [ ] **Step 3: Install Playwright browsers**

```bash
cd AgentLens/web && npx playwright install --with-deps chromium
```

- [ ] **Step 4: Build the SPA so the Python server has something to serve**

```bash
cd AgentLens/web && npm run build
```

- [ ] **Step 5: Run e2e**

```bash
cd AgentLens/web && npx playwright test
```
Expected: PASS (1 test, screenshot saved to `test-results/signature.png`).

- [ ] **Step 6: Commit**

```bash
git add AgentLens/web/playwright.config.ts AgentLens/web/tests/
git commit -m "test(agentlens-dashboard): Playwright e2e for the signature false-success scenario"
```

---

## M7 — Packaging, CI, Docs

### Task 32: Wheel packaging + static asset serving

**Review correction:** preserve `src/agentlens/web_assets/__init__.py` during `clean` and `build`; otherwise `importlib.resources.files("agentlens.web_assets")` will fail after a frontend build.

**Files:**
- Modify: `AgentLens/pyproject.toml` (package-data + license)
- Modify: `AgentLens/src/agentlens/web/app.py` (StaticFiles mount unless dev_proxy)
- Create: `AgentLens/Makefile`

- [ ] **Step 1: Update pyproject for package-data; gate license change on owner approval**

Do **not** change the current proprietary license mechanically. If the owner explicitly approves MIT publication, update top-level fields in `AgentLens/pyproject.toml` and add a matching `LICENSE` file in the same commit:

```toml
license = { text = "MIT" }
```

Replace `[tool.setuptools.package-data]`:

```toml
[tool.setuptools.package-data]
"agentlens.schema.jsonschema" = ["*.schema.json"]
"agentlens.demo_data" = ["**/*.json", "**/*.jsonl"]
"agentlens.web_assets" = ["**/*"]
```

- [ ] **Step 2: Mount StaticFiles in create_app when no dev_proxy**

Replace the dev_proxy-only mount block in `AgentLens/src/agentlens/web/app.py` with both branches:

```python
    if settings.dev_proxy:
        from agentlens.web.dev_proxy import mount_dev_proxy

        mount_dev_proxy(app, settings.dev_proxy)
    else:
        from importlib.resources import as_file, files
        from fastapi.staticfiles import StaticFiles

        pkg = files("agentlens.web_assets")
        with as_file(pkg) as p:
            if any(p.iterdir()):
                app.mount(
                    "/",
                    StaticFiles(directory=str(p), html=True),
                    name="web_assets",
                )
            else:
                @app.get("/", include_in_schema=False)
                def _missing_spa():
                    return JSONResponse(
                        {
                            "title": "SPA not built",
                            "detail": "Run `npm --prefix web run build` or use --dev-proxy.",
                        },
                        status_code=503,
                        media_type="application/problem+json",
                    )
```

- [ ] **Step 3: Makefile target**

`AgentLens/Makefile`:

```makefile
.PHONY: install test build wheel clean

install:
	uv pip install -e .[test]
	cd web && npm ci

test:
	.venv/bin/python -m pytest -q
	cd web && npx vitest run && npx playwright test

build:
	cd web && npm run build

wheel: build
	python -m build --wheel

clean:
	rm -rf web/node_modules web/.vite src/agentlens/web_assets/*
	touch src/agentlens/web_assets/__init__.py
	find . -name __pycache__ -exec rm -rf {} +
	rm -rf dist build *.egg-info
```

- [ ] **Step 4: Smoke wheel build**

```bash
cd AgentLens && python -m pip install --upgrade build && python -m build --wheel
unzip -l dist/agentlens-0.1.0-py3-none-any.whl | grep web_assets
```
Expected: lists files under `agentlens/web_assets/`.

- [ ] **Step 5: Commit**

```bash
git add AgentLens/pyproject.toml AgentLens/src/agentlens/web/app.py AgentLens/Makefile
git commit -m "feat(agentlens-dashboard): wheel package-data + StaticFiles mount + Makefile"
```

---

### Task 33: CI matrix + type-sync drift guard

**Files:**
- Create: `.github/workflows/dashboard-ci.yml`

- [ ] **Step 1: Workflow file**

`.github/workflows/dashboard-ci.yml`:

```yaml
name: dashboard-ci

on:
  push:
    paths:
      - "AgentLens/**"
  pull_request:
    paths:
      - "AgentLens/**"

jobs:
  python:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        working-directory: AgentLens
        run: |
          python -m pip install --upgrade pip
          pip install -e .[test]
      - name: Pytest
        working-directory: AgentLens
        run: pytest -q

  frontend:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [20, 22]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
      - name: Install
        working-directory: AgentLens/web
        run: npm ci
      - name: Type-sync drift guard
        working-directory: AgentLens/web
        run: |
          npm run gen-types
          git diff --exit-code src/types/api.ts
      - name: Vitest
        working-directory: AgentLens/web
        run: npx vitest run
      - name: Build
        working-directory: AgentLens/web
        run: npm run build
      - name: Playwright
        working-directory: AgentLens/web
        run: |
          npx playwright install --with-deps chromium
          # Python dep needed for the webServer command.
          python -m pip install -e ../
          npx playwright test
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/dashboard-ci.yml
git commit -m "ci: matrix for AgentLens dashboard (python 3.11-3.13 × node 20/22)"
```

---

### Task 34: README + getting-started + signature GIF placeholder

**Files:**
- Modify: `AgentLens/docs/cli.md` (add `serve` doc)
- Create: `AgentLens/docs/dashboard.md`
- Modify: `README.md` at repo root (link to dashboard docs)

- [ ] **Step 1: Dashboard doc**

`AgentLens/docs/dashboard.md`:

```markdown
# AgentLens Dashboard

A read-only web view of every run AgentLens has recorded on this machine.

## Install + first launch

```
pipx install agentlens
agentlens serve --demo
```

`--demo` boots with bundled sample runs so the UI is populated immediately.
Remove the flag to view your real `~/.agentlens` store.

## Default URL

`http://127.0.0.1:5757`

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--host` | `127.0.0.1` | Bind host. Use `0.0.0.0` only on trusted networks. |
| `--port` | `5757` | TCP port. |
| `--demo` | off | Use bundled sample runs in a temp directory. |
| `--debug` | off | Include tracebacks in error responses (local dev only). |
| `--auto-port` | off | Try `port+1..+3` if the requested port is busy. |
| `--dev-proxy URL` | none | Reverse-proxy static assets to a Vite dev server (loopback only). |
| `--allow-origin URL` | none | Add a CORS allowlist entry (repeatable). |

## What it shows

- A list of all runs, with status pills and a red highlight when
  `agent_outcome=success` but `eval_status=failed`.
- A run-detail page that puts the agent's claimed outcome next to the
  evaluator's verdict, then shows failures with linked evidence.
- A transcript view of `events.jsonl` in chronological order.
- A workspace summary with pass-rate aggregations.
- A live `doctor` status pill in the sidebar.

## What it does not do

- Authenticate users.
- Write to the store (no marking, tagging, or eval re-runs through the UI).
- Expose data over the network beyond the chosen host:port.
- Track runs across machines or in real time.
```

- [ ] **Step 2: Append serve section to docs/cli.md**

In `AgentLens/docs/cli.md`, add after the existing command reference:

```markdown
## `agentlens serve`

Boot the dashboard. See [dashboard.md](dashboard.md) for full options.

```
agentlens serve [--host HOST] [--port PORT] [--demo] [--debug]
                [--auto-port] [--dev-proxy URL] [--allow-origin URL]...
```
```

- [ ] **Step 3: Repo-root README pointer**

Append to `README.md`:

```markdown
## Dashboard

See `AgentLens/docs/dashboard.md`. Launch with:

```
agentlens serve --demo
```
```

- [ ] **Step 4: Commit**

```bash
git add AgentLens/docs/dashboard.md AgentLens/docs/cli.md README.md
git commit -m "docs(agentlens-dashboard): dashboard getting-started + CLI reference"
```

---

## Final Verification

After Task 34 is committed:

```bash
cd AgentLens
.venv/bin/python -m pytest -q
cd web && npx vitest run && npm run build && npx playwright test
cd .. && python -m build --wheel
```

Expected:
- All Python tests pass (existing 426 + new ~25).
- All Vitest tests pass.
- E2E smoke passes; `test-results/signature.png` exists.
- Wheel build succeeds and includes `agentlens/web_assets/`.

Manual smoke:

```bash
pipx install --force ./dist/agentlens-0.1.0-py3-none-any.whl
agentlens serve --demo
# Open http://127.0.0.1:5757 in a browser; verify the false-success row is visible.
```
