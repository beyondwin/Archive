# AgentLens Dashboard — v1 Design Spec

| | |
|---|---|
| Date | 2026-05-19 |
| Author | kws |
| Status | Draft → User review |
| Supersedes | n/a (new component) |
| Successor of | `AgentLens/docs/adr/agentlens_architecture_proposal.md` §16 (deferred Dashboard) |

## 0. TL;DR

A **read-only web viewer** for AgentLens runs, packaged as `agentlens serve`. Single FastAPI process serves an embedded React SPA on `localhost:5757`. Reuses the existing `agentlens.store.query` facade — no new source of truth. Public distribution via PyPI (`pipx install agentlens && agentlens serve`).

The v1 signature demo: a runs list with a red row where `agent_outcome=success` but `eval_status=failed`. Clicking opens a run detail with the outcome ↔ eval contrast prominent and a Sentry-style failures panel with evidence links into the transcript. This single GIF showcases AgentLens's three differentiators (everyday list, trust-model split, evidence-linked taxonomy) in one screen.

## 1. Context & Motivation

AgentLens v0 (M0–M8) is complete: contract, store, deterministic evaluator, SQLite index, query CLI, process wrapper, install/shim/doctor, adapters, redaction, retention. Every read path has CLI surface with `--format json`. ADR §16 deferred a Dashboard to post-v0 because the core contract and evaluator had to settle first.

That premise now holds. The bottleneck for adoption is that *users discover failures only when they think to run `agentlens show --latest`*. A persistent viewer makes "did my last 10 agent runs really succeed?" a glanceable answer.

Going public (PyPI) raises the bar on first-touch UX: install → see something useful within 60 seconds, with zero code changes to the agent being recorded. That bar is the design driver for nearly every choice below.

## 2. Goals / Non-Goals

### Goals (v1)
- Read-only web view of all runs and their failures/risks across local workspaces.
- Make the **trust-model distinction** (`agent_outcome` vs `eval_status`) visually obvious.
- Surface **manifest seal integrity** so users can trust what they see.
- Provide a first-launch experience that works with zero recorded runs (demo data + doctor + install hint).
- Package as a single `pipx`-installable wheel including the SPA build artifact. No node required at install time.
- Ship a stable, versioned read REST API (`/api/v1`) usable by external tools.

### Non-Goals (v1, explicit)
- Authentication, multi-user, remote store access.
- Write actions of any kind (mark, seal, eval-trigger, tag, comment, gc).
- Real-time push (SSE) — hook reserved, not implemented.
- OpenTelemetry compatibility / OTLP ingest.
- Cross-run diff / regression detector (post-v1, reserved as v2 headline).
- Search across runs (deferred to v1.x).
- GC / retention management UI (CLI remains the surface).
- Live tail of in-progress runs (v1.x).
- Mobile viewport, full WCAG audit, visual regression testing.
- Dashboard widgets, charts beyond the workspace overview, alerting.

## 3. Decisions (Q1–Q5 Record)

