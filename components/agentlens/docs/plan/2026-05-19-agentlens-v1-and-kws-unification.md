# AgentLens v1 + kws-Skill Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship AgentLens v1 container runs, opaque skill events, Claude Code session import, TTY-aware shims, and cmux chaining; migrate `kws-claude-multi-agent-executor` and `kws-codex-plan-executor` away from their local event/logging stacks while preserving each skill's mutable resume state.

**Architecture:** AgentLens remains the durable run/event substrate. The canonical store is `run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`, and optional `artifacts/`; SQLite is a rebuildable index. Container runs are orchestration-only parent runs. Capture runs are subprocess/session runs linked by `parent_run_id`. Skill state stays local: `.orchestrator/state.json` for `kws-cme`, and `.codex-orchestrator/runs/<run_id>/state.json` for `kws-cpe`.

**Tech Stack:** Python 3.12, Typer, JSON Schema, SQLite, JSONL, pytest, bash shims, source skill trees under `skills/`.

---

## Engineering Review Findings

| ID | Severity | Finding | Plan correction |
|----|----------|---------|-----------------|
| P0 | Blocker | The previous draft wrote `meta.json` and root-level `transcript.jsonl`, but AgentLens v1 is locked around `run.json` and `events.jsonl`. | All new commands write schema-valid AgentLens artifacts through existing writers. Transcript material, when imported, goes under `artifacts/transcripts/` and is manifest-covered. |
| P1 | Blocker | `agentlens.event.v1` currently rejects `kws-cme.*` and `kws-cpe.*` event names because event `type` is enum-only. | First implementation task extends event schema to support reserved core events plus lowercase namespace events. |
| P2 | Blocker | `agentlens run open` collides conceptually with locked `agentlens run -- <command>`. | Use top-level additive commands: `agentlens run-open` and `agentlens run-close`. |
| P3 | Blocker | Existing nested handling uses `AGENTLENS_RUN_ID`; `AGENTLENS_PARENT_RUN_ID` would be ignored and inherited runs can force passthrough. | Explicit `AGENTLENS_PARENT_RUN_ID` wins over nested passthrough and becomes the child run's `parent_run_id`. |
| P4 | High | The prior plan edited installed skill copies under `~/.claude/skills`. | Edit source files under `skills/` first, then deploy/sync through the normal skill installation path. |
| P5 | High | `kws-cpe` has both a project-local event journal and a user-local learning log. | Migrate both `append_run_event.py` and `append_learning_event.py` after a dual-write parity window. |
| P6 | Medium | The draft assumed interactive `codex` is safe to pipe-wrap. | Wrap `codex exec`; verify interactive `codex` separately before claiming full interactive Codex coverage. |

---

## File Structure

