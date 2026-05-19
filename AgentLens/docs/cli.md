# AgentLens CLI Reference (v1 locked)

This document re-narrates spec section S1.11 (CLI UX). The subcommand surface, the `--format json` snapshot contract, and the stdout/stderr separation rule are **v1 잠금 / v1 locked**: scripts and dashboards built against `agentlens --format json` are expected to keep working across v1.x releases.

## 1. Subcommand contract

The user-visible subcommand set is:

```
agentlens install <agent> [--real PATH] [--yes]
agentlens uninstall <agent>
agentlens doctor [integrations | paths | all] [--format text|json]
agentlens on | off
agentlens mode show
agentlens mode set <disabled|minimal|full>
agentlens run -- <command> [args...]
agentlens start --agent <name> --mode <cli|app|code|unknown> [--parent <run_id>]
agentlens mark <event_type> [--task-id ...] [--name ...]
agentlens attach --kind <kind> --path <path>
agentlens final --outcome <success|failed|partial|cancelled|unknown>
agentlens seal [--final]
agentlens eval [--latest | --run-id <id>]
agentlens cancel --run-id <id> [--reason ...] [--signal SIGINT]
agentlens latest [--format json]
agentlens status [--format json]
agentlens show <--latest | run_id> [--format json]
agentlens failures [--since-days 30] [--format json]
agentlens risks [--since-days 30] [--format json]
agentlens serve [--host HOST] [--port PORT] [--demo] [--debug] [--auto-port]
                [--dev-proxy URL] [--allow-origin URL]...
agentlens gc [--dry-run]
```

Each command supports `--help`. Subcommand names are part of the v1 contract and will not be renamed.

## 2. Lifecycle commands

- **`agentlens run -- <command> [args...]`** — recommended entry point. Spawns the child under the wrapper (not `exec`), drains stdout/stderr concurrently via a selector loop so large output cannot deadlock on pipe buffers, and forwards both streams verbatim to the parent's tty/pipes. The child's exit code is propagated verbatim; on signal cancellation the wrapper exits with `128 + signum` (e.g. SIGINT → 130, SIGTERM → 143). SIGINT and SIGTERM received by the wrapper are forwarded to the child and original handlers are restored after the child exits. The post-drain recording pipeline (write_run_meta → append_event → write_workspace_pointer → write_final → seal(pre_eval) → evaluate → seal(final) → index_run) is **non-blocking**: every stage is guarded so that AgentLens-internal failures never alter the child's exit code. Pre-eval / evaluate failures are surfaced by marking the manifest `recording_incomplete`; bounded excerpts (allow-listed extractors, capped at `MAX_EXCERPT_CHARS = 4096` with a `<TRUNCATED>` marker) are attached to `final.json`. If AgentLens cannot create the run directory it degrades to silent passthrough (S1.2 invariant #6).
- **`agentlens start --agent <name> --mode <cli|app|code|unknown>`** — manual start for adapters that cannot use `run`. Optional `--parent <run_id>` links a child run to its caller.
- **`agentlens mark <event_type>`** — appends a timeline event. Supports `--task-id` and `--name` for structured task boundaries.
- **`agentlens attach --kind <kind> --path <path>`** — registers a file under `artifacts/` and adds a manifest entry with its sha256.
- **`agentlens final --outcome <success|failed|partial|cancelled|unknown>`** — writes `final.json`.
- **`agentlens seal [--final]`** — takes the `pre_eval` seal by default; with `--final`, takes the `final` seal after `eval.json` has been written.
- **`agentlens eval [--latest | --run-id <id>]`** — runs the evaluator over an already-sealed run (or seals it first). Read-only against durable artifacts; writes `eval.json`.
- **`agentlens cancel --run-id <id>`** — cancels an active run; signals the child if applicable.

## 3. Query commands

- **`agentlens latest [--format json]`** — most recent run for the current workspace. Text emits a single one-line row; `--format json` emits a locked `run_row` object (or `null` when no runs exist).
- **`agentlens status [--format json]`** — currently-active runs (one row per non-sealed run). Text emits one row per active run; `--format json` emits an array of `run_row` objects.
- **`agentlens show <--latest | run_id> [--format json]`** — detailed view of a single run. Resolves the run by `--latest` (current workspace) or by positional `run_id`. Text output is a multi-line summary with `failures` and `risks` sections; `--format json` emits the `show` object (see §3.2).
- **`agentlens failures [--since-days 30] [--format json]`** — rollup of failure-outcome runs over the trailing window (default 30 days). Text emits one line per failure; `--format json` emits an array of `failure` objects.
- **`agentlens risks [--since-days 30] [--format json]`** — rollup of residual-risk signals surfaced by `eval` over the trailing window. Text emits one line per risk; `--format json` emits an array of `risk` objects.