| ID | Decision | Rejected alternatives | Rationale |
|---|---|---|---|
| Q1 | Distribution: **public** via PyPI. Audience model: **local single-user** (localhost-only). | Team/remote (out of v1 scope) | Smallest surface that still unlocks public adoption. Auth/remote deferred without code-shape lock-in. |
| Q2 | v1 signature demo: **A + B combined** — runs list with a red false-success row, click into detail with outcome↔eval contrast. | C (transcript-only — competes with Laminar's strength), D (cross-run diff — needs evaluator extension) | Differentiates AgentLens in one frame; doesn't depend on future evaluator work. |
| Q3 | Frontend stack: **React + Vite + TypeScript** (build artifact embedded in wheel). | A (vanilla, no build), B (htmx + Alpine) | C scales with planned roadmap (live tail, search, future widgets) without ad-hoc framework drift. Build cost lives in CI, not at user install. |
| Q4 | C-variant: **C1** — React 19 + Vite + TS + Tailwind + Radix primitives (shadcn-style copy-into-repo) + TanStack Query + React Router + lucide-react. | C2 (minimal modern, no Tailwind/Radix) | Once React is accepted, the marginal cost of Tailwind + Radix is small; the marginal benefit per page is large. shadcn copy-into-repo keeps runtime deps low. |
| Q5 | v1 page set: **V1-Std (5 pages)** — runs list, run detail, workspace, empty/demo, doctor footer. | V1-Min (3 pages), V1-Plus (7 pages incl. GC + search) | Workspace + doctor are necessary for the "install → first useful screen" loop. GC/search are useful but unrelated to the signature demo. |
| Tone | **Hybrid: dark sidebar + light main**. No dark-mode toggle in v1. | All-light (B), all-dark (C), auto+toggle (D) | Convention preserved; v1 keeps one token system. Toggle revisited if user feedback demands. |
| Spec path | `AgentLens/docs/spec/` (matches existing convention; `docs/superpowers/` is gitignored at root) | `AgentLens/docs/superpowers/specs/` (skill default) | Repo convention takes precedence over skill default. |

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Browser                                                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  React 19 SPA (Vite-built, embedded in wheel)            │ │
│  │   - React Router (5 routes)                              │ │
│  │   - TanStack Query (read cache, 30s stale)               │ │
│  │   - shadcn-style components (Radix + Tailwind, in-repo)  │ │
│  └────────────────────┬─────────────────────────────────────┘ │
└───────────────────────┼────────────────────────────────────────┘
                        │  fetch /api/v1/* (JSON)
                        │  + future SSE /events
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  agentlens serve  (Typer subcommand → uvicorn:5757)            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  FastAPI app                                             │ │
│  │   - StaticFiles("/")     → web_assets/  (SPA)            │ │
│  │   - APIRouter("/api/v1") → read-only endpoints           │ │
│  │   - APIRouter("/healthz")→ liveness                      │ │
│  │   - Lifespan: open SQLite read-only once, reuse          │ │
│  └────────────────────┬─────────────────────────────────────┘ │
└───────────────────────┼────────────────────────────────────────┘
                        │  reuse EXISTING facade — unchanged
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  agentlens.store.query  (UNCHANGED in v1)                      │
│   - latest / list_runs / get_run / failures / risks            │
│   - SQLite primary, full-scan fallback                         │
└────────────────────────┬───────────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────────┐
│  ~/.agentlens/                                                 │
│   - runs/<workspace_id>/<run_id>/{run,events,final,eval,       │
│       manifest}.json[l]   ← source of truth (sealed)           │
│   - index.db              ← rebuildable cache                  │
└────────────────────────────────────────────────────────────────┘
```

### Core principles
1. **Read-only strict.** Viewer never writes to the store. SQLite is opened with `mode=ro&immutable=0`. Write actions (mark, seal, gc) remain CLI-only.
2. **Reuse first.** `agentlens.store.query` functions are called as-is. JSON output shapes match the existing `tests/fixtures/format_snapshots/*.json` — API and CLI become two faces of the same contract.
3. **Single process.** SPA and API live on the same port; no CORS. Dev mode uses Vite proxy (:5173 → :5757) only.
4. **Safe defaults for public distribution.** Localhost-only by default; no auth; no write surface. `--host 0.0.0.0` triggers a visible red warning banner.
5. **Future-proof hooks.** Live tail / cross-run diff / search extend within this architecture (new SSE endpoint, new query.py function, new SPA page) without a redesign.

## 5. Repo Layout & Module Boundaries

### File tree (changes only)

```
AgentLens/
├── .gitignore                           # NEW: package-local ignores (web build artifact, vite cache, test reports)
├── pyproject.toml                       # + fastapi, uvicorn[standard], pydantic-settings
├── src/agentlens/
│   ├── cli.py                           # + register `serve` subcommand
│   ├── commands/
│   │   └── serve.py                     # NEW: Typer command, uvicorn boot
│   ├── demo_data/                       # NEW: curated subset of tests/fixtures/*_run/, shipped in wheel
│   │   └── …                            #   used by `agentlens serve --demo`
│   ├── web/                             # NEW: backend module
│   │   ├── __init__.py
│   │   ├── app.py                       #   FastAPI app factory
│   │   ├── deps.py                      #   AGENTLENS_HOME, query facade dependency
│   │   ├── errors.py                    #   RFC 7807 ProblemDetails handler
│   │   ├── settings.py                  #   pydantic-settings: port/host/demo/debug
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── runs.py                  #   /api/v1/runs, /api/v1/runs/{id}/*
│   │       ├── workspaces.py            #   /api/v1/workspaces[/{id}]
│   │       ├── failures.py              #   /api/v1/failures, /api/v1/risks
│   │       ├── doctor.py                #   /api/v1/doctor
│   │       └── meta.py                  #   /api/v1/meta
│   └── web_assets/                      # NEW: built SPA, embedded in wheel
│       └── .gitkeep                     #   (created during impl; tree exists, contents gitignored)
│
├── web/                                 # NEW: frontend source (outside Python pkg)
│   ├── package.json                     #   react@19, vite, tailwind, radix, tanstack-query, react-router, lucide
│   ├── vite.config.ts                   #   /api proxy → :5757, build outDir = ../src/agentlens/web_assets
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                      #   QueryClient + Router
│   │   ├── routes/
│   │   │   ├── runs-list.tsx
│   │   │   ├── run-detail.tsx
│   │   │   ├── workspace.tsx
│   │   │   └── empty.tsx
│   │   ├── components/
│   │   │   ├── ui/                      #   shadcn-style: Button, Card, Table, Tabs, Dialog, Badge, …
│   │   │   ├── layout/                  #   AppShell, Sidebar, TopBar
│   │   │   ├── run-list-table.tsx
│   │   │   ├── outcome-eval-pills.tsx   #   the signature widget
│   │   │   ├── transcript-view.tsx
│   │   │   ├── failures-panel.tsx
│   │   │   ├── doctor-footer.tsx
│   │   │   └── redaction-badge.tsx
│   │   ├── api/                         #   typed fetch wrappers + zod schemas
│   │   ├── types/                       #   codegen from tests/fixtures/format_snapshots/*.json
│   │   └── lib/                         #   format helpers, route paths
│   └── tests/e2e/                       #   Playwright smoke (1 spec — the signature GIF)
│
├── tests/
│   ├── unit/test_web_*.py               #   NEW
│   └── integration/test_web_e2e_*.py    #   NEW
│
└── docs/spec/
    └── 2026-05-19-agentlens-dashboard-design.md   # this file
```

### Dependency direction (top → down, no upward calls)

```
commands/serve.py
       │
       ▼
web/app.py ── web/settings.py
       │
       ▼
web/routers/*.py
       │
       ▼   (thin adapting only — no business logic)
web/deps.py
       │
       ▼   ★ line below which v1 does not modify
store/query.py  ← single source of truth for read
       │
       ▼
store/sqlite_index.py, store/manifest.py, schema/*  (unchanged)
```

### Rules
- `web/*` calls only `store.query.*` functions. No direct SQLite handles, no direct file IO.
- `web/routers/*` decides JSON shape only; zero business logic. Wraps `dict[str, Any]` from query into a `JSONResponse`, maps exceptions.
- Static asset serving happens once in `web/app.py` via `StaticFiles`. If `web_assets/` is empty (dev), a fallback HTML explains how to build or use `--dev-proxy`.

### Frontend module boundaries
- `components/ui/*`: pure presentation, no domain knowledge.
- `components/*-view.tsx`, `*-panel.tsx`: domain components receiving typed props, no fetch.
- `routes/*.tsx`: only place that fetches data and decides routing.

### Build / release flow
1. `npm --prefix web ci`
2. `npm --prefix web run build` → populates `src/agentlens/web_assets/`
3. `python -m build` → wheel includes `web_assets/` via `[tool.setuptools.package-data]`
4. Tests: `pytest` (Python) + `npm --prefix web test` (Vitest) + `npm --prefix web run e2e` (Playwright smoke)

Wrapped behind a single `Makefile` target (or `scripts/release.sh`) so contributors run one command.

## 6. REST API Contract (`/api/v1`)

### Principles
- Base path versioned (`/api/v1`); independent of run schema version (`v1` of contract, encoded in payload `schema_version`).
- JSON shapes mirror `tests/fixtures/format_snapshots/*.json`. CLI `--format json` and API responses are identical for the same entity.
- Errors use RFC 7807 `application/problem+json` (`{type, title, status, detail, instance, correlation_id?}`).
- All timestamps: UTC ISO8601 with `Z`.
- Pagination: cursor-based (`?cursor=<opaque>&limit=50`, response `next_cursor`). Never offset.
- Cache headers: `Cache-Control: no-store`. Client-side cache is TanStack Query's stale-while-revalidate.

### Endpoints (v1)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/v1/meta` | `{agentlens_version, schema_version, store_path, store_exists, demo_mode}` | Header/footer + onboarding logic |
| GET | `/api/v1/workspaces` | `[{workspace_id, workspace_short, id_basis, run_count, latest_started_at}]` | Sidebar |
| GET | `/api/v1/workspaces/{workspace_id}` | `{workspace_id, …, recent_runs:[…], eval_pass_rate_30d, agent_breakdown}` | Workspace page |
| GET | `/api/v1/runs` | `{items:[<latest.json shape>], next_cursor}` | List page; filters: `workspace_id`, `agent`, `eval_status`, `agent_outcome`, `since_days` |
| GET | `/api/v1/runs/{run_id}` | `<show.json shape>` + `manifest_seal:{phase, sealed_at, manifest_sha256, integrity?}` | Run detail |
| GET | `/api/v1/runs/{run_id}/events` | `application/x-ndjson` (one event per line) | Transcript; v1 dumps full sealed events.jsonl. SSE reserved for v1.x |
| GET | `/api/v1/runs/{run_id}/failures` | `[<failure shape>]` | Cache-separable |
| GET | `/api/v1/runs/{run_id}/risks` | `[<risk shape>]` | Same |
| GET | `/api/v1/runs/{run_id}/artifacts` | `[{path, sha256, size, kind}]` | Manifest's artifact list |
| GET | `/api/v1/runs/{run_id}/artifacts/{sha256}` | raw bytes (redacted view only) | `Content-Disposition: attachment`; header `X-AgentLens-Redacted: true` |
| GET | `/api/v1/runs/{run_id}/verify` | `{ok:bool, expected, actual}` | Server-side manifest hash verification |
| GET | `/api/v1/failures` | `[…]` | Global; filters: `workspace_id`, `since_days` |
| GET | `/api/v1/risks` | `[…]` | Same |
| GET | `/api/v1/doctor` | `<doctor json>` — `integrations, paths, modes, warnings[]` | Sidebar footer + diag modal |
| GET | `/healthz` | `{status:"ok"}` | Liveness, outside `/api/v1` |

### Explicitly absent (v1)
- POST/PATCH/DELETE of any kind.
- Auth endpoints.
- WebSocket.

### Response headers (common)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `Cross-Origin-Opener-Policy: same-origin`
- `Cache-Control: no-store`
- `X-AgentLens-Warning: bound-to-non-loopback` (only when host is non-loopback)
- `X-AgentLens-Redacted: true` (artifact endpoints; informational)
- `X-AgentLens-Index: fallback` (when SQLite missing/corrupt and full-scan in use)

### CORS
- Default: same-origin only (no `Access-Control-Allow-Origin`).
- `--allow-origin URL` (CLI flag) adds an explicit allowlist entry.

### OpenAPI
- FastAPI auto-generates. `/docs` (Swagger UI) and `/openapi.json` are **on by default in v1** so third-party tools can be built on the read API.

### Sample: `GET /api/v1/runs/{run_id}` (canonical contract example)

```jsonc
{
  "run_id": "run_20260101_000001_bbbbbb",
  "workspace_id": "ws_0000000000000002",
  "workspace_short": "ws_00000000",
  "agent": "claude",
  "agent_outcome": "success",
  "eval_status": "failed",
  "sealed_phase": "final",
  "started_at": "2026-01-01T00:00:01Z",
  "finished_at": "2026-01-01T00:14:33Z",
  "failures": [ /* show.json shape */ ],
  "risks":    [ /* show.json shape */ ],
  "manifest_seal": {
    "phase": "final",
    "sealed_at": "2026-01-01T00:14:35Z",
    "manifest_sha256": "sha256:ab12...f9",
    "integrity": "ok"
  }
}
```

## 7. Frontend Design

### Pages (V1-Std, 5 routes)

1. **`/`** — runs list (default workspace = most recently active)
2. **`/runs/:run_id`** — run detail (default tab: Failures if any, else Transcript)
3. **`/workspaces/:workspace_id`** — workspace summary (run_count, eval pass rate, agent breakdown)
4. **`/empty`** — onboarding for empty store (three cards: Load demo, Install shim, Run doctor)
5. **`*`** — NotFound (with sidebar intact, suggests recent workspaces)

### App shell

- **Sidebar (dark, ~230px)**: AgentLens wordmark + version → Workspaces list → Global (All / Failures / Risks) → bottom: live doctor status pill.
- **Main (light, hybrid tone)**: page content.
- Tone: dark sidebar + light main (Hybrid A). Single token system; no dark-mode toggle in v1.

### Run list — signature screen
- Table columns: Started (relative; hover absolute) · Agent (badge) · Outcome · Eval · Failures · Duration · Run ID (mono, truncated).
- Row highlight: when `agent_outcome=success` and `eval_status=failed`, row gets a light-red background to make false-successes glanceable.
- Filters in top bar: Agent, Eval status, Since (7/30/90d).
- "Load more" pagination (cursor); v1.x considers virtualization.

### Run detail — three primary affordances
1. **Outcome ↔ Eval split** at the top: two equal columns under a single card. Left: "AGENT CLAIMS" with `agent_outcome`. Right: "EVALUATOR SAYS" with `eval_status`. If they disagree, a one-line discrepancy note.
2. **Meta strip**: agent + mode, started/duration, sealed_phase, manifest hash (with `verify` link → `GET /verify`), redaction badge if applicable.
3. **Tabs**: Failures / Risks / Transcript / Artifacts / Metadata. Default to Failures when non-empty; otherwise Transcript.

### Failures panel (Sentry-style)
- Each failure as a card with severity-colored left stripe.
- Meta chips: severity, category code, confidence, blame_scope, recoverability.
- Evidence: clickable `sha256:...` links jump to the Transcript tab and scroll to the matching event line.

### Transcript view (Laminar-inspired, not Phoenix span tree)
- Time-ordered flat list of events from `events.jsonl`.
- Each row: relative timestamp (hover for absolute) · event-type chip · one-line summary.
- Nested tool calls / sub-events collapsed by default, expand-on-click.
- Parse failure lines render inline as `⚠ unparseable line N` rather than breaking the view.

### Empty state — three-card onboarding
- "Your store is empty"
- Cards: **Load demo data** (uses bundled fixtures) · **Install shim** (CLI command shown) · **Run doctor**
- Footer: links to getting-started and contract spec docs.

### Component sourcing
- `components/ui/*` follows shadcn methodology: code copied into our repo, no runtime dependency on a component library, Radix primitives as headless atoms, Tailwind for styling.
- Icons: `lucide-react`.
- State: TanStack Query for server cache; no Redux/Zustand in v1.
- Routing: `react-router` v6+, declarative.

### Type sync
- `web/scripts/gen-types.ts` reads `tests/fixtures/format_snapshots/*.json` and generates zod schemas + TS types into `web/src/types/api.ts`.
- CI runs `gen-types` and fails if the result diverges from committed file — forces frontend ↔ backend contract alignment.

## 8. Error Handling & Edge Cases

### Backend

| Scenario | Behaviour |
|---|---|
| `AGENTLENS_HOME` absent | Server starts; `/api/v1/meta` returns `store_exists:false`; SPA enters empty state. |
| `index.db` missing/corrupt | `store.query` falls back to full-scan (already implemented). Responses include `X-AgentLens-Index: fallback`; SPA shows a yellow banner. |
| Run dir partial (some files missing) | `get_run` returns dict with nulls; API: 200 + `partial:true`; SPA detail page shows "incomplete run" notice. |
| Manifest hash mismatch | API: 200 + `manifest_seal.integrity:"broken"`; SPA shows orange integrity banner. Data still rendered (user's call). |
| Malformed line in `events.jsonl` | That line emitted as `{"_error":"parse","line":N}`; rest of stream intact. |
| Unknown schema version (e.g. v2 run) | API: 412 Precondition Failed; SPA shows "viewer update needed". Other runs unaffected. |
| FS permission denied | 403 ProblemDetails; that run only is unreadable; list page intact. |
| Internal 5xx | RFC 7807 response; `correlation_id` in body and in stderr log line. No stacktrace unless `--debug`. |
| Port 5757 in use | Default: fail-fast with helpful message. `--auto-port` opt-in tries +1, +2, +3. |
| `--host 0.0.0.0` | Red stderr warning at startup; warning header on every response; SPA top banner. |
| `--demo` | Bundled fixtures (from `src/agentlens/demo_data/` — curated subset of `tests/fixtures/*_run/`, shipped in the wheel via `package-data`) copied into a temporary HOME; SPA shows yellow "demo mode" banner. |

### Frontend

| Scenario | Behaviour |
|---|---|
| Backend unreachable | Top red banner; exponential backoff (1, 2, 4, 8, 16s cap); stale cache continues to render. |
| API 5xx | Toast: "Server error · id: <prefix>". Raw error body never shown. |
| API 412 | The affected view shows a "viewer update needed" empty state; sidebar intact. |
| `_error` marker in transcript | Inline `⚠ unparseable line N` row; page does not break. |
| Manifest broken | Orange banner at top of detail; data still displayed. |
| Redaction header `true` | "redacted view" badge near affected area. |
| 1000+ runs | Cursor pagination + "Load more". (Virtual scroll deferred to v1.x.) |
| 404 route | Custom NotFound; sidebar suggests recent workspaces. |
| Direct URL to gc'd run | "Run not found" empty state + link to recent runs. |
| Manifest verify click | Calls server-side `/verify`; UI shows result only. (Client never re-hashes large data.) |

### CLI (`agentlens serve`)

| Scenario | Behaviour |
|---|---|
| `web_assets/` empty (dev) | Server boots; static path serves a fallback HTML with build instructions. API still works. |
| `--dev-proxy URL` | Static mount replaced by reverse proxy. Allowed targets restricted to `127.0.0.1` hosts. |
| SIGINT | uvicorn graceful shutdown; ≤5s wait for in-flight; exit 0. |
| Concurrent `agentlens run …` writing | We open SQLite in RO mode → no write lock contention. Stale-while-revalidate masks transient gaps. |

### Deliberate trade-offs
- **Show, don't block.** Broken manifest still renders; user decides. Matches CLI behaviour.
- **No raw error bodies.** Public distribution; debug mode required.
- **Partial state is normal.** Recorder may have died; the run is exactly what we want to see.

## 9. Distribution & Release

- **Package**: `agentlens` on PyPI; `pipx install agentlens && agentlens serve`.
- **License**: MIT (matches AgentTrace, AgentPrism, ecosystem norm).
- **Wheel layout**: includes built `src/agentlens/web_assets/*` via `[tool.setuptools.package-data]`.
- **node** is required only for contributors editing the frontend; never at user install time.
- **CI matrix**: Python 3.11 / 3.12 / 3.13 / 3.14 × Node LTS 20/22 × Ubuntu + macOS. (Windows: post-v1.)
- **Release script**: single `Makefile` target runs lint, tests (Python + JS + e2e), build (npm + wheel), publish.
- **README signature**: GIF of the false-success run from the runs list → click → detail → evidence click → transcript line highlighted. Generated from the Playwright smoke spec's screenshot output.

## 10. Testing Strategy

### Layers

1. **Backend unit (pytest)** — settings, deps, errors, router input/output normalization.
2. **Backend integration (pytest + FastAPI TestClient)** — temp `AGENTLENS_HOME` populated from fixtures; all endpoints assert against `format_snapshots/*.json`. Covers: empty store, corrupt manifest, missing final, schema mismatch, demo mode, doctor parity with CLI, response headers.
3. **Frontend unit (Vitest)** — fetch wrappers + zod, format helpers, outcome/eval pills, failure cards, transcript renderer, redaction badge, default-tab behaviour, keyboard a11y on Tabs.
4. **Frontend integration (Vitest + MSW)** — MSW serves real fixture JSON; covers empty store onboarding, false-success row + click, disconnect/backoff, 412 mismatch, pagination.
5. **E2E smoke (Playwright, 1 spec)** — the signature GIF scenario, end-to-end, screenshot output reused as release artwork.
6. **Type-sync drift guard** — `npm run gen-types && git diff --exit-code` in CI.

### Regression locks
- Existing `format_snapshots/*.json` are now the joint truth for CLI and API. Either drifts → both fail.
- Redaction regression: redacted fixture must produce zero secret-pattern matches in any API response.
- Reverse non-blocking: `serve` crashing must not affect a concurrent `record` (RO mode = no write lock contention).
- Graceful shutdown: SIGINT → exit 0 within 5s.

### Explicitly out of scope (v1)
- Visual regression (screenshot diff) — flaky for v1.
- Cross-browser matrix beyond Playwright default.
- Mobile viewport / WCAG full audit.
- Performance benchmarks (localhost; not meaningful).

## 11. Open Questions / Future

- **Live tail** (in-progress run streaming) — design `events` endpoint as SSE upgrade path. Likely v1.1.
- **Cross-run diff / regression** — reserved as v2 headline. Requires evaluator extension (cross-run check).
- **Search across runs** — SQLite FTS index on summary fields. Likely v1.2.
- **GC UI** — read-only "what would be deleted" preview. v1.3 if demand.
- **Dark-mode toggle** — revisit after public feedback. Hybrid theme single-source-of-truth in v1 keeps refactor cheap if added later.
- **Windows support** — defer; current shim/path code is POSIX-first.
- **Hosted demo** — `demo.agentlens.dev`? Post-v1 marketing decision.

## 12. Appendix — References Studied

- AgentTrace (Rxflex/agenttrace) — closest local-first model; we steal the FastAPI + SQLite + embedded SPA architecture pattern. We differ in trust model (no SDK; agent-agnostic wrappers) and integrity (sealed manifests).
- Laminar (lmnr-ai) — transcript-view critique of span-tree UIs informs our Transcript tab.
- AgentPrism (evilmartians/agent-prism) — considered, rejected: OTLP-shape coupling and React component lock-in conflicts with our taxonomy-first UX. Inspiration only (4-component mental model, compressed details panel).
- Arize Phoenix — cited by Laminar as the cautionary example of span-tree-first UX on long agent runs; we explicitly avoid that.
- Langfuse / FutureAGI — too heavy infra footprint (ClickHouse, multi-service) for our local-first stance.
- GitHub Actions UI — list → detail → step-expand pattern users already know.
- Sentry issue page — severity-stripe + evidence link pattern adopted for our failures panel.

End of spec.