### Create

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/commands/run_open.py` | Create a container run and print `run_id`. |
| `AgentLens/src/agentlens/commands/run_close.py` | Finalize a container run with `final.json`. |
| `AgentLens/src/agentlens/commands/event.py` | `agentlens event append` and query subcommands. |
| `AgentLens/src/agentlens/commands/events.py` | Top-level `agentlens events` alias. |
| `AgentLens/src/agentlens/commands/import_claude_session.py` | `agentlens import claude-session`. |
| `AgentLens/src/agentlens/commands/import_codex_session.py` | `agentlens import codex-session` (Codex CLI + Codex Desktop rollout JSONL). |
| `AgentLens/src/agentlens/store/event_query.py` | Load/filter/merge `events.jsonl` streams. |
| `AgentLens/src/agentlens/store/claude_session.py` | Locate and parse Claude Code session JSONL. |
| `AgentLens/src/agentlens/store/codex_session.py` | Locate and parse Codex rollout JSONL (`~/.codex/sessions/` + `~/.codex/archived_sessions/`). |
| `AgentLens/tests/unit/test_event_query.py` | Pure event-query coverage. |
| `AgentLens/tests/unit/test_claude_session_parser.py` | Claude session parser coverage. |
| `AgentLens/tests/unit/test_codex_session_parser.py` | Codex rollout parser coverage (CLI + Desktop + subagent variants). |
| `AgentLens/tests/integration/test_run_open_close.py` | Container lifecycle integration tests. |
| `AgentLens/tests/integration/test_event_append.py` | Opaque event append/query integration tests. |
| `AgentLens/tests/integration/test_parent_run_linkage.py` | `AGENTLENS_PARENT_RUN_ID` linkage tests. |
| `AgentLens/tests/integration/test_import_claude_session.py` | Claude session import idempotency tests. |
| `AgentLens/tests/integration/test_import_codex_session.py` | Codex rollout import idempotency + subagent linkage tests. |
| `AgentLens/tests/integration/test_cmux_chain.py` | cmux chain install/behavior tests. |
| `AgentLens/tests/integration/test_shim_tty_passthrough.py` | TTY pass-through tests (claude TUI + codex non-`exec`). |

### Modify

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/schema/jsonschema/run.schema.json` | Add optional `run_kind`, `agent.label`, `recording.has_transcript`, `recording.transcript_source`, and `input.import_key`. |
| `AgentLens/src/agentlens/schema/jsonschema/event.schema.json` | Allow reserved AgentLens core events plus lowercase namespaced events. |
| `AgentLens/tests/fixtures/schemas/valid/*.json` | Add valid examples for container runs and skill event types. |
| `AgentLens/tests/fixtures/schemas/invalid/*.json` | Add malformed namespace and reserved-name negative examples. |
| `AgentLens/src/agentlens/store/sqlite_index.py` | Add derived `run_kind`, `agent_label`, `has_transcript`; keep SQLite rebuildable from JSON. |
| `AgentLens/src/agentlens/store/query.py` and `AgentLens/src/agentlens/commands/_format.py` | Surface additive fields without breaking existing JSON output. |
| `AgentLens/src/agentlens/adapters/process.py` | Read `AGENTLENS_PARENT_RUN_ID`; override nested passthrough when explicitly set. |
| `AgentLens/src/agentlens/adapters/shims.py` | Add interactive Claude pass-through; verify/wire `codex exec` behavior. |
| `AgentLens/src/agentlens/commands/install.py` | Add explicit cmux chain install path. |
| `AgentLens/src/agentlens/commands/doctor.py` | Report cmux drift, missing backup, and permission failures. |
| `AgentLens/docs/contract.md` | Document container/capture run additions. |
| `AgentLens/docs/cli.md` | Document new CLI commands and additive query fields. |
| `AgentLens/docs/security.md` | Document transcript artifact policy and retention limits. |
| `skills/kws-claude-multi-agent-executor/SKILL.md` | Add AgentLens container run id and event mirroring. |
| `skills/kws-claude-multi-agent-executor/docs/*` | Replace learning-log source-of-truth references with AgentLens event queries where applicable. |
| `skills/kws-codex-plan-executor/SKILL.md` | Add AgentLens container run id and event mirroring. |
| `skills/kws-codex-plan-executor/docs/*` and `references/*` | Update state/logging docs for AgentLens migration while preserving per-run state. |

### Delete After Cutover

| Path | Reason |
|------|--------|
| `skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py` | Replaced by AgentLens events after parity. |
| `skills/kws-codex-plan-executor/scripts/append_run_event.py` | Replaced by AgentLens events after parity. |
| `skills/kws-codex-plan-executor/scripts/append_learning_event.py` | Replaced by AgentLens events or AgentLens query/export after parity. |

---

# Phase 0 — Contract Reconciliation

### Task 0: Extend AgentLens run/event schemas

**Files:** `run.schema.json`, `event.schema.json`, schema fixtures, `tests/unit/test_schema_validation.py`, `tests/unit/test_writer.py`

- [ ] Add tests proving existing valid run/event fixtures still validate unchanged.
- [ ] Add a valid container run fixture:
  - `run_kind="container"`
  - `agent.name="generic"`
  - `agent.mode="unknown"`
  - `agent.label="kws-cme-orchestrator"`
  - `recording.has_transcript=false`
  - `recording.transcript_source="none"`
