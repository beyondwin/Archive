# AgentLens Auto-Record + kws-Skill Unification — Design Spec

**Date:** 2026-05-19
**Status:** Draft — pending user review
**Scope:** AgentLens v1 + kws-claude-multi-agent-executor + kws-codex-plan-executor
**Supersedes / extends:** AgentLens v0 (`AgentLens/docs/spec/`, `AgentLens/docs/contract.md`)

## 1. Problem

Today, two orchestrator skills each maintain their own logging stack:

- **kws-claude-multi-agent-executor (kws-cme)** writes `.orchestrator/state.json`, `.orchestrator/headless.jsonl`, and `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl` via `scripts/append_learning_event.py`.
- **kws-codex-plan-executor (kws-cpe)** writes `.codex-orchestrator/state.json` and `.codex-orchestrator/runs/<run_id>/events.jsonl` via `scripts/append_run_event.py`.

Meanwhile AgentLens v0 already captures subprocess transcripts when invoked through its shim, producing a third overlapping record of the same `claude -p` / `codex` runs. The user wants:

1. **AgentLens to activate automatically** for every `claude -p`, `codex`, and interactive Claude Code invocation in every terminal (cmux, iTerm, ghostty, Terminal.app), and for every sub-spawn done by the kws skills.
2. **The kws skills' own transcript/event logging to be eliminated** in favor of AgentLens as the single recording substrate, while preserving each skill's mutable orchestration `state.json` (required for resume).

This spec describes the integration design — what AgentLens gains, what each kws skill loses, and how cross-terminal auto-activation works.

## 2. Goals & Non-Goals

### Goals
- One transcript per `claude` / `codex` invocation, captured by AgentLens, regardless of which terminal the user launched it from.
- One event log per orchestrator run, captured in AgentLens as opaque per-skill event types, queryable across skills.
- Zero-touch developer experience: after install, the user works exactly as before; recording happens transparently.
- Existing kws orchestration state (task graph, baselines, resume points) keeps living in each skill's own `state.json` — AgentLens never owns it.
- Hard non-blocking guarantee: any AgentLens failure (CLI missing, disk full, DB locked) is silently absorbed; orchestrators never halt because of it.

### Non-Goals
- Event-sourced state (option C in brainstorming) — explicitly deferred. AgentLens does not derive `state.json`.
- Real-time transcript capture for interactive Claude Code — uses post-session ingest instead (rationale §5).
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
│           ├─ events.jsonl (command.started/finished)      │
│           ├─ transcript.jsonl                             │
│           └─ meta.json                                    │
└───────────────────────────────────────────────────────────┘

┌──── kws orchestrator (kws-cme / kws-cpe) ─────────────────┐
│  Phase -1:                                                │
│    ORCH=$(agentlens run open --agent <skill>-orchestrator)│
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

┌──── Interactive Claude Code ingest (post-session) ────────┐
│  ~/.claude/projects/<encoded>/<session-id>.jsonl          │
│              │                                            │
│              ▼ (watcher daemon OR explicit import)        │
│   agentlens import claude-session --latest                │
│              │                                            │
│              ▼                                            │
│   Materialized AgentLens run (agent=claude_code,          │
│     has_transcript=True, source=session-jsonl)            │
└───────────────────────────────────────────────────────────┘
```

Two AgentLens run shapes emerge:

| Shape | `has_transcript` | Populated by | Examples |
|-------|:----------------:|--------------|----------|
| **Container run** | False | `agentlens run open` | Orchestrator wrapping its own phase/task events |
| **Capture run** | True | shim wrapper OR session-JSONL import | One `claude -p` / `codex` / interactive Claude Code session |

Container runs can have many capture runs as children (via `parent_run_id`).

## 4. AgentLens v1 Additions

### 4.1 Schema

`runs` table (existing) gains two nullable columns:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `parent_run_id` | TEXT, FK → runs.run_id, ON DELETE SET NULL | NULL | Link capture runs to their orchestrator container; tree queries |
| `has_transcript` | BOOLEAN | TRUE | Distinguish container runs (no transcript) from capture runs |

Indexes added: `(parent_run_id)`, `(type, ts)` on events. Schema migration is automatic at first v1 startup (idempotent `ALTER TABLE` + index create).

`events` table (existing) — no shape change. `type` remains a free-form string; new typing convention is enforced only by docs and CLI lint:

- Reserved namespaces (AgentLens core): `command.*`, `recording.*`, `agentlens.*`.
- Skill namespaces: `kws-cme.*`, `kws-cpe.*`, or any free `<namespace>.*` form. Payload is opaque JSON — AgentLens never introspects.

### 4.2 New CLI commands

#### `agentlens run open`
```
agentlens run open --agent <name> \
  [--workspace <path>] [--parent <run_id>] [--meta <k=v>] [--meta <k=v>]