All query commands route through the `store/query.py` facade. They never mutate durable artifacts.

### 3.1 Text output rules (query commands)

- **No absolute paths.** Workspace identity is rendered using `workspace_short`, defined as `workspace_id[:11]` (e.g. `ws_3f7a8b9c` → `ws_3f7a8b9c`; empty/missing → `-`). This mirrors the git short-SHA convention and never reveals filesystem layout.
- **Canonical one-line row** (used by `latest` and `status`):
  ```
  <run_id>  <workspace_short>  <agent_outcome>  <eval_status>  <sealed_phase>
  ```
  Missing string fields render as `-`. `eval_status` defaults to `needs_eval` when `eval.json` is absent.
- **stdout/stderr separation.** Query results go to `stdout`; warnings, progress, and errors go to `stderr` (§5). Scripts can safely pipe `--format json` output through `jq`.

### 3.2 JSON schema v1 — wire contract

The `--format json` output of every query command is **locked at v1** (`JSON_SCHEMA_VERSION = "v1"` in `agentlens.commands._format`). The locked shapes are:

| Command     | Top level                                                      |
|-------------|----------------------------------------------------------------|
| `latest`    | `run_row` object, or `null` when there are no runs             |
| `status`    | array of `run_row` objects (possibly empty)                    |
| `show`      | `show` object (always emitted; embeds `failures` and `risks`)  |
| `failures`  | array of `failure` objects (possibly empty)                    |
| `risks`     | array of `risk` objects (possibly empty)                       |

Locked object shapes (each object always emits **all** the listed keys, in this order, with the documented defaults for missing values):

- **`run_row`** (11 canonical keys, plus optional `status` / `residual_risks` / `schema_invalid` when present): `run_id`, `workspace_id`, `parent_run_id`, `started_at`, `ended_at`, `agent_name`, `agent_mode`, `recording_mode`, `agent_outcome`, `eval_status` (default `"needs_eval"`), `sealed_phase`. String defaults: `""`; `parent_run_id` defaults to `null`.
- **`show`** (10 keys): `run_id`, `agent` (default `"unknown"`), `started_at`, `agent_outcome` (default `"unknown"`), `eval_status` (default `"needs_eval"`), `sealed_phase`, `workspace_id`, `workspace_short` (default `"-"`), `failures` (array of `failure`), `risks` (array of `risk`).
- **`failure`** (10 keys): `run_id`, `workspace_id`, `category`, `severity`, `source`, `blame_scope`, `summary`, `confidence` (number or `null`), `recoverability`, `evidence` (array; default `[]`).
- **`risk`** (6 keys): `run_id`, `workspace_id`, `category`, `source`, `severity`, `summary`.

**No absolute paths leak.** The `_source_dir` field used internally by `store.query.full_scan_runs` for schema-invalid rows is stripped by the projectors before emission.

**Snapshot test contract.** The wire contract is pinned by snapshot tests at `tests/integration/test_format_json_snapshot.py` against golden files at `tests/fixtures/format_snapshots/<cmd>.json` (one each for `latest`, `status`, `show`, `failures`, `risks`). Any change in JSON output shape MUST be reflected in those goldens; a snapshot diff blocks CI. Regenerate the goldens (after an intentional, contract-compatible change) with:

```
AGENTLENS_UPDATE_SNAPSHOTS=1 pytest tests/integration/test_format_json_snapshot.py
```

A breaking shape change requires bumping `JSON_SCHEMA_VERSION` and is governed by the v1 lock policy (§7).

### 3.3 Examples

```
$ agentlens latest
01HXY7K...  ws_3f7a8b9c  success  passed  final
```

```
$ agentlens show --latest --format json | jq '.run_id, .agent_outcome'
"01HXY..."
"success"
```

```
$ agentlens failures --since-days 7 --format json | jq '.[].category' | sort -u
"tool_misuse"
"unhandled_exception"
```

## 4. Configuration & maintenance commands

- **`agentlens install <agent> [--real PATH] [--yes]`** — writes a PATH shim plus a sibling `.real` sha256 lockfile under `~/.agentlens/shims/`. The real binary is auto-detected via `shutil.which(agent)` unless `--real PATH` is passed. Requires explicit user consent at an interactive prompt; `--yes` bypasses the prompt for CI/automation only. **The command never edits the user's shell rc** — it prints the `export PATH="$HOME/.agentlens/shims:$PATH"` hint and the user must add it manually. See `security.md` for the shim trust model.
- **`agentlens uninstall <agent>`** — removes `~/.agentlens/shims/<agent>` and the matching `.real` lockfile. Idempotent: succeeds even when no shim is installed.
- **`agentlens doctor [integrations | paths | all] [--format text|json]`** — environment diagnostics. Scopes:
  - `integrations` — per known agent (`claude`, `codex`), reports `integration_level` (one of `none`, `watcher-only`, `shim`, `full`, `native-experimental` per the taxonomy in `integrations.md`) and, when a shim is installed, `shim_integrity` (`ok` | `drift_warning`). `missing` shims collapse to `integration_level=none`.
  - `paths` — resolved `AGENTLENS_HOME`, `workspace_id` (with `id_basis`), and the shim directory, each annotated with whether the path exists.
  - `all` (default) — both blocks.

  Output is human-readable text by default; `--format json` emits a deterministic JSON document (keys sorted) suitable for piping into `jq`.