- [ ] Add valid event fixtures for `kws-cme.task_started`, `kws-cpe.verification_failed`, `claude.tool_use`, and `codex.tool_use`.
- [ ] Add invalid event fixtures for uppercase namespaces, missing dots, and reserved-but-unknown core names.
- [ ] Extend the `recording.transcript_source` enum in `run.schema.json` to include `"codex-rollout-jsonl"`; add a valid capture-run fixture with `agent.name="codex_cli"`, `recording.transcript_source="codex-rollout-jsonl"`, `input.import_key="codex-rollout:<uuid>"`.
- [ ] Update schemas until all fixture tests pass.
- [ ] Run:

```bash
cd AgentLens
.venv/bin/pytest tests/unit/test_schema_validation.py tests/unit/test_writer.py -v
```

### Task 1: Update AgentLens docs for the new contract

**Files:** `AgentLens/docs/contract.md`, `AgentLens/docs/cli.md`, `AgentLens/docs/security.md`

- [ ] Document `run_kind`, `agent.label`, and transcript source fields in the storage contract.
- [ ] Document `agentlens run-open`, `agentlens run-close`, `agentlens event append`, `agentlens events`, `agentlens import claude-session`, and `agentlens import codex-session` (including the `--include-archived` flag and Codex Desktop coverage note).
- [ ] Clarify that full prompt transcripts are still not captured by the process wrapper.
- [ ] Clarify that imported session JSONL (both Claude and Codex) is stored only under `artifacts/transcripts/`, is manifest-covered, and is subject to retention.

---

# Phase 1 — AgentLens Core

### Task 2: Add SQLite derived columns

**Files:** `AgentLens/src/agentlens/store/sqlite_index.py`, `AgentLens/tests/unit/test_sqlite_index.py`

- [ ] Add idempotent migrations for `run_kind TEXT DEFAULT 'capture'`, `agent_label TEXT`, and `has_transcript INTEGER NOT NULL DEFAULT 0`.
- [ ] Update `index_run()` to derive values from `run.json`, not `meta.json`.
- [ ] Add indexes for `(parent_run_id)` and `(run_kind, started_at DESC)`.
- [ ] Verify rebuild still works from only JSON artifacts.

### Task 3: Add `agentlens run-open` and `agentlens run-close`

**Files:** `commands/run_open.py`, `commands/run_close.py`, `cli.py`, `tests/integration/test_run_open_close.py`

- [ ] `run-open --agent <label> [--workspace <path>] [--parent <run_id>] [--meta k=v]...` creates a valid container `run.json`.
- [ ] `run-open` appends a schema-valid `run.started` event through `append_event`.
- [ ] `run-open` prints only `run_id` to stdout.
- [ ] `run-close --run <id> --outcome <...>` writes `final.json`, indexes best-effort, and exits 0 for unknown run ids with a warning.
- [ ] Tests assert no `meta.json` and no root-level `transcript.jsonl` are created.

### Task 4: Add opaque event append and query

**Files:** `commands/event.py`, `commands/events.py`, `store/event_query.py`, `cli.py`, `tests/integration/test_event_append.py`, `tests/unit/test_event_query.py`

- [ ] `event append` accepts exactly one payload source: `--payload-json`, `--payload-file`, or `--payload-stdin`.
- [ ] It resolves run directories via filesystem-safe lookup, with SQLite as optional acceleration only.
- [ ] It constructs full `agentlens.event.v1` objects with `schema`, `event_id`, `run_id`, `ts`, `type`, and `payload`.
- [ ] It calls `append_event()` so redaction, schema validation, and locking stay centralized.
- [ ] `events --run <id> [--type <glob>] [--since <ts>] [--tree]` emits JSONL to stdout.
- [ ] `--tree` includes all descendants by `parent_run_id`, ordered by `(ts, run_id)`.

### Task 5: Wire explicit parent linkage

