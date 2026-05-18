# AgentLens CLI Reference (v1 locked)

This document re-narrates spec section S1.11 (CLI UX). The subcommand surface, the `--format json` snapshot contract, and the stdout/stderr separation rule are **v1 잠금 / v1 locked**: scripts and dashboards built against `agentlens --format json` are expected to keep working across v1.x releases.

## 1. Subcommand contract

The user-visible subcommand set is:

```
agentlens install [--yes]
agentlens doctor [integrations] [--format json]
agentlens on | off | mode <minimal|full>
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
agentlens gc [--dry-run]
```

Each command supports `--help`. Subcommand names are part of the v1 contract and will not be renamed.

## 2. Lifecycle commands

- **`agentlens run -- <command> [args...]`** — recommended entry point. Wraps the child process, creates the run directory, emits a `start` event, then `exec`s the child. The child's exit code is propagated verbatim. If AgentLens cannot create the run directory it degrades to silent passthrough (S1.2 invariant #6).
- **`agentlens start --agent <name> --mode <cli|app|code|unknown>`** — manual start for adapters that cannot use `run`. Optional `--parent <run_id>` links a child run to its caller.
- **`agentlens mark <event_type>`** — appends a timeline event. Supports `--task-id` and `--name` for structured task boundaries.
- **`agentlens attach --kind <kind> --path <path>`** — registers a file under `artifacts/` and adds a manifest entry with its sha256.
- **`agentlens final --outcome <success|failed|partial|cancelled|unknown>`** — writes `final.json`.
- **`agentlens seal [--final]`** — takes the `pre_eval` seal by default; with `--final`, takes the `final` seal after `eval.json` has been written.
- **`agentlens eval [--latest | --run-id <id>]`** — runs the evaluator over an already-sealed run (or seals it first). Read-only against durable artifacts; writes `eval.json`.
- **`agentlens cancel --run-id <id>`** — cancels an active run; signals the child if applicable.

## 3. Query commands

- **`agentlens latest [--format json]`** — most recent run for the current workspace.
- **`agentlens status [--format json]`** — currently-active runs.
- **`agentlens show <--latest | run_id> [--format json]`** — detailed view of a single run.
- **`agentlens failures [--since-days 30] [--format json]`** — rollup of failure-outcome runs.
- **`agentlens risks [--since-days 30] [--format json]`** — rollup of risk signals surfaced by `eval`.

All query commands route through the `store/query.py` facade. They never mutate durable artifacts.

### Examples

```
$ agentlens latest
ws/3f7a  01HXY...  agent=claude  outcome=success  sealed=final
```

```
$ agentlens show --latest --format json | jq '.run_id, .outcome'
"01HXY..."
"success"
```

## 4. Configuration & maintenance commands

- **`agentlens install [--yes]`** — installs PATH shims after explicit consent (see `security.md`).
- **`agentlens doctor [integrations] [--format json]`** — environment diagnostics; with `integrations`, reports per-adapter Levels.
- **`agentlens on | off | mode <minimal|full>`** — toggles recording globally or down-clamps to `minimal`.
- **`agentlens gc [--dry-run]`** — enforces the retention budget; `--dry-run` reports what would be deleted.

## 5. Output conventions

- **Default output is human-readable text** at a target width of 80 columns, with color when `stdout` is a TTY.
- **`--format json`** emits a schema-stable JSON document that is snapshot-tested. New fields may be added only as optional/additive members; existing field names and types are locked under v1.
- **`stdout` carries query results only.** Diagnostics, warnings, progress, and errors go to `stderr`. Scripts may safely pipe `stdout` into `jq`.
- **Absolute paths are never printed.** Run identifiers use a short `workspace_id` prefix plus the `run_id` (`ws/3f7a 01HXY…`); artifact paths are rendered relative to the run directory.
- Exit codes: `0` on success, `1` on user error, `2` on AgentLens-internal error, and for `agentlens run` the child's exit code is propagated verbatim.

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