- **`agentlens mode show`** — prints the resolved mode (one token, one line: `disabled` | `minimal` | `full`) according to the config priority chain: `AGENTLENS_DISABLE=1` > `AGENTLENS_MODE` env > `<cwd>/.agentlens/config.yaml` > `~/.agentlens/config.yaml` > default `minimal`.
- **`agentlens mode set <disabled|minimal|full>`** — persists `mode` to `<cwd>/.agentlens/config.yaml` (merging with existing keys). Rejects values outside the three-token allow-list.
- **`agentlens on | off`** — convenience toggles equivalent to `mode set full` / `mode set disabled`.
- **`AGENTLENS_DISABLE=1`** is an **unconditional kill switch**: when set in the environment, `load_config` returns `{"mode": "disabled"}` regardless of any YAML file or other env var, and `agentlens mode show` reports `disabled`. This is the recommended way to silence AgentLens in a one-off shell without editing config files.
- **Nested invocation policy.** When a child process started under `agentlens run` itself invokes `agentlens run`, the wrapper detects the parent via `AGENTLENS_RUN_ID` in the environment. `AGENTLENS_NESTED_POLICY=passthrough` (the default) causes the nested call to skip re-recording and act as a transparent passthrough; `AGENTLENS_NESTED_POLICY=nested` opens a new run whose `run.json` records the outer run's id as `parent_run_id`. The recording-path environment variables (`AGENTLENS_RUN_ID`, `AGENTLENS_RUN_DIR`, `AGENTLENS_RUN_PID_STAMP`) are only propagated to children on the recording path.
- **`agentlens gc [--dry-run]`** — enforces the retention budget (`RetentionPolicy`, spec §5.9). Defaults: `sealed_runs_days=30`, `large_artifacts_days=7`, `max_artifact_mb_per_run=50`, `max_total_store_gb=5`, `keep_eval_summaries=true` — summary JSON (`run.json`/`final.json`/`eval.json`/`manifest.json`) is preserved when the quota path triggers. SQLite-independent (scans the filesystem only). `--dry-run` lists candidates and projected freed bytes without unlinking. See `runbook.md` §5 for the full defaults table.

## 5. Output conventions

- **Default output is human-readable text** at a target width of 80 columns, with color when `stdout` is a TTY.
- **`--format json`** emits a schema-stable JSON document that is snapshot-tested. New fields may be added only as optional/additive members; existing field names and types are locked under v1.
- **`stdout` carries query results only.** Diagnostics, warnings, progress, and errors go to `stderr`. Scripts may safely pipe `stdout` into `jq`.
- **Absolute paths are never printed.** Query commands render workspace identity via `workspace_short = workspace_id[:11]` (§3.1); artifact paths are rendered relative to the run directory.
- Exit codes: `0` on success, `1` on user error, `2` on AgentLens-internal error. For `agentlens run` the child's exit code is propagated verbatim, and on signal cancellation the wrapper exits with `128 + signum` (e.g. SIGINT → 130, SIGTERM → 143). AgentLens-internal failures in the post-drain recording pipeline never alter the child's exit code.

## 6. Hidden v0 commands

The following commands exist in the v0 binary but are intentionally **not** advertised in `--help` listings or this reference. They are subject to change without notice and are not part of the v1 contract:

```
agentlens import
agentlens dashboard
agentlens studio
agentlens mcp
agentlens patch
agentlens compile
```

## 7. v1 잠금 정책 (v1 lock policy)

- Subcommand names, the `--format json` schema shape, and the stdout/stderr separation rule are **locked** for v1.
- New subcommands may be added; existing ones may not be renamed or have their flags' meanings changed.
- Hidden v0 commands (section 6) are explicitly **not** part of the v1 lock and may be removed or restructured at any time.

## 8. `agentlens serve`

Boot the dashboard. See [dashboard.md](dashboard.md) for full options.

```bash
agentlens serve [--host HOST] [--port PORT] [--demo] [--debug]
                [--auto-port] [--dev-proxy URL] [--allow-origin URL]...
```

The default URL is `http://127.0.0.1:5757`. The dashboard is read-only: it
views runs, failures, risks, transcripts, workspace summaries, and doctor
status without mutating the AgentLens store.