**Files:** `adapters/process.py`, `tests/integration/test_parent_run_linkage.py`

- [ ] Read `AGENTLENS_PARENT_RUN_ID` before nested policy resolution.
- [ ] If it is non-empty, record a new child run even when `AGENTLENS_RUN_ID` is inherited.
- [ ] If it is absent, preserve existing `AGENTLENS_RUN_ID` / `AGENTLENS_NESTED_POLICY` behavior.
- [ ] Add tests for explicit parent only, inherited parent only, and both env vars set.

### Task 6: Update shims for TTY behavior

**Files:** `adapters/shims.py`, `tests/integration/test_shim_tty_passthrough.py`

- [ ] Interactive `claude` with TTY and no print-mode flag passes through to the real binary.
- [ ] `claude -p`, `claude --print`, and stream-json print modes still wrap.
- [ ] `codex exec` and the `codex e` alias wrap (even when stdin is a TTY, because `codex exec` is non-interactive by design).
- [ ] All other `codex` subcommands (bare `codex`, `codex resume`, `codex fork`, `codex review`, `codex apply`, `codex login`, `codex mcp`, `codex app`) pass through to the real binary when stdin is a TTY — their transcripts are captured post-hoc by Task 7b's importer.
- [ ] Add a regression test asserting Codex Desktop's bundled binary path (when present) is *not* automatically shimmed — Desktop coverage is import-only by design.

### Task 7: Import Claude Code session JSONL

**Files:** `store/claude_session.py`, `commands/import_claude_session.py`, parser and integration tests

- [ ] Locate `~/.claude/projects/<encoded>/<session-id>.jsonl` by `--latest`, `--id`, `--project`, or `--all`.
- [ ] Parse session boundaries and derive `command.started` / `command.finished` plus opaque `claude.*` events as safe.
- [ ] Copy the source session JSONL to `artifacts/transcripts/<session-id>.jsonl`.
- [ ] Write `run.json` with `run_kind="capture"`, `recording.has_transcript=true`, `recording.transcript_source="claude-session-jsonl"`, and `input.import_key="claude-session:<session-id>"`.
- [ ] Make re-import idempotent by scanning `input.import_key` or maintaining a small import index.

### Task 7b: Import Codex rollout JSONL

**Files:** `store/codex_session.py`, `commands/import_codex_session.py`, `tests/unit/test_codex_session_parser.py`, `tests/integration/test_import_codex_session.py`

- [ ] Locate active rollouts under `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<UUIDv7>.jsonl` and (with `--include-archived`) archived rollouts under `~/.codex/archived_sessions/rollout-<ISO>-<UUIDv7>.jsonl`.
- [ ] Selection flags: `--latest` (most recent by mtime across both trees), `--id <UUIDv7>` (exact match in either tree), `--since <iso8601>` (mtime cutoff), `--all`.
- [ ] Parse the first line as a `session_meta` event; extract `payload.id` (UUIDv7 session id), `payload.timestamp`, `payload.cwd`, `payload.originator` ("Codex CLI" or "Codex Desktop"), `payload.cli_version`, `payload.model_provider`, `payload.source` (string `"vscode"` etc. OR object `{"subagent":{"thread_spawn":{...}}}`).
- [ ] Map subsequent rollout lines into opaque events under the `codex.*` namespace (e.g. `codex.message`, `codex.tool_use`, `codex.tool_result`, `codex.reasoning`); derive `command.started` from `session_meta` and `command.finished` from the last line's timestamp.
- [ ] Copy the source rollout JSONL to `artifacts/transcripts/<session-id>.jsonl` (do not symlink; AgentLens retention/manifest rules must apply uniformly).
- [ ] Write `run.json` with `agent.name="codex_cli"`, `agent.label="codex-cli"` (or `"codex-desktop"` when `originator="Codex Desktop"`), `run_kind="capture"`, `recording.adapter="agentlens_session_import"`, `recording.has_transcript=true`, `recording.transcript_source="codex-rollout-jsonl"`, `input.import_key="codex-rollout:<session-id>"`, and `meta.originator`, `meta.codex_cli_version`, `meta.codex_source` preserved from `session_meta`.
- [ ] When `payload.source.subagent.thread_spawn.parent_thread_id` is present AND a previously imported run exists with `input.import_key="codex-rollout:<parent_thread_id>"`, set the new run's `parent_run_id` to that run.
- [ ] When the parent hasn't been imported yet, record the parent_thread_id in `meta.pending_parent_thread_id` and re-resolve on the next import (or via a doctor-style sweep) — do not silently drop the linkage.
- [ ] Make re-import idempotent by scanning `input.import_key` (matching the rollout filename UUIDv7) — re-importing the same session-id (whether currently active OR archived OR a stale active copy still present after archive) is a no-op for both the run row and the transcript artifact.
- [ ] Tests must include: (a) Codex CLI rollout with `source="vscode"`, (b) Codex Desktop rollout with `originator="Codex Desktop"`, (c) subagent rollout with `source.subagent.thread_spawn` and parent imported, (d) subagent rollout with parent NOT imported yet (pending linkage), (e) the same session_id appearing in both `sessions/` and `archived_sessions/` (only one run created).