```
Behavior:
- Creates a container run (`has_transcript=False`).
- Writes `meta.json`, empty `events.jsonl`, no `transcript.jsonl`.
- Prints `<run_id>` to stdout.
- Returns 0 on success; non-zero only on hard failure (e.g. AGENTLENS_HOME unwritable).

#### `agentlens event append`
```
agentlens event append --run <run_id> --type <type_string> \
  (--payload-json <inline> | --payload-file <path> | --payload-stdin) \
  [--ts <iso8601>]
```
Behavior:
- Resolves run via SQLite index. If not found, prints warning to stderr and **exits 0** (non-blocking invariant).
- Appends `{ts, type, payload}` to the run's `events.jsonl`. POSIX `O_APPEND` writes are line-atomic; safe under concurrent appenders.
- Updates derived SQLite `events` row.
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
- Each session JSONL becomes one AgentLens capture run (`agent=claude_code`, `has_transcript=True`, `source=claude-session-jsonl`).
- Transcript is copied (not symlinked) so AgentLens own retention rules apply.
- Events extracted: `command.started`, `command.finished` derived from the session boundaries; tool-use events stored opaque under `claude.tool_use` etc.
- Idempotent: re-importing the same session updates `meta.json` mtime but doesn't duplicate the run (keyed by session-id).
- Optional `--parent <run_id>` for linkage when the user knows the session belongs to a higher-level workflow.

### 4.3 Optional watcher daemon

```
agentlens daemon start [--watch claude-sessions] [--watch <other>]
agentlens daemon stop
agentlens daemon status
```

`--watch claude-sessions` monitors `~/.claude/projects/` via `fswatch` (macOS) / `inotify` (Linux). Whenever a session JSONL changes and the session has ended (last-line within N seconds quiescent), invokes `agentlens import claude-session --id <id>`.

Daemon is **opt-in**. Default install path uses explicit `agentlens import claude-session --latest` so the user can run it on demand without a long-lived process.

### 4.4 Parent-link env contract

The orchestrator → child linkage is carried by a single env var:

```
AGENTLENS_PARENT_RUN_ID=<container_run_id>
```

Read by `agentlens run --` (the process wrapper) at startup: if set and non-empty, the new capture run's `parent_run_id` column is populated with the value. If unset, the capture run is a root run (no parent link).

Independent of the existing `AGENTLENS_RUN_ID` env (which is the shim's nested-invocation policy switch — different concept; both may coexist).

### 4.5 Shim: TTY-detect pass-through

Current shim unconditionally wraps with `agentlens run --`. v1 shim adds an interactive guard near the top:

```bash
# If invoked interactively (stdin is a TTY) AND the agent is one whose
# interactive mode uses a TUI we cannot safely wrap, skip recording and
# pass through. A separate post-session ingest mechanism captures the
# transcript from the agent's own session log.
if [ -t 0 ] && [ "{name}" = "claude" ]; then
  case "${{1:-}}" in
    -p|--print|--output-format) ;;  # non-TTY mode → wrap
    *) exec "$REAL_PATH" "$@" ;;     # interactive → pass-through
  esac
