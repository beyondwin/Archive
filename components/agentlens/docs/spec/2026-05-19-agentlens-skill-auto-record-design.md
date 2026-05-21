# AgentLens Auto-Record + kws-Skill Unification — Design Spec

**Date:** 2026-05-19
**Status:** Draft — engineering review incorporated
**Scope:** AgentLens v1 + kws-claude-multi-agent-executor + kws-codex-plan-executor
**Supersedes / extends:** AgentLens v0 (`AgentLens/docs/spec/`, `AgentLens/docs/contract.md`)

## 1. Problem

Today, two orchestrator skills each maintain their own logging stack:

- **kws-claude-multi-agent-executor (kws-cme)** writes `.orchestrator/state.json`, `.orchestrator/headless.jsonl`, and `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl` via `scripts/append_learning_event.py`.
- **kws-codex-plan-executor (kws-cpe)** writes primary state under `.codex-orchestrator/runs/<run_id>/state.json`, keeps `.codex-orchestrator/state.json` as a compatibility latest pointer/copy, writes project-local `.codex-orchestrator/runs/<run_id>/events.jsonl` via `scripts/append_run_event.py`, and writes user-local learning events under `~/.codex/learning/kws-codex-plan-executor/` via `scripts/append_learning_event.py`.

Meanwhile AgentLens v0 already wraps subprocess lifecycle when invoked through its shim, producing `run.json`, `events.jsonl`, `final.json`, `eval.json`, and `manifest.json` with bounded, schema-validated evidence. It does **not** currently persist full prompt or stdout/stderr transcripts; `docs/security.md` explicitly says full prompt transcripts are not stored and arbitrary output slicing is forbidden. Any v1 transcript feature is therefore a new storage/security contract, not a reuse of existing v0 behavior. The user wants:

1. **AgentLens to activate automatically** for every non-interactive `claude -p` and `codex exec` invocation reachable through the installed shim, and to ingest interactive Claude Code sessions and Codex sessions (CLI interactive, `codex resume`/`fork`, and Codex Desktop) post-hoc from their own per-session JSONL stores without degrading either TUI.
2. **The kws skills' own event/logging substrates to be eliminated** in favor of AgentLens as the single run/event substrate, while preserving each skill's mutable orchestration `state.json` (required for resume).

This spec describes the integration design — what AgentLens gains, what each kws skill loses, and how cross-terminal auto-activation works. It also records the implementation-impact review findings that must be handled before code execution.

## 1.1 Engineering Review Findings

These findings are based on the current AgentLens source and the two skill source trees under `skills/`.

| ID | Severity | Finding | Required correction |
|----|----------|---------|---------------------|
| R1 | Blocker | The initial draft used `meta.json` and root-level `transcript.jsonl`, but the locked AgentLens store is `run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`, plus `artifacts/`. | Container and imported runs must write valid `agentlens.run.v1` documents through `store/writer.py`. Transcript material, when stored, belongs under `artifacts/` and must be covered by `manifest.json`. |
| R2 | Blocker | `agentlens.event.v1` currently restricts `type` to a fixed enum, so `kws-cme.*` / `kws-cpe.*` events will fail schema validation. | Extend the event schema from enum-only to namespace-pattern event types, update fixtures/tests/docs, and keep core AgentLens event names reserved. |
| R3 | Blocker | `agentlens.run -- <command>` is an existing locked top-level wrapper command; `agentlens run open` would collide with that surface. | Use additive top-level commands `agentlens run-open` and `agentlens run-close`, or introduce a different non-conflicting group. This spec standardizes on `run-open` / `run-close`. |
| R4 | Blocker | Existing nested invocation handling only reads `AGENTLENS_RUN_ID`; the proposed `AGENTLENS_PARENT_RUN_ID` would be ignored, and inherited `AGENTLENS_RUN_ID` can force passthrough. | Teach the wrapper that explicit `AGENTLENS_PARENT_RUN_ID` wins over default nested passthrough, and only falls back to inherited `AGENTLENS_RUN_ID` when the explicit parent is absent. |
| R5 | High | `kws-cpe` primary state is `.codex-orchestrator/runs/<run_id>/state.json`; root `.codex-orchestrator/state.json` is compatibility-only. The initial draft flattened this. | Preserve per-run state as source of truth and treat the root state file as a pointer/copy only. |
| R6 | High | `kws-cpe` has two logging layers: project-local event journal (`append_run_event.py`) and user-local learning log (`append_learning_event.py`). The initial draft only removed one. | Migrate both layers or explicitly defer one. This spec migrates both to AgentLens, with dual-write parity before removal. |
| R7 | High | The plan targeted installed skill copies under `~/.claude/skills`, but the source of truth in this repo is `skills/kws-claude-multi-agent-executor/` and `skills/kws-codex-plan-executor/`. | Patch source files in `skills/` first, then install/sync through the normal skill deployment path. |
| R8 | Medium | The draft assumed `codex` has no TUI. That is an unsafe product assumption. | Resolved: bare `codex` is a TUI. Wrap only `codex exec` (and the `e` alias). All other subcommands and Codex Desktop are pass-through; capture goes through `agentlens import codex-session` against `~/.codex/sessions/` rollout JSONLs. See §4.5 and §5.1. |