### Task 8: Add cmux chain install and doctor checks

**Files:** `commands/install.py`, `commands/doctor.py`, `tests/integration/test_cmux_chain.py`

- [ ] Detect `/Applications/cmux.app/Contents/Resources/bin/claude`.
- [ ] Require explicit user consent or explicit non-interactive flags before modifying the app bundle.
- [ ] Preserve cmux wrapper mode and sha before replacing it with an AgentLens shim.
- [ ] Chain AgentLens shim to the backed-up cmux wrapper, not directly to the real Claude binary.
- [ ] `doctor` reports missing backup, changed backup sha, app version/mtime drift, and permission failures.

### Task 9: AgentLens integration smoke

**Files:** `AgentLens/tests/integration/test_phase1_smoke.py`

- [ ] Create a container run.
- [ ] Append `kws-cme.phase_0_started`.
- [ ] Spawn a fake child under `AGENTLENS_PARENT_RUN_ID`.
- [ ] Append `kws-cme.phase_2_complete`.
- [ ] Close the container run.
- [ ] Import one synthetic Claude session JSONL and one synthetic Codex rollout JSONL under a fake `HOME`; assert both produce capture runs with the expected `transcript_source` and `input.import_key`.
- [ ] Query `agentlens events --run <id> --tree` and assert parent and child events are ordered.
- [ ] Run the full suite:

```bash
cd AgentLens
.venv/bin/pytest -q
```

---

# Phase 2 — `kws-claude-multi-agent-executor` Migration

### Task 10: Add dual-write AgentLens hooks

**Files:** `skills/kws-claude-multi-agent-executor/SKILL.md`

- [ ] In Phase -1 before the first state write, call `agentlens run-open --agent kws-cme-orchestrator --workspace "$WORKTREE_ABS" ... 2>/dev/null || echo ""`.
- [ ] Persist `agentlens_orchestration_run` in `.orchestrator/state.json`.
- [ ] Add `AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"` to every `claude -p` subprocess spawn when the id is non-empty.
- [ ] Mirror existing notable learning events and phase/task transitions into `agentlens event append --type kws-cme.<event>`.
- [ ] Keep existing `append_learning_event.py` during the parity window.
- [ ] Preserve sub-agent candidate-file handoff; only the orchestrator drains candidates into AgentLens.

### Task 11: Validate cme parity and cut over

**Files:** `skills/kws-claude-multi-agent-executor/scripts/compare_agentlens_events.py`, `SKILL.md`, related docs

- [ ] Add a comparison script that maps legacy learning-log events to `kws-cme.*` AgentLens events for a run.
- [ ] Run at least one small plan end-to-end with dual-write.
- [ ] Confirm `state.json` remains resumable when AgentLens is absent.
- [ ] Remove `append_learning_event.py` calls after parity.
- [ ] Delete `scripts/append_learning_event.py`.
- [ ] Update `README.md`, `docs/how-it-works.md`, `docs/usage.md`, `references/learning-log.md`, and troubleshooting docs to point to `agentlens events`.