fi
```

Rationale: AgentLens v0 process wrapper uses `subprocess.Popen + PIPE`, which breaks Claude Code's TTY-dependent TUI. Rather than build a full pty-based wrapper (heavy, error-prone), we ride on Claude Code's existing session JSONL.

`codex` has no equivalent TUI — wrap unconditionally.

### 4.6 cmux auto-detection at install

`agentlens install claude` detects `/Applications/cmux.app/` at run time. If found and the user accepts the prompt:

1. Back up `/Applications/cmux.app/Contents/Resources/bin/claude` → `claude.cmux-original` (preserved file mode).
2. Install AgentLens shim at `/Applications/cmux.app/Contents/Resources/bin/claude` with `REAL_PATH = .../claude.cmux-original`.
3. Record cmux app version + binary mtime in `~/.agentlens/cmux-install.json`.
4. `agentlens doctor` detects cmux app version drift or missing backup, prints re-install guidance.

The chain at run time becomes:
```
User types: claude foo
  → /Applications/cmux.app/.../claude          (AgentLens shim)
  → exec agentlens run --agent claude_code -- /Applications/cmux.app/.../claude.cmux-original foo
  → /Applications/cmux.app/.../claude.cmux-original  (cmux's own wrapper, injects --session-id)
  → real claude binary
```
Both wrapping layers (AgentLens recording + cmux session-id injection) work.

The auto-detect prompt defaults to "yes" but is explicit so the user isn't surprised by `/Applications/...` modification.

## 5. Interactive Claude Code Capture (post-session ingest)

Two paths considered:

| Path | Description | Decision |
|------|-------------|----------|
| **A. pty-based wrapper** | Extend AgentLens to spawn child under `pty.openpty()`, forward TTY size/signals, capture all bytes for transcript | **Rejected.** macOS pty quirks, raw-mode pass-through, SIGWINCH propagation, ANSI escape preservation each introduce user-visible risk (input lag, lost keys, garbled UI). The user works in Claude Code every day; degradation is unacceptable. |
| **B. Session JSONL import** | shim pass-through for interactive `claude`; AgentLens ingests `~/.claude/projects/<encoded>/<session-id>.jsonl` post-hoc | **Accepted.** Claude Code already writes a canonical, complete session log. Wrapping to capture it again would be duplicate signal. |

Trade-off accepted: **interactive Claude Code is not recorded in real time.** It's captured after the session ends (either by daemon or by explicit `agentlens import claude-session --latest`). The user sees zero TUI degradation.

The cmux `--session-id` injection plays nicely: cmux assigns the session ID, claude writes its JSONL keyed by that ID, and AgentLens import keys its run by the same ID — so cmux's own session bookkeeping and AgentLens runs share an identifier.

## 6. kws-claude-multi-agent-executor Changes

### 6.1 REMOVE
- `scripts/append_learning_event.py` (~400 lines) — replaced by direct `agentlens event append` calls.
- `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/` writes — no new files created from new runs onward. Existing directory stays read-only for historical inspection.

### 6.2 ADD / MODIFY
- **SKILL.md Phase -1 step b** (state.json init): immediately before writing `state.json`, call:
  ```bash
  ORCH_RUN_ID=$(agentlens run open --agent kws-cme-orchestrator \
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
  agentlens event append --run "$ORCH_RUN_ID" \
    --type "kws-cme.<event_name>" --payload-json '<json>' 2>/dev/null || true
  ```
  Reference event taxonomy: `kws-cme.phase_0_started`, `kws-cme.task_started`, `kws-cme.task_completed`, `kws-cme.blocker`, `kws-cme.verification_failed`, `kws-cme.reviewer_warn_or_fail`, `kws-cme.compaction`, `kws-cme.phase_2_complete`.

### 6.3 KEEP unchanged
- `state.json` schema (multi-plan `plan_chain[]`, all fields).
- `headless.jsonl` (live monitoring tail; AgentLens transcript is the archival copy).
- `scripts/accumulate_cost.py`, `redact_archive.py`, `validate_method_audit.py`, `archive_run.sh`, `query_state.sh`, `query_run.sh`.
- worktree lifecycle / Phase 0–2 logic.

### 6.4 Cross-cutting
- `scripts/query_run.sh` event-related sub-commands delegate to `agentlens events --type 'kws-cme.*'`.
- `scripts/archive_run.sh` adds optional `--include-agentlens-run` flag bundling the orchestration run's events + child transcripts into the tarball.

## 7. kws-codex-plan-executor Changes

### 7.1 REMOVE
- `scripts/append_run_event.py` — replaced by direct `agentlens event append` calls.
- `.codex-orchestrator/runs/<run_id>/events.jsonl` writes — no new files from new runs onward.

### 7.2 ADD / MODIFY
- **SKILL.md run init**: `ORCH_RUN_ID=$(agentlens run open --agent kws-cpe-orchestrator --workspace "$REPO" --meta plan="$PLAN" 2>/dev/null || echo "")`. Persist in `.codex-orchestrator/state.json`.
- **SKILL.md codex exec spawn**: prefix with `AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`.
- **All event-emission points**: replace `python scripts/append_run_event.py ...` with `agentlens event append --run "$ORCH_RUN_ID" --type kws-cpe.<event> --payload-json ...`.
- **`scripts/check_run_diffs.py`**: state-diff logic unchanged; events-diff logic delegates to `agentlens events --run`.
- **`scripts/check_learning_log_health.py`**: queries AgentLens for new runs; falls back to old file format for legacy runs.

### 7.3 KEEP unchanged
- `.codex-orchestrator/state.json` and `runs/<id>/state.json` snapshots.
- `runs/<id>/context.json` (codex-specific context capture).
- `parse_plan.py`, `validate_state.py`, `reconcile_state.py`, `build_context_snapshot.py`.

## 8. Failure Modes & Non-Blocking Invariant

All AgentLens-side failures **must absorb silently** at the boundary between kws skills and AgentLens. The orchestrator never halts because AgentLens is missing or unhappy.

| Failure | Behavior | Recovery |
|---------|----------|----------|
| `agentlens` CLI not on PATH at skill startup | `ORCH_RUN_ID=""`; subsequent `event append` calls become no-ops via empty `--run`; orchestrator runs with no AgentLens coverage | Install AgentLens; next run captures normally |
| `agentlens run open` errors | exit non-zero captured by `|| echo ""`; `ORCH_RUN_ID=""` | Same as above |
| `agentlens event append` errors mid-run | stderr warning, exit 0, event dropped | No action; next event tries again |
| AGENTLENS_HOME disk full | event/transcript writes fail; warning; orchestrator unaffected | Free disk |
| SQLite index locked or corrupted | Direct `events.jsonl` writes succeed; sqlite index out of sync | `agentlens index rebuild` |
| Shim `REAL_PATH` lockfile drift (sha256 mismatch) | shim falls back to direct passthrough (existing v0 behavior) | `agentlens install <name>` to refresh |
| cmux app updated, our shim overwritten | Recording silently disabled in cmux | `agentlens doctor` warns; user re-runs install |
| Parent run not found at child capture time | Child captured as orphan (no `parent_run_id`); still visible in `agentlens latest` | No action; tree query just misses linkage |

## 9. Migration Plan

### Phase 1 — AgentLens v1 (single PR sequence)
1. Schema migration: `runs.parent_run_id`, `runs.has_transcript`; new indexes.
2. CLI: `run open`, `event append`, `events`, `import claude-session`.
3. Shim TTY-detect for interactive `claude`.
4. cmux auto-detect + chain install path in `agentlens install claude`.
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
- Run open without transcript: `has_transcript=False`, no `transcript.jsonl` created.
- `parent_run_id` FK behavior: parent delete → children NULL.
- Tree query orders by `(ts, run_id)` deterministically across siblings.
- Import claude-session idempotency: re-import same session-id is a no-op for the run row.
- Shim TTY-detect: with `-p` flag wraps even if stdin is TTY; without `-p` and stdin TTY → exec REAL directly.

### AgentLens integration
- End-to-end: `run open` → fake `claude -p` spawn → child run exists with correct `parent_run_id` → events query with `--tree` shows ordered parent+child events.
- cmux chain test: install fake cmux wrapper, run `agentlens install claude`, exec the shimmed binary, verify both AgentLens recording present AND original cmux wrapper behavior (e.g. an env marker the wrapper sets) preserved.
- Watcher daemon: write a synthetic session JSONL to a tmp `~/.claude/projects/` path; verify daemon ingests within N seconds.

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
| 1 | What does orchestrator do if AgentLens CLI absent? | Silent skip; orchestrator continues with its own state.json. No fallback to file-based event logging — old infrastructure is removed. |
| 2 | What about `headless.jsonl` (kws-cme live tail)? | Keep as-is. AgentLens transcript is the archival copy; headless.jsonl serves Monitor scripts. |
| 3 | cmux chaining install — opt-in / auto-detect / silent? | Auto-detect, prompt user once at install. Default "yes". |
| 4 | `accumulate_cost.py` — in B+ scope? | Out of scope. v2 separate. |
| 5 | Interactive Claude Code — wrap with pty or import session JSONL? | Import session JSONL. Pty wrapper too risky for daily-use TUI. |
| 6 | events.jsonl absorption requires AgentLens to know event semantics? | No. Type strings are opaque; payload is opaque JSON. Each skill defines its own namespace. |
| 7 | state.json absorption (option C)? | Rejected. Coupling and blast-radius cost too high. |

## 12. Out of Scope (Explicit Non-Commitments)

- **Cost accounting unification** (`accumulate_cost.py`).
- **Event-sourced state** (option C in brainstorming).
- **Live transcript capture for interactive Claude Code** (we use post-session ingest).
- **Cross-machine sync** of AgentLens runs.
- **UI/dashboard** for browsing runs (CLI only in v1).
- **Slack/email notifications** on orchestrator events.
- **Migrating historical kws event logs** (optional import provided, not required).

## 13. Definition of Done

- AgentLens v1 ships with schema migration, four new CLI commands, TTY-aware shim, cmux auto-detect.
- kws-cme runs a 2-task plan end-to-end with AgentLens active and produces one orchestration run + two child runs in AgentLens; `append_learning_event.py` deleted; `~/.claude/learning/.../runs/` no longer written.
- kws-cpe same as above with its own taxonomy.
- All failure-isolation tests (§10) pass: orchestrator unaffected when AgentLens disk full, CLI missing, or SQLite locked.
- `agentlens import claude-session --latest` works against a real Claude Code session JSONL on the user's machine.
- `agentlens doctor` reports green on a freshly-installed system; reports cmux drift correctly after a simulated cmux update.