## 2. Goals & Non-Goals

### Goals
- One AgentLens capture run per wrapped `claude -p` / `codex exec` invocation, regardless of which terminal launched it, with command lifecycle events and bounded evidence. Full transcript storage is allowed only through the explicit transcript artifact contract below.
- One event log per orchestrator run, captured in AgentLens as opaque per-skill event types, queryable across skills.
- Zero-touch developer experience: after install, the user works exactly as before; recording happens transparently.
- Existing kws orchestration state (task graph, baselines, resume points) keeps living in each skill's own `state.json` — AgentLens never owns it.
- Hard non-blocking guarantee: any AgentLens failure (CLI missing, disk full, DB locked) is silently absorbed; orchestrators never halt because of it.
- Contract-compatible storage: new AgentLens data must respect the current `run.json` / `events.jsonl` / `final.json` / `eval.json` / `manifest.json` layout and update `docs/contract.md`, `docs/cli.md`, and `docs/security.md` when schemas or transcript retention change.

### Non-Goals
- Event-sourced state (option C in brainstorming) — explicitly deferred. AgentLens does not derive `state.json`.
- Real-time transcript capture for interactive Claude Code — uses post-session ingest instead (rationale §5).
- Event-sourced replay of project state — AgentLens stores observations; it does not replace `.orchestrator/state.json` or `.codex-orchestrator/runs/<run_id>/state.json`.
- Cost-accounting unification (kws-cme's `accumulate_cost.py`) — out of scope, deferred to a separate v2.
- Migration of historical pre-existing kws event logs into AgentLens — optional one-shot import provided but not required.

## 3. Architecture Overview

```
┌──── Any terminal ─────────────────────────────────────────┐
│  User: claude -p ... / codex ... / claude (interactive)   │
│              │                                            │
│              ▼ PATH lookup                                │
│   ~/.agentlens/shims/<name>   ← shim 1순위 (zshrc/cmux)  │
│              │                                            │
│      ┌───────┴────────────┐                               │
│      │ interactive claude │ ── stdin.isatty() == True ──► │
│      │                    │   pass-through exec REAL      │
│      │                    │   (no wrap; session JSONL     │
│      │                    │    ingested separately)       │
│      └────────────────────┘                               │
│      │ non-interactive    │                               │
│      ▼                                                    │
│   agentlens run --agent <canon> -- REAL "$@"              │
│      ├─ tee child stdout/stderr ─► user 화면              │
│      └─ AgentLens run_dir/                                │
│           ├─ run.json                                     │
│           ├─ events.jsonl (run/command lifecycle)         │
│           ├─ final.json / eval.json / manifest.json       │
│           └─ artifacts/ (optional transcript material)    │
└───────────────────────────────────────────────────────────┘

┌──── kws orchestrator (kws-cme / kws-cpe) ─────────────────┐
│  Phase -1:                                                │
│    ORCH=$(agentlens run-open --agent <skill>-orchestrator)│
│    persist ORCH into state.json                           │
│                                                           │
│  Every phase/task transition:                             │
│    agentlens event append --run $ORCH \                   │
│      --type <skill>.<event> --payload-json @data          │
│                                                           │
│  Sub-spawn:                                               │
│    AGENTLENS_PARENT_RUN_ID=$ORCH \                        │
│    nohup claude -p ... > headless.jsonl 2>&1              │
│    (above flow auto-creates child run linked to parent)   │
│                                                           │
│  state.json: kws-local, unchanged                         │
└───────────────────────────────────────────────────────────┘

┌──── Session JSONL ingest (post-session) ──────────────────┐
│  Claude Code:                                             │
│    ~/.claude/projects/<encoded>/<session-id>.jsonl        │
│  Codex CLI / Codex Desktop / Codex subagents:             │
│    ~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<id>.jsonl  │
│    (archived: ~/.codex/archived_sessions/rollout-*.jsonl) │
│              │                                            │
│              ▼ (watcher daemon OR explicit import)        │
│   agentlens import claude-session --latest                │
│   agentlens import codex-session --latest                 │
│              │                                            │
│              ▼                                            │
│   Materialized AgentLens run (run_kind=capture,           │
│     transcript_source=claude-session-jsonl                │
│     or codex-rollout-jsonl)                               │
└───────────────────────────────────────────────────────────┘
```

Two AgentLens run shapes emerge:

| Shape | `run_kind` | Populated by | Examples |
|-------|------------|--------------|----------|
| **Container run** | `container` | `agentlens run-open` | Orchestrator wrapping its own phase/task events |
| **Capture run** | `capture` | shim wrapper OR session-JSONL import | One `claude -p` / `codex exec` / interactive Claude Code session |

Container runs can have many capture runs as children (via `parent_run_id`).

## 4. AgentLens v1 Additions

### 4.1 Schema

This change intentionally extends the locked v1 contracts. The current schema files have `additionalProperties: false`, so every new field below requires schema, fixture, writer, query, snapshot, and docs updates in the same PR.

`run.json` (`agentlens.run.v1`) gains additive optional fields:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `run_kind` | `"capture"` \| `"container"` | `"capture"` | Distinguish subprocess/session capture runs from orchestration-only container runs |
| `agent.label` | string | `agent.name` | Human/query label such as `kws-cme-orchestrator` without requiring a new enum value for every skill |
| `recording.has_transcript` | boolean | `false` | Whether transcript material is present under `artifacts/` |
| `recording.transcript_source` | `"none"` \| `"claude-session-jsonl"` \| `"codex-rollout-jsonl"` \| `"wrapper-stream-json"` \| `"external"` | `"none"` | Identifies how transcript material was obtained |
| `input.import_key` | string | absent | Stable idempotency key for imported sessions, e.g. `claude-session:<session-id>` or `codex-rollout:<session-id>` |

Container runs use `agent.name="generic"`, `agent.mode="unknown"`, `agent.label="<skill>-orchestrator"`, `run_kind="container"`, and `recording.adapter="agentlens_container"`. This avoids expanding `agent.name` for every skill namespace while still giving queries a readable label.

`events.jsonl` (`agentlens.event.v1`) changes `type` from enum-only to a namespace pattern:

- Reserved AgentLens core namespaces: `run.*`, `command.*`, `checkpoint.*`, `artifact.*`, `task.*`, `failure.*`, `recording.*`, `agentlens.*`.
- Skill namespaces: `kws-cme.*`, `kws-cpe.*`, or any lower-case `<namespace>.<event>` form matching `^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+$`.
- Imported session namespaces: `claude.*` (from Claude Code session JSONL ingest) and `codex.*` (from Codex rollout JSONL ingest) are reserved for the importers.
- The existing core event names remain valid. Unknown core-looking event names under reserved namespaces are rejected unless AgentLens defines them.
- Payload remains opaque JSON for non-core namespaces; AgentLens validates only that it is an object and passes redaction.

`runs` SQLite table (derived index, not source of truth) gains additive nullable/defaulted columns:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `parent_run_id` | TEXT, FK → runs.run_id, ON DELETE SET NULL | NULL | Link capture runs to their orchestrator container; tree queries |
| `run_kind` | TEXT | `capture` | Query/filter capture vs container runs without opening JSON |
| `agent_label` | TEXT | NULL | Query display label (`agent.label`) |
| `has_transcript` | BOOLEAN | FALSE | Mirror `recording.has_transcript` |

Indexes added: `(parent_run_id)`, `(run_kind, started_at DESC)`. A SQLite `events` table is optional; the existing code does not have one. If an event index is added, it is derived from `events.jsonl` and must be rebuildable. Schema migration is automatic at first v1 startup (idempotent `ALTER TABLE` + index create).

The durable event shape is still the full schema line, never the short draft shape:

```json
{
  "schema": "agentlens.event.v1",
  "event_id": "evt_abc123def456",
  "run_id": "run_20260519_000000_abc123",
  "ts": "2026-05-19T00:00:00Z",
  "type": "kws-cme.task_started",
  "payload": {"task_id": "task_1"}
}
```

### 4.2 New CLI commands

#### `agentlens run-open`
```
agentlens run-open --agent <label> \
  [--workspace <path>] [--parent <run_id>] [--meta <k=v>] [--meta <k=v>]
```
Behavior:
- Creates a container run (`run_kind=container`, `recording.has_transcript=false`).
- Writes a valid `run.json`, appends a `run.started` event to `events.jsonl`, and leaves `final.json` absent until `run-close`.
- Prints `<run_id>` to stdout.
- Returns 0 on success; non-zero only on hard failure (e.g. AGENTLENS_HOME unwritable).

#### `agentlens run-close`
```
agentlens run-close --run <run_id> [--outcome success|failed|partial|cancelled|unknown] [--summary <text>]
```
Behavior:
- Writes `final.json` for a container run and updates the SQLite index best-effort.
- Unknown run id is non-blocking for orchestrators: warning to stderr and exit 0.

#### `agentlens event append`
```
agentlens event append --run <run_id> --type <type_string> \
  (--payload-json <inline> | --payload-file <path> | --payload-stdin) \
  [--ts <iso8601>]
```
Behavior:
- Resolves run via filesystem first (`commands/_run_resolve.py`), with SQLite only as an acceleration path. JSON artifacts remain authoritative.
- Builds and appends the full `agentlens.event.v1` line (`schema`, `event_id`, `run_id`, `ts`, `type`, `payload`) through `store/writer.py:append_event`, preserving locking, redaction, and schema validation.
- Updates any derived SQLite event index best-effort if one exists.
- On any unexpected error: stderr warning + exit 0.

#### `agentlens events`
```
agentlens events [--run <id>] [--type <glob>] [--since <ts>] [--tree] [--follow]
```
Behavior:
- Queries `events.jsonl` directly (no SQLite re-derivation for body).
- `--tree`: includes the run plus all descendants ordered by `(ts, run_id)`.
- `--type 'kws-cme.*'`: glob match.
- `--follow`: tails the file(s) and prints new lines (useful for live monitoring).
- Output JSONL, one event per line.

#### `agentlens import claude-session`
```
agentlens import claude-session \
  (--latest | --id <session-id> | --all) \
  [--project <encoded-name>] [--parent <run_id>]
```
Behavior:
- Locates `~/.claude/projects/<encoded>/<session-id>.jsonl` (or all of them).
- Each session JSONL becomes one AgentLens capture run (`agent.name=claude_code`, `run_kind=capture`, `recording.has_transcript=true`, `recording.transcript_source=claude-session-jsonl`).
- Transcript material is copied (not symlinked) under `artifacts/transcripts/<session-id>.jsonl` so AgentLens retention and manifest rules apply. It is not written as root-level `transcript.jsonl`.
- Events extracted: `command.started`, `command.finished` derived from the session boundaries; tool-use events stored opaque under `claude.tool_use` etc.
- Idempotent: re-importing the same session does not duplicate the run. Use `input.import_key="claude-session:<session-id>"` and either a small import index under AgentLens home or a full-scan lookup to resolve the existing run.
- Optional `--parent <run_id>` for linkage when the user knows the session belongs to a higher-level workflow.

#### `agentlens import codex-session`
```
agentlens import codex-session \
  (--latest | --id <session-id> | --since <iso8601> | --all) \
  [--include-archived] [--parent <run_id>]
```
Behavior:
- Locates Codex rollout JSONLs under `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<session-id>.jsonl` (active) and, with `--include-archived`, `~/.codex/archived_sessions/rollout-<ISO>-<session-id>.jsonl`.
- Each rollout JSONL becomes one AgentLens capture run (`agent.name=codex_cli`, `run_kind=capture`, `recording.has_transcript=true`, `recording.transcript_source=codex-rollout-jsonl`).
- The first line of each rollout is a `session_meta` event whose `payload` carries `id`, `timestamp`, `cwd`, `originator` (`"Codex CLI"`, `"Codex Desktop"`), `cli_version`, `model_provider`, and optionally `source.subagent.thread_spawn` (parent thread id, depth, agent role). The importer maps these into `run.json` metadata and records the originator/subagent-source under `meta`.
- Transcript material is copied (not symlinked) to `artifacts/transcripts/<session-id>.jsonl` so AgentLens manifest/redaction/retention rules apply uniformly.
- Events extracted: `command.started` and `command.finished` derived from rollout boundaries; tool-use / message / reasoning lines stored opaque under `codex.*` (e.g. `codex.message`, `codex.tool_use`, `codex.tool_result`, `codex.reasoning`).
- Idempotent: re-importing the same rollout is a no-op. Use `input.import_key="codex-rollout:<session-id>"` (matching the rollout filename's UUID).
- Subagent linkage: when `session_meta.payload.source.subagent.thread_spawn.parent_thread_id` is present and the parent session has already been imported, the child run's `parent_run_id` is set automatically. `--parent <run_id>` overrides.
- Covers both Codex CLI and Codex Desktop: they write to the same `~/.codex/sessions/` tree with identical JSONL schema; only the `originator` field differs and is preserved in the resulting run's metadata.

### 4.3 Optional watcher daemon

```
agentlens daemon start [--watch claude-sessions] [--watch codex-sessions] [--watch <other>]
agentlens daemon stop
agentlens daemon status
```

`--watch claude-sessions` monitors `~/.claude/projects/` via `fswatch` (macOS) / `inotify` (Linux). Whenever a session JSONL changes and the session has ended (last-line within N seconds quiescent), invokes `agentlens import claude-session --id <id>`.

`--watch codex-sessions` monitors `~/.codex/sessions/` analogously. The watcher also picks up moves into `~/.codex/archived_sessions/` (Codex's archive step on session end) and treats them as the canonical "session ended" signal, then invokes `agentlens import codex-session --id <id> --include-archived`.

Daemon is **opt-in**. Default install path uses explicit `agentlens import claude-session --latest` / `agentlens import codex-session --latest` so the user can run them on demand without a long-lived process.

### 4.4 Parent-link env contract

The orchestrator → child linkage is carried by a single env var:

```
AGENTLENS_PARENT_RUN_ID=<container_run_id>
```

Read by `agentlens run --` (the process wrapper) at startup: if set and non-empty, the new capture run's `parent_run_id` column is populated with the value. If unset, the capture run is a root run (no parent link).

Independent of the existing `AGENTLENS_RUN_ID` env (which is the shim's nested-invocation policy switch — different concept; both may coexist). If both are present, `AGENTLENS_PARENT_RUN_ID` wins. This matters because current nested policy defaults to passthrough when `AGENTLENS_RUN_ID` is inherited; explicit parent linkage is an opt-in signal that a child run must be recorded even inside another AgentLens-wrapped process.

### 4.5 Shim: TTY-detect pass-through

Current shim unconditionally wraps with `agentlens run --`. v1 shim adds an interactive guard near the top:

```bash
# If invoked interactively (stdin is a TTY) AND the agent is one whose
# interactive mode uses a TUI we cannot safely wrap, skip recording and
# pass through. A separate post-session ingest mechanism captures the
# transcript from the agent's own session log.
if [ -t 0 ]; then
  case "{name}" in
    claude)
      case "${{1:-}}" in
        -p|--print|--output-format) ;;  # non-TTY mode → wrap
        *) exec "$REAL_PATH" "$@" ;;     # interactive TUI → pass-through
      esac
      ;;
    codex)
      # codex exec is non-interactive and safe to wrap.
      # All other subcommands (default interactive, resume, fork, review,
      # apply, login, mcp, app, ...) either open a TUI or interact with
      # external systems we should not pipe-wrap.
      case "${{1:-}}" in
        exec|e) ;;  # wrap
        *) exec "$REAL_PATH" "$@" ;;
      esac
      ;;
  esac
fi
```

Rationale: AgentLens v0 process wrapper uses `subprocess.Popen + PIPE`, which breaks any TTY-dependent TUI. Rather than build a full pty-based wrapper (heavy, error-prone), we ride on each tool's own canonical session log:

- Claude Code: `~/.claude/projects/<encoded>/<session-id>.jsonl` → `agentlens import claude-session`.
- Codex CLI (interactive `codex`, `codex resume`, `codex fork`): writes to `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` while live; moved to `~/.codex/archived_sessions/` on session end → `agentlens import codex-session`.

**Codex Desktop is not shimmable** (the app launches its bundled `codex` binary directly, not via PATH). Capture for the Desktop app relies entirely on the same rollout JSONL ingest path; the resulting run's `recording.adapter` is `agentlens_session_import` and `meta.originator="Codex Desktop"` so it is distinguishable from CLI runs in queries.

### 4.6 cmux auto-detection at install

`agentlens install claude` detects `/Applications/cmux.app/` at run time. If found and the user explicitly accepts the prompt:

1. Back up `/Applications/cmux.app/Contents/Resources/bin/claude` → `claude.cmux-original` (preserved file mode).
2. Install AgentLens shim at `/Applications/cmux.app/Contents/Resources/bin/claude` with `REAL_PATH = .../claude.cmux-original`.
3. Record cmux app version + binary mtime in `~/.agentlens/cmux-install.json`.
4. `agentlens doctor` detects cmux app version drift, backup drift, permission failure, or missing backup, and prints re-install guidance.

The chain at run time becomes:
```
User types: claude foo
  → /Applications/cmux.app/.../claude          (AgentLens shim)
  → exec agentlens run --agent claude_code -- /Applications/cmux.app/.../claude.cmux-original foo
  → /Applications/cmux.app/.../claude.cmux-original  (cmux's own wrapper, injects --session-id)
  → real claude binary
```
Both wrapping layers (AgentLens recording + cmux session-id injection) work.

The auto-detect prompt must be explicit because it modifies `/Applications/...`. Non-interactive installs require `--yes --cmux` (or equivalent) rather than silently changing the app bundle.

## 5. Interactive Claude Code & Codex Capture (post-session ingest)

Two paths considered:

| Path | Description | Decision |
|------|-------------|----------|
| **A. pty-based wrapper** | Extend AgentLens to spawn child under `pty.openpty()`, forward TTY size/signals, capture all bytes for transcript | **Rejected.** macOS pty quirks, raw-mode pass-through, SIGWINCH propagation, ANSI escape preservation each introduce user-visible risk (input lag, lost keys, garbled UI). The user works in Claude Code / Codex every day; degradation is unacceptable. |
| **B. Session JSONL import** | shim pass-through for interactive `claude` and non-`exec` `codex`; AgentLens ingests each tool's native session log post-hoc | **Accepted.** Both Claude Code and Codex already write canonical, complete per-session JSONLs. Wrapping to capture them again would be duplicate signal. |

Trade-off accepted: **interactive Claude Code and interactive Codex are not recorded in real time.** They are captured after the session ends (either by daemon or by explicit `agentlens import claude-session --latest` / `agentlens import codex-session --latest`). The user sees zero TUI degradation.

The cmux `--session-id` injection plays nicely on the Claude side: cmux assigns the session ID, claude writes its JSONL keyed by that ID, and AgentLens import keys its run by the same ID — so cmux's own session bookkeeping and AgentLens runs share an identifier.

### 5.1 Codex specifics

The Codex side is conceptually identical but the file layout differs:

- Live, running session: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<UUIDv7>.jsonl` (the UUIDv7 is the session id; `codex resume` re-opens by id).
- Session end: Codex moves the file to `~/.codex/archived_sessions/rollout-<ISO>-<UUIDv7>.jsonl`. This move is the canonical "session ended" signal for the watcher.
- First line is always a `session_meta` event whose `payload` carries the session id, originator (`Codex CLI` / `Codex Desktop`), `cwd`, `cli_version`, `model_provider`, and optionally `source.subagent.thread_spawn` (parent thread id, depth, agent role, nickname).

Coverage matrix:

| Codex surface | Capture path |
|---------------|--------------|
| `codex exec` (non-interactive) | Real-time via shim wrapper |
| `codex` (interactive TUI), `codex resume`, `codex fork`, `codex review`, `codex apply` | Post-hoc rollout JSONL import |
| Codex Desktop app | Post-hoc rollout JSONL import (no shim possible) |
| Codex subagent threads (`source.subagent.thread_spawn`) | Same rollout import; child run's `parent_run_id` derived from `parent_thread_id` if the parent thread has been imported |

## 6. kws-claude-multi-agent-executor Changes

Source of truth is `skills/kws-claude-multi-agent-executor/` in this repo. Installed copies under `~/.claude/skills/` are deployment artifacts and must not be patched first.

### 6.1 REMOVE
- `scripts/append_learning_event.py` (~400 lines) — replaced by direct `agentlens event append` calls.
- `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/` writes — no new files created from new runs onward. Existing directory stays read-only for historical inspection.

### 6.2 ADD / MODIFY
- **SKILL.md Phase -1 step b** (state.json init): immediately before writing `state.json`, call:
  ```bash
  ORCH_RUN_ID=$(agentlens run-open --agent kws-cme-orchestrator \
    --workspace "$WORKTREE_ABS" --meta plan="$PLAN_PATH" --meta spec="$SPEC_PATH" \
    2>/dev/null || echo "")
  ```
  Persist `agentlens_orchestration_run` in `state.json` (NULL-safe if AgentLens absent).

- **SKILL.md Phase -1 step d** (headless spawn): add env var before `nohup`:
  ```bash
  AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID" \
  nohup claude -p ... > "$WORKTREE_ABS/.orchestrator/headless.jsonl" 2>&1 &
  ```
  Shim reads env and links child run.

- **SKILL.md all phase/task transitions**: every place that currently invokes `scripts/append_learning_event.py` now becomes:
  ```bash
  if [ -n "${ORCH_RUN_ID:-}" ]; then
    agentlens event append --run "$ORCH_RUN_ID" \
      --type "kws-cme.<event_name>" --payload-json '<json>' 2>/dev/null || true
  fi
  ```
  Reference event taxonomy: `kws-cme.phase_0_started`, `kws-cme.task_started`, `kws-cme.task_completed`, `kws-cme.blocker`, `kws-cme.verification_failed`, `kws-cme.reviewer_warn_or_fail`, `kws-cme.compaction`, `kws-cme.phase_2_complete`.

- **Learning event candidates remain local files.** Existing sub-agent candidate files under `<worktree>/.orchestrator/learning_events/` can stay as the sub-agent → orchestrator handoff mechanism. The orchestrator remains the single writer, but drains those candidates into AgentLens instead of `append_learning_event.py`.

### 6.3 KEEP unchanged
- `state.json` schema (multi-plan `plan_chain[]`, all fields).
- `headless.jsonl` (live monitoring tail; AgentLens transcript is the archival copy).
- `scripts/accumulate_cost.py`, `redact_archive.py`, `validate_method_audit.py`, `archive_run.sh`, `query_state.sh`, `query_run.sh`.
- worktree lifecycle / Phase 0–2 logic.

### 6.4 Cross-cutting
- `scripts/query_run.sh` event-related sub-commands delegate to `agentlens events --type 'kws-cme.*'`.
- `scripts/archive_run.sh` adds optional `--include-agentlens-run` flag bundling the orchestration run's events + child transcripts into the tarball.

## 7. kws-codex-plan-executor Changes

Source of truth is `skills/kws-codex-plan-executor/` in this repo. Installed copies are deployment artifacts.

### 7.1 REMOVE
- `scripts/append_run_event.py` — replaced by direct `agentlens event append` calls.
- `scripts/append_learning_event.py` and `~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/` writes — replaced by AgentLens notable-boundary events. If cross-repository learning aggregation still needs a separate view, build it as an AgentLens query/export, not a second write path.
- `.codex-orchestrator/runs/<run_id>/events.jsonl` writes — no new files from new runs onward.

### 7.2 ADD / MODIFY
- **SKILL.md run init**: `ORCH_RUN_ID=$(agentlens run-open --agent kws-cpe-orchestrator --workspace "$REPO" --meta plan="$PLAN" 2>/dev/null || echo "")`. Persist in `.codex-orchestrator/runs/<run_id>/state.json`; mirror to `.codex-orchestrator/state.json` only as the existing compatibility copy/pointer.
- **SKILL.md codex exec spawn**: prefix with `AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`.
- **All event-emission points**: replace `python scripts/append_run_event.py ...` with `agentlens event append --run "$ORCH_RUN_ID" --type kws-cpe.<event> --payload-json ...`.
- **`scripts/check_run_diffs.py`**: state-diff logic unchanged; events-diff logic delegates to `agentlens events --run`.
- **`scripts/check_learning_log_health.py`**: queries AgentLens for new runs; falls back to old file format for legacy runs.

### 7.3 KEEP unchanged
- `.codex-orchestrator/runs/<run_id>/state.json` as the primary state source, with `.codex-orchestrator/state.json` retained only as the compatibility latest-state copy/pointer.
- `runs/<id>/context.json` (codex-specific context capture).
- `parse_plan.py`, `validate_state.py`, `reconcile_state.py`, `build_context_snapshot.py`.

## 8. Failure Modes & Non-Blocking Invariant

All AgentLens-side failures **must absorb silently** at the boundary between kws skills and AgentLens. The orchestrator never halts because AgentLens is missing or unhappy.

| Failure | Behavior | Recovery |
|---------|----------|----------|
| `agentlens` CLI not on PATH at skill startup | `ORCH_RUN_ID=""`; subsequent `event append` calls become no-ops via empty `--run`; orchestrator runs with no AgentLens coverage | Install AgentLens; next run captures normally |
| `agentlens run-open` errors | exit non-zero captured by `|| echo ""`; `ORCH_RUN_ID=""` | Same as above |
| `agentlens event append` errors mid-run | stderr warning, exit 0, event dropped | No action; next event tries again |
| AGENTLENS_HOME disk full | event/artifact writes fail; warning; orchestrator unaffected | Free disk |
| SQLite index locked or corrupted | Direct `events.jsonl` writes succeed; sqlite index out of sync | `agentlens index rebuild` |
| Shim `REAL_PATH` lockfile drift (sha256 mismatch) | shim falls back to direct passthrough (existing v0 behavior) | `agentlens install <name>` to refresh |
| cmux app updated, our shim overwritten | Recording silently disabled in cmux | `agentlens doctor` warns; user re-runs install |
| Parent run not found at child capture time | Child captured as orphan (no `parent_run_id`); still visible in `agentlens latest` | No action; tree query just misses linkage |

## 9. Migration Plan

### Phase 1 — AgentLens v1 (single PR sequence)
0. Contract reconciliation: update `run.schema.json`, `event.schema.json`, valid/invalid fixtures, `docs/contract.md`, `docs/cli.md`, and `docs/security.md` for run kinds, opaque event namespaces, and transcript artifact policy.
1. Schema migration: `runs.parent_run_id` already exists; add `runs.run_kind`, `runs.agent_label`, `runs.has_transcript`; new indexes.
2. CLI: `run-open`, `run-close`, `event append`, `events`, `import claude-session`.
3. Shim TTY-detect for interactive `claude`; verify `codex exec` vs interactive `codex` behavior before broad wrapping claims.
4. cmux auto-detect + explicit chain install path in `agentlens install claude`.
5. Optional watcher daemon (`agentlens daemon`).
6. Tests (§10).

### Phase 2 — kws-cme migration (dual-write window)
1. SKILL.md changes: add AgentLens calls, **keep** `append_learning_event.py` calls (dual-write).
2. Run 1 week with dual-write; verify event parity (`scripts/compare_logs.py` checks `kws-cme.*` events in AgentLens match `~/.claude/learning/.../events.jsonl`).
3. Remove `append_learning_event.py` invocations from SKILL.md.
4. Delete `scripts/append_learning_event.py`.
5. Mark `~/.claude/learning/kws-claude-multi-agent-executor/` as read-only legacy.

### Phase 3 — kws-cpe migration
Same pattern as Phase 2 with `kws-cpe.*` events.

### Historical data
Optional one-shot: `agentlens import legacy-kws-events <root>` reads existing events.jsonl files and replays them into AgentLens. Provided but not required for the migration to land.

## 10. Test Surface

### AgentLens unit
- `event append` round-trip: payload bytes preserved, ts ordering correct.
- Event schema accepts `kws-cme.task_started` and rejects malformed or reserved-but-unknown namespaces.
- Run-open writes valid `run.json` with `run_kind=container`, `agent.label`, and `recording.has_transcript=false`.
- `parent_run_id` FK behavior: parent delete → children NULL.
- Tree query orders by `(ts, run_id)` deterministically across siblings.
- Import claude-session idempotency: re-import same session-id is a no-op for the run row and does not duplicate transcript artifacts.
- Import codex-session: a synthetic rollout JSONL (with a representative `session_meta` first line — both `Codex CLI` and `Codex Desktop` originators, with and without `source.subagent.thread_spawn`) yields a capture run whose `agent.name=codex_cli`, `recording.transcript_source=codex-rollout-jsonl`, and `input.import_key=codex-rollout:<id>`.
- Import codex-session subagent linkage: importing a parent rollout then a child rollout whose `session_meta.payload.source.subagent.thread_spawn.parent_thread_id` matches the parent populates the child's `parent_run_id`; reverse order also works (parent linkage backfilled at parent-import time, or left null and resolvable via a second pass).
- Import codex-session idempotency: re-importing the same rollout (active or archived) is a no-op for the run row and does not duplicate transcript artifacts.
- Shim TTY-detect (claude): with `-p` flag wraps even if stdin is TTY; without `-p` and stdin TTY → exec REAL directly.
- Shim TTY-detect (codex): `codex exec ...` and `codex e ...` wrap even when stdin is TTY; bare `codex`, `codex resume`, `codex fork`, `codex review`, `codex apply`, `codex login`, `codex mcp`, `codex app` with stdin TTY → exec REAL directly.

### AgentLens integration
- End-to-end: `run-open` → fake `claude -p` spawn → child run exists with correct `parent_run_id` → events query with `--tree` shows ordered parent+child events.
- cmux chain test: install fake cmux wrapper, run `agentlens install claude`, exec the shimmed binary, verify both AgentLens recording present AND original cmux wrapper behavior (e.g. an env marker the wrapper sets) preserved.
- Watcher daemon: write a synthetic session JSONL to a tmp `~/.claude/projects/` path; verify daemon ingests within N seconds.
- Nested override: run a child command with both `AGENTLENS_RUN_ID` and `AGENTLENS_PARENT_RUN_ID`; verify the explicit parent is recorded and the child is not silently passed through.
- Security regression: transcript artifacts are stored only under `artifacts/`, are manifest-covered, and `docs/security.md` reflects the new retention/redaction contract.

### kws-cme integration
- Micro-plan with 2 tasks, run end-to-end with AgentLens installed → orchestration run exists with `kws-cme.phase_0_started`, `task_started` (×2), `task_completed` (×2), `phase_2_complete` events. 2 child runs (one per spawned `claude -p`) linked via `parent_run_id`.
- AgentLens missing scenario: same plan run with AgentLens CLI removed from PATH → orchestrator completes normally, `state.json` reflects all task transitions, no AgentLens-related stderr noise causes Phase test failures.

### kws-cpe integration
- Symmetric to kws-cme.

### Failure isolation
- Mid-run: kill AgentLens-related processes, `chmod -w AGENTLENS_HOME` → orchestrator continues, all `event append` exit 0.
- SQLite locked: hold an exclusive lock during a task transition → orchestrator unaffected, events still flushed to JSONL.

## 11. Open Questions Resolved (record of brainstorm decisions)

| # | Question | Decision |
|---|----------|----------|
| 1 | What does orchestrator do if AgentLens CLI absent? | Silent skip; orchestrator continues with its own state.json. During dual-write, legacy logging may still run for parity. After cutover, there is no fallback file event log. |
| 2 | What about `headless.jsonl` (kws-cme live tail)? | Keep as-is. AgentLens events/artifacts are the archival substrate; `headless.jsonl` serves live Monitor scripts and can be archived separately if needed. |
| 3 | cmux chaining install — opt-in / auto-detect / silent? | Auto-detect, prompt user once at install. Default "yes". |
| 4 | `accumulate_cost.py` — in B+ scope? | Out of scope. v2 separate. |
| 5 | Interactive Claude Code — wrap with pty or import session JSONL? | Import session JSONL. Pty wrapper too risky for daily-use TUI. |
| 6 | events.jsonl absorption requires AgentLens to know event semantics? | No. Type strings are opaque; payload is opaque JSON. Each skill defines its own namespace. |
| 7 | state.json absorption (option C)? | Rejected. Coupling and blast-radius cost too high. |
| 8 | Codex CLI / Codex Desktop coverage — wrap or import? | Same as Claude. Wrap `codex exec`; import everything else from `~/.codex/sessions/` rollout JSONL (and `~/.codex/archived_sessions/` for ended sessions). Desktop is import-only because the app launches its bundled binary directly, bypassing PATH. |

## 12. Out of Scope (Explicit Non-Commitments)

- **Cost accounting unification** (`accumulate_cost.py`).
- **Event-sourced state** (option C in brainstorming).
- **Live transcript capture for interactive Claude Code** (we use post-session ingest).
- **Cross-machine sync** of AgentLens runs.
- **UI/dashboard** for browsing runs (CLI only in v1).
- **Slack/email notifications** on orchestrator events.
- **Migrating historical kws event logs** (optional import provided, not required).

## 13. Definition of Done

- AgentLens v1 ships with contract/schema docs updated, schema migration, additive CLI commands, TTY-aware shim, cmux auto-detect.
- kws-cme runs a 2-task plan end-to-end with AgentLens active and produces one orchestration run + two child runs in AgentLens; `append_learning_event.py` deleted; `~/.claude/learning/.../runs/` no longer written.
- kws-cpe same as above with its own taxonomy; both its project-local event journal and user-local learning log writes are removed after parity.
- All failure-isolation tests (§10) pass: orchestrator unaffected when AgentLens disk full, CLI missing, or SQLite locked.
- `agentlens import claude-session --latest` works against a real Claude Code session JSONL on the user's machine.
- `agentlens import codex-session --latest` works against a real Codex rollout JSONL on the user's machine, including a session originated from Codex Desktop (`originator="Codex Desktop"` preserved in run meta).
- `agentlens doctor` reports green on a freshly-installed system; reports cmux drift correctly after a simulated cmux update.