---

# Phase 3 — `kws-codex-plan-executor` Migration

### Task 12: Add dual-write AgentLens hooks

**Files:** `skills/kws-codex-plan-executor/SKILL.md`, `references/execution-cycle.md`, `references/headless-runner.md`

- [ ] At execution run init, call `agentlens run-open --agent kws-cpe-orchestrator --workspace "$WORKTREE_ABS" ... 2>/dev/null || echo ""`.
- [ ] Persist `agentlens_orchestration_run` in `.codex-orchestrator/runs/<run_id>/state.json`.
- [ ] Keep `.codex-orchestrator/state.json` only as the existing latest-state compatibility copy/pointer.
- [ ] Add `AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"` to `codex exec` headless spawns when non-empty.
- [ ] Mirror project-local event-journal events into `kws-cpe.<event>`.
- [ ] Mirror user-local learning-log events into `kws-cpe.learning.<event>` or another documented `kws-cpe.*` namespace.
- [ ] Keep `append_run_event.py` and `append_learning_event.py` during the parity window.

### Task 13: Validate cpe parity and cut over

**Files:** `skills/kws-codex-plan-executor/scripts/compare_agentlens_events.py`, `SKILL.md`, `docs/state-and-logging.md`, `references/event-journal.md`, `references/learning-log.md`

- [ ] Compare project-local `.codex-orchestrator/runs/<run_id>/events.jsonl` to AgentLens `kws-cpe.*` events.
- [ ] Compare user-local `~/.codex/learning/kws-codex-plan-executor/...` events to AgentLens learning namespace events.
- [ ] Confirm `.codex-orchestrator/runs/<run_id>/state.json` validates and remains the source of truth.
- [ ] Remove `append_run_event.py` and `append_learning_event.py` calls after parity.
- [ ] Delete both scripts.
- [ ] Update state/logging docs and eval expectations.

---

# Final Verification

### Task 14: Cross-skill query and failure-isolation verification

**Files:** AgentLens integration tests, skill evals, docs

- [ ] Run AgentLens unit and integration tests.
- [ ] Run relevant cme deterministic checks, including learning-log/doc freshness checks adjusted for AgentLens.
- [ ] Run relevant cpe deterministic checks, including event-journal and learning-log checks adjusted for AgentLens.
- [ ] Verify AgentLens missing from `PATH` does not halt either orchestrator.
- [ ] Verify unwritable `AGENTLENS_HOME` does not halt either orchestrator.
- [ ] Verify `agentlens events --type 'kws-cme.*'` and `agentlens events --type 'kws-cpe.*'` both return expected events.
- [ ] Verify `agentlens events --run <orchestrator-run> --tree` includes child capture runs.
- [ ] Run `agentlens import claude-session --latest` against the user's real `~/.claude/projects/`; assert a capture run is created and `agentlens events --type 'claude.*' --run <id>` returns events.
- [ ] Run `agentlens import codex-session --latest --include-archived` against the user's real `~/.codex/sessions/` and `~/.codex/archived_sessions/`; assert at least one capture run is created with `meta.originator` preserved (CLI or Desktop) and `agentlens events --type 'codex.*' --run <id>` returns events.

Suggested commands:

```bash
cd AgentLens && .venv/bin/pytest -q
cd skills/kws-claude-multi-agent-executor && bash evals/run.sh
cd skills/kws-codex-plan-executor && bash evals/run.sh
```

---

## Execution Notes

- Do not start implementation from old snippets that mention `meta.json` or root-level `transcript.jsonl`; those were removed by this reviewed plan.
- Do not remove legacy skill logging until dual-write parity has run successfully.
- Do not claim interactive Codex coverage until it is tested under a real TTY.
- Do not run `graphify update .` for this plan-only change; run it after code files change in the implementation session.
