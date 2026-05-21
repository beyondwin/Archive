# AgentLens v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build AgentLens v0 as a local-first run evidence system that records new Claude/Codex/generic agent executions, preserves durable artifacts, and evaluates agent claims with deterministic checks.

**Architecture:** AgentLens v0 is split into Core and Adapters. Core owns the CLI, durable run store, schemas, redaction, manifest sealing, SQLite index, and deterministic evaluator. Adapters provide process shim, Claude Code hooks/plugin integration, Codex CLI integration, and Codex App experimental/watcher integration without making agent execution depend on AgentLens success.

**Tech Stack:** Python 3.11+, Typer for CLI, **jsonschema as the contract source of truth** with optional Pydantic models generated from schemas for IDE/runtime convenience (schemas are authoritative — drift must fail CI), SQLite standard library, pytest, ruff, pyright, POSIX shell scripts for shims (Windows is out of v0 scope; document explicitly).

---

## 0. Scope

### In v0

- New run recording only.
- Durable source of truth under `~/.agentlens/runs/<workspace_id>/<run_id>/`.
- Workspace pointer under `<workspace>/.agentlens/`.
- SQLite as a rebuildable index cache.
- JSON contracts for `run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`.
- Deterministic evaluator.
- `off`, `minimal`, `full` recording modes.
- Process wrapper and shim integration.
- Claude Code plugin/hooks integration.
- Codex CLI shim/config integration.
- Codex App `native-experimental` probe and `watcher-only` fallback.
- CLI query commands for latest run, status, failures, risks, and garbage collection.

### Explicitly deferred

- Legacy log importer.
- Dashboard / Studio.
- MCP API.
- Automatic patch queue.
- LLM judge.
- Cross-run lesson compiler.
- Eval fixture generator.
- Cloud sync.
- External observability exporter.

---

## 1. Proposed Project Layout

Use this layout for a new AgentLens repository.

```text
agentlens/
  pyproject.toml
  README.md
  docs/
    architecture.md
    contract.md
    integrations.md
    security.md
    cli.md
  src/
    agentlens/
      __init__.py
      cli.py
      config.py
      constants.py
      ids.py
      time.py
      store/
        __init__.py
        paths.py
        writer.py
        manifest.py
        sqlite_index.py
        retention.py
      schema/
        __init__.py
        models.py
        validate.py
        jsonschema/
          run.v1.json
          event.v1.json
          final.v1.json
          eval.v1.json
          manifest.v1.json
      evaluator/
        __init__.py
        checks.py
        engine.py
        failures.py
      redaction/
        __init__.py
        patterns.py
        redact.py
      adapters/
        __init__.py
        process.py
        shims.py
        claude.py
        codex_cli.py
        codex_app.py
        generic.py
      commands/
        __init__.py
        start.py
        mark.py
        attach.py
        final.py
        eval.py
        show.py
        install.py
        doctor.py
        mode.py
        gc.py
  tests/
    fixtures/
      minimal_run/
      failed_command_run/
      missing_final_run/
      residual_risk_run/
      corrupt_manifest_run/
    unit/
      test_paths.py
      test_ids.py
      test_redaction.py
      test_schema_validation.py
      test_manifest.py
      test_sqlite_index.py
      test_evaluator_checks.py
    integration/
      test_cli_lifecycle.py
      test_process_wrapper.py
      test_install_doctor.py
```

---

## 2. Milestone Overview

Milestones are ordered to deliver the **first end-to-end vertical slice as early as possible** (end of M1), then layer query/process/adapter capabilities on top.

| Milestone | Result | Must pass before moving on |
|---|---|---|
| M0 Contract Freeze | Schemas, directory layout, modes, taxonomy, enums documented and validated | All schema examples validate, including invalid-rejection cases |
| **M1 Vertical Slice** | `start` → `mark` → `final` → `seal (pre_eval)` → `eval` → `seal (final)` → minimal `show` callable end-to-end | A user can record a minimal run by hand and read its status from the CLI |
| M2 Evaluator Hardening | Full deterministic check set + failure taxonomy + fixture suite | Each fixture produces the documented eval status/category, byte-equal on re-run |
| M3 SQLite Index | Runs queryable after recording and after full-scan rebuild | Index deletable + rebuildable; GC works without SQLite |
| M4 Query Surface | `status`, `latest`, `failures`, `risks`, `--format json` | All query commands return both human and JSON outputs over fixtures |
| M5 Process Wrapper | `agentlens run -- <command>` with SIGINT handling | Exit code passthrough in all three termination paths (final, cancel, abort) |
| M6 Install / Shim / Doctor | shim install with permission + lockfile checks, doctor in JSON | shim integrity drift detected; consent prompt enforced |
| M7 Claude/Codex Adapters | Claude stream-json subscription, Codex shim, Codex App watcher/native-experimental probe | `doctor integrations` reports accurate levels and falls back correctly |
| M8 Hardening | Redaction, retention (incl. `max_total_store_gb`), non-blocking fault-injection, evaluator determinism | All Task 8.x tests pass; secret/path leakage zero |

Rationale for ordering:

- M1 collapses what was previously "core store + manifest seal" and the "first vertical slice from §15" into a single milestone so that a developer running the project can demo `agentlens show --latest` after the first milestone, not the fourth. Move Tasks 1.1, 1.2, 1.3, plus a minimal evaluator stub (just `schema_valid` + `final_present` checks) and a minimal `show --latest` into M1.
- M2 then deepens the evaluator with the full check set, fixture coverage, and determinism. The basic eval invocation is already proven in M1.
- Query surface (M4) builds on the vertical slice; SQLite (M3) sits between because some query commands need acceleration.
- M5 (process wrapper) and M6 (shim install) are deferred until the contract is provably stable — wrapping agents before the contract is firm produces churn.
- M7 adapters depend on M6 shim infrastructure.
- M8 hardening intentionally last; it adds invariants on top of working features rather than gating early development on redaction.

Implementation note: the original §15 "first useful vertical slice" is now the **exit criterion for M1**, not a post-M4 milestone.

---

## 3. M0 - Contract Freeze

### Task 0.1: Write Contract Documentation

**Files:**
- Create: `docs/contract.md`
- Create: `docs/security.md`
- Create: `docs/integrations.md`
- Create: `docs/cli.md`

- [ ] Write `docs/contract.md` with the canonical run directory:

```text
~/.agentlens/
  agentlens.sqlite
  config.yaml
  runs/
    <workspace_id>/
      <run_id>/
        run.json
        events.jsonl
        final.json
        eval.json
        manifest.json
        artifacts/

<workspace>/
  .agentlens/
    config.yaml
    current-run
    runs/
      <run_id>.json
```

- [ ] Document that `~/.agentlens/runs/...` is the source of truth.
- [ ] Document that SQLite is rebuildable and never canonical.
- [ ] Document that `final.json` is the agent claim and `eval.json` is AgentLens judgment.
- [ ] Write `docs/security.md` with default redaction and retention policy.
- [ ] Write `docs/integrations.md` with integration levels: `off`, `process_shim`, `native_hooks`, `app_protocol`, `watcher`.
- [ ] Write `docs/cli.md` with command contract for `start`, `mark`, `attach`, `final`, `seal`, `eval`, `status`, `latest`, `show`, `failures`, `risks`, `gc`, `install`, `doctor`, `mode`.
- [ ] Run markdown lint if available:

```bash
markdownlint docs/*.md
```

Expected: no broken heading hierarchy or fenced-code formatting errors.

### Task 0.2: Define JSON Schemas

**Files:**
- Create: `src/agentlens/schema/jsonschema/run.v1.json`
- Create: `src/agentlens/schema/jsonschema/event.v1.json`
- Create: `src/agentlens/schema/jsonschema/final.v1.json`
- Create: `src/agentlens/schema/jsonschema/eval.v1.json`
- Create: `src/agentlens/schema/jsonschema/manifest.v1.json`
- Create: `tests/unit/test_schema_validation.py`

All schemas use JSON Schema Draft 2020-12, `additionalProperties: false`, and enforce UTC ISO8601 timestamps via regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$`.

- [ ] Create schema for `run.json`:

Required fields:
```text
schema           const: "agentlens.run.v1"
run_id           string, filesystem-safe
workspace_id     string (sha256 hex)
started_at       UTC ISO8601 with Z
agent.name       enum: claude_code | codex_cli | codex_app | generic
agent.mode       enum: cli | app | code | unknown
workspace.root_label   string
workspace.root_hash    string (sha256)
workspace.id_basis     enum: git | path
recording.mode         enum: minimal | full
recording.adapter      string
```

Optional fields:
```text
parent_run_id          string | null (nested run support)
agent.version          string
workspace.git_remote_hash  string
workspace.git_branch       string
workspace.commit_before    string
input.kind | input.summary | input.hash
```

- [ ] Create schema for `events.jsonl` rows with required fields:

```text
schema           const: "agentlens.event.v1"
event_id         string
run_id           string
ts               UTC ISO8601 with Z
type             enum (see below)
payload          object
```

- [ ] Restrict v0 event `type` to:

```text
run.started
checkpoint.marked
command.started
command.finished
artifact.attached
task.started
task.finished
failure.observed
run.finalized
run.cancelled
```

- [ ] Create schema for `final.json` with required fields:

```text
schema           const: "agentlens.final.v1"
run_id           string
ended_at         UTC ISO8601 with Z
agent_outcome   enum: success | failed | partial | cancelled | unknown
summary          string (max 4096 chars)
changed_files    array of { path_label, path_hash }
verification     array of { kind, command_hash, status, excerpt }
                   excerpt: max 4096 chars
residual_risks   array of { severity, summary }
                   severity enum: low | medium | high | critical
```

Optional when `agent_outcome=cancelled`:
```text
exit_signal      enum: SIGINT | SIGTERM | SIGHUP | other
exit_code        integer
```

- [ ] Create schema for `eval.json` with required fields:

```text
schema           const: "agentlens.eval.v1"
run_id           string
evaluated_at     UTC ISO8601 with Z
status           enum: passed | failed | incomplete | needs_eval | error
agent_outcome    enum: success | failed | partial | cancelled | unknown
checks           array of { name, status, message?, evidence? }
                   status enum: passed | failed | skipped
failures         array of { category, severity, source, blame_scope,
                            recoverability, confidence, summary, evidence }
                   confidence: number in [0,1]
```

- [ ] Create schema for `manifest.json` with required fields:

```text
schema           const: "agentlens.manifest.v1"
run_id           string
sealed_at        UTC ISO8601 with Z
sealed           boolean
sealed_phase     enum: pre_eval | final | recording_incomplete
files            array of { path, sha256 }
redaction        object describing applied policies
```

- [ ] Schema versioning policy comment at the top of each schema file:

```text
# v1 is locked. Breaking changes require v2 alongside v1.
# Additive enum extensions allowed only if consumers tolerate unknown values.
```

- [ ] Write schema validation tests:
  - valid + invalid document per schema
  - enum boundary cases (e.g., `agent.name = "unknown_agent"` rejected)
  - timestamp regex rejects naive datetimes (no Z) and non-UTC offsets
  - `additionalProperties: false` rejects unknown fields
  - `recording.mode` immutability is enforced by writer (covered in Task 1.2 test), schema permits the field

- [ ] Run:

```bash
pytest tests/unit/test_schema_validation.py -v
```

Expected: all schema tests pass, including enum/timestamp/strict-additional-properties rejections.

---

## 4. M1 - Core Store

### Task 1.1: Implement Path and ID Utilities

**Files:**
- Create: `src/agentlens/constants.py`
- Create: `src/agentlens/ids.py`
- Create: `src/agentlens/time.py`
- Create: `src/agentlens/store/paths.py`
- Create: `tests/unit/test_paths.py`
- Create: `tests/unit/test_ids.py`

- [ ] Implement config-independent path resolution:

```text
AGENTLENS_HOME env var
  > ~/.agentlens default
```

- [ ] Implement `workspace_id` as a stable hash from:

```text
git remote URL when available
workspace root path hash fallback
```

- [ ] Implement `run_id` with timestamp plus random suffix:

```text
run_20260518_153000_a1b2c3
```

- [ ] Ensure generated IDs are filesystem-safe.
- [ ] Test that no absolute home path is embedded in `workspace_id`.
- [ ] Run:

```bash
pytest tests/unit/test_paths.py tests/unit/test_ids.py -v
```

Expected: all path and ID tests pass.

### Task 1.2: Implement Run Writer

**Files:**
- Create: `src/agentlens/store/writer.py`
- Create: `src/agentlens/commands/start.py`
- Create: `src/agentlens/commands/mark.py`
- Create: `src/agentlens/commands/attach.py`
- Create: `src/agentlens/commands/final.py`
- Create: `tests/integration/test_cli_lifecycle.py`

- [ ] Implement `agentlens start` to create:

```text
run.json
events.jsonl with run.started
workspace .agentlens/current-run
workspace .agentlens/runs/<run_id>.json pointer
```

- [ ] Implement `agentlens mark <event_type>` to append one event row.
- [ ] Implement `agentlens attach --kind <kind> --path <path>` to copy or reference an artifact according to mode.
- [ ] Implement `agentlens final --outcome <outcome>` to write `final.json` and append `run.finalized`.
- [ ] Make all writes atomic:

```text
write temp file
fsync where practical
rename into place
```

- [ ] Make event append tolerant of process interruption:

```text
one JSON object per line
no trailing array syntax
bad line causes eval failure, not reader crash
```

- [ ] Run:

```bash
pytest tests/integration/test_cli_lifecycle.py -v
```

Expected: a full run directory is created with `run.json`, `events.jsonl`, `final.json`, and workspace pointer files.

### Task 1.3: Implement Manifest Seal (pre-eval / final two-phase)

**Files:**
- Create: `src/agentlens/store/manifest.py`
- Create: `src/agentlens/commands/seal.py`
- Create: `tests/unit/test_manifest.py`

- [ ] Implement two-phase seal:

```text
pre_eval seal:
  - includes run.json, events.jsonl, final.json, artifacts/**
  - sets sealed_phase = "pre_eval"

final seal (after eval.json written):
  - recomputes hashes for all files including eval.json
  - sets sealed_phase = "final" and refreshes sealed_at

recording_incomplete:
  - written by wrapper when normal flow could not complete
  - sealed_phase = "recording_incomplete"
```

- [ ] Store redaction summary in `manifest.json`.
- [ ] Add verification helper that detects changed artifact hash.
- [ ] Test that re-running final seal after eval produces a manifest containing `eval.json` sha256.
- [ ] Run:

```bash
pytest tests/unit/test_manifest.py -v
```

Expected: manifest verification passes for untouched files in both pre_eval and final phases, and fails after a fixture file is modified.

### Task 1.4: Vertical-Slice Evaluator Stub and Show

**Files:**
- Create: `src/agentlens/evaluator/engine.py` (stub; full implementation in M2)
- Create: `src/agentlens/commands/eval.py`
- Create: `src/agentlens/commands/show.py` (minimal; expands in M4)
- Modify: `src/agentlens/cli.py`
- Modify: `tests/integration/test_cli_lifecycle.py` (created in Task 1.2)

This task closes the vertical slice. It is intentionally minimal — full evaluator and full query surface come in M2/M4.

- [ ] Implement minimal evaluator producing `eval.json` with only two checks:
  - `schema_valid` — run/event/final/manifest validate against jsonschema
  - `final_present` — final.json exists
- [ ] Status resolution for the stub:

```text
missing final           -> incomplete
schema invalid          -> failed
both pass               -> passed (warning: stub only)
```

- [ ] Implement minimal `agentlens show --latest` printing:

```text
run_id
workspace_id (truncated)
agent_outcome (from final.json)
eval_status (from eval.json)
sealed_phase (from manifest.json)
```

- [ ] Wire CLI: `agentlens start`, `agentlens mark`, `agentlens final`, `agentlens seal`, `agentlens eval`, `agentlens show --latest` all reachable.
- [ ] Integration test: end-to-end manual run from `start` to `show` succeeds without touching M2/M3/M4 code.
- [ ] Run:

```bash
pytest tests/integration/test_cli_lifecycle.py -v
```

Expected: the §15 vertical slice works end-to-end at the end of M1.

---

## 5. M2 - Deterministic Evaluator

### Task 2.1: Implement Evaluator Check Model

**Files:**
- Create: `src/agentlens/evaluator/checks.py`
- Create: `src/agentlens/evaluator/failures.py`
- Create: `tests/unit/test_evaluator_checks.py`

- [ ] Implement check result fields:

```text
name
status
message
evidence
```

- [ ] Implement failure fields:

```text
category
severity
source
blame_scope
recoverability
confidence
summary
evidence
```

- [ ] Implement categories:

```text
MISSING_FINAL
INVALID_FINAL_SCHEMA
MISSING_VERIFICATION_EVIDENCE
UNACKNOWLEDGED_FAILED_COMMAND
SUCCESS_WITH_RESIDUAL_RISK
ARTIFACT_HASH_MISMATCH
MANIFEST_NOT_SEALED
COMMAND_TIMEOUT
ENVIRONMENT_BLOCKER
DIFF_SCOPE_UNKNOWN
CHANGED_FILES_MISSING
AGENT_REPORTED_GAP
USER_CORRECTION
UNKNOWN
```

- [ ] Test serialization to valid `eval.json` shape.
- [ ] Run:

```bash
pytest tests/unit/test_evaluator_checks.py -v
```

Expected: check and failure objects serialize deterministically.

### Task 2.2: Implement Evaluator Engine

**Files:**
- Create: `src/agentlens/evaluator/engine.py`
- Create: `src/agentlens/commands/eval.py`
- Modify: `tests/unit/test_evaluator_checks.py`
- Create: `tests/fixtures/minimal_run/`
- Create: `tests/fixtures/failed_command_run/`
- Create: `tests/fixtures/missing_final_run/`
- Create: `tests/fixtures/residual_risk_run/`
- Create: `tests/fixtures/corrupt_manifest_run/`

- [ ] Implement these checks:

```text
schema_valid
run_started
events_well_formed
final_present
agent_outcome_valid
verification_present
commands_resolved
failed_commands_acknowledged
changed_files_present_when_success
residual_risks_explicit
manifest_sealed
artifact_hashes_valid
```

- [ ] Implement status resolution:

```text
any evaluator crash -> error
missing final -> incomplete
missing eval before command -> needs_eval only in query layer
any failed required check -> failed
all required checks pass -> passed
```

- [ ] Ensure `agent_outcome=success` with no verification becomes `failed`.
- [ ] Ensure `agent_outcome=success` with residual risk becomes `failed` or `incomplete` according to severity policy:

```text
low residual risk + explicit verification -> passed with warning
medium/high/critical residual risk -> failed
```

- [ ] Run:

```bash
pytest tests/unit/test_evaluator_checks.py -v
pytest tests/integration/test_cli_lifecycle.py -v
```

Expected: each fixture produces the expected `eval.json` status and failure category.

---

## 6. M3 - SQLite Index

### Task 3.1: Implement Rebuildable Index

**Files:**
- Create: `src/agentlens/store/sqlite_index.py`
- Create: `tests/unit/test_sqlite_index.py`

- [ ] Create tables:

```text
runs
checks
failures
artifacts
```

- [ ] Store only data that can be rebuilt from run artifacts:

```text
run_id
workspace_id
started_at
ended_at
agent_name
agent_mode
recording_mode
eval_status
failure_category
failure_severity
artifact_path
artifact_sha256
```

- [ ] Implement `index_run(run_dir)`.
- [ ] Implement `rebuild_index(agentlens_home)`.
- [ ] Test deleting `agentlens.sqlite` and rebuilding from fixture directories.
- [ ] Run:

```bash
pytest tests/unit/test_sqlite_index.py -v
```

Expected: rebuilt index matches original indexed rows.

---

## 7. M4 - CLI Query Commands

### Task 4.1: Implement Status and Show

**Files:**
- Create: `src/agentlens/commands/show.py`
- Modify: `src/agentlens/cli.py`
- Modify: `tests/integration/test_cli_lifecycle.py` (created in Task 1.2)

- [ ] Implement `agentlens latest`.
- [ ] Implement `agentlens status`.
- [ ] Implement `agentlens show --latest`.
- [ ] Implement `agentlens show <run_id>`.
- [ ] For missing `eval.json`, show `needs_eval`.
- [ ] Output must distinguish:

```text
agent_outcome from final.json
eval_status from eval.json
recording status from manifest/evaluator errors
```

- [ ] Run:

```bash
pytest tests/integration/test_cli_lifecycle.py -v
```

Expected: CLI prints current run status without exposing absolute home paths.

### Task 4.2: Implement Failures and Risks

**Files:**
- Modify: `src/agentlens/commands/show.py`
- Modify: `tests/integration/test_cli_lifecycle.py` (created in Task 1.2)

- [ ] Implement `agentlens failures`.
- [ ] Implement `agentlens risks`.
- [ ] `failures` should read evaluator failures from `eval.json`.
- [ ] `risks` should combine:

```text
final.json residual_risks
eval.json failures
recording_incomplete indicators
```

- [ ] Run:

```bash
pytest tests/integration/test_cli_lifecycle.py -v
```

Expected: a run with residual risk appears in `risks`, and a run with missing verification appears in `failures`.

---

## 8. M5 - Process Wrapper

### Task 5.1: Implement `agentlens run -- <command>`

**Files:**
- Create: `src/agentlens/adapters/process.py`
- Modify: `src/agentlens/cli.py`
- Create: `tests/integration/test_process_wrapper.py`

- [ ] Start a run before launching the child process.
- [ ] Record `command.started`.
- [ ] Capture exit code and duration.
- [ ] Capture short stdout/stderr excerpts only.
- [ ] Record `command.finished`.
- [ ] Generate final result with three termination paths:

```text
normal exit + explicit final.json present
  -> respect agent-written final.json

normal exit 0 + no explicit final
  -> agent_outcome = unknown

normal exit non-zero + no explicit final
  -> agent_outcome = failed, exit_code recorded

SIGINT / SIGTERM (signum captured via signal handler in wrapper)
  -> agent_outcome = cancelled
  -> exit_signal field set, exit code = 128 + signum (POSIX convention)
```

- [ ] Install signal handler in wrapper that flushes events.jsonl, writes a `final.json` with `agent_outcome=cancelled` if no explicit final exists, then re-raises the signal.
- [ ] Seal (pre_eval), evaluate, then re-seal (final) after process exit. On any AgentLens-side step failure, manifest is written with `sealed_phase: recording_incomplete` and process exit code is **still preserved**.
- [ ] Return the child process exit code exactly (or 128+signum on signal termination).
- [ ] Run:

```bash
pytest tests/integration/test_process_wrapper.py -v
```

Expected: wrapper records the command while preserving the command's exit code in all three termination paths.

---

## 9. M6 - Install, Shim, and Doctor

### Task 6.1: Implement Mode Configuration

**Files:**
- Create: `src/agentlens/config.py`
- Create: `src/agentlens/commands/mode.py`
- Create: `tests/unit/test_config.py`

- [ ] Implement config priority:

```text
command flag
environment variable
workspace config
user config
default
```

- [ ] Implement `AGENTLENS_DISABLE=1` override.
- [ ] Implement `AGENTLENS_MODE=off|minimal|full`.
- [ ] Implement `agentlens on`, `agentlens off`, `agentlens mode minimal`, `agentlens mode full`.
- [ ] Run:

```bash
pytest tests/unit/test_config.py -v
```

Expected: mode resolution follows priority and disable always wins.

### Task 6.2: Implement CLI Shims

**Files:**
- Create: `src/agentlens/adapters/shims.py`
- Create: `src/agentlens/commands/install.py`
- Create: `src/agentlens/commands/doctor.py`
- Create: `tests/integration/test_install_doctor.py`
- Create: `tests/unit/test_shim_security.py`

- [ ] Implement shim path with restrictive permissions:

```text
~/.agentlens/shims/                       (0700, owner = current user)
~/.agentlens/shims/claude                 (0755, owner = current user)
~/.agentlens/shims/codex                  (0755, owner = current user)
~/.agentlens/shims/<name>.real            (lockfile: real binary path + sha256)
```

- [ ] Shim behavior:

```text
1. read <name>.real lockfile and verify real binary sha256 still matches
   (if mismatch: print warning to stderr, fall back to pass-through, no recording)
2. if AGENTLENS_RUN_ID is already set:
     a. AGENTLENS_NESTED_POLICY=passthrough (default): exec real binary, no recording
     b. AGENTLENS_NESTED_POLICY=nested: start new run with parent_run_id=$AGENTLENS_RUN_ID
3. pass through admin/auth/update/plugin/mcp commands
4. start AgentLens when enabled
5. set AGENTLENS_RUN_ID and AGENTLENS_RUN_DIR
6. install SIGINT/SIGTERM trap to call `agentlens cancel`
7. exec real binary
8. seal/eval after exit where possible
9. return original exit code (or 128+signum on signal termination)
```

- [ ] `agentlens install`: prompt for explicit consent before modifying PATH (`--yes` to bypass for CI).
- [ ] `agentlens doctor`: verify shim dir/file permissions and lockfile integrity; print warnings if drift detected.
- [ ] Test that a shim with a tampered real-binary sha256 falls back to pass-through.
- [ ] Test that nested shim invocation honors `AGENTLENS_NESTED_POLICY`.
- [ ] Implement `agentlens doctor integrations`.
- [ ] Doctor output must include:

```text
Claude Code: full | shim-only | unavailable
Codex CLI: full | shim-only | unavailable
Codex App: native-experimental | watcher-only | unavailable
Fallback watcher: available | unavailable
Shim integrity: ok | drift_warning
```

- [ ] All doctor/status/show/latest commands must support `--format json`.
- [ ] Run:

```bash
pytest tests/integration/test_install_doctor.py -v
pytest tests/unit/test_shim_security.py -v
```

Expected: shims install into a temp home with correct permissions, pass-through commands are recognized, nested-invocation policy is honored, doctor prints deterministic integration levels in both text and JSON formats.

---

## 10. M7 - Claude and Codex Adapters

### Task 7.1: Claude Code Adapter

**Files:**
- Create: `src/agentlens/adapters/claude.py`
- Modify: `src/agentlens/commands/install.py`
- Modify: `src/agentlens/commands/doctor.py`
- Modify: `tests/integration/test_install_doctor.py` (created in Task 6.2)

- [ ] Detect `claude --version`.
- [ ] Detect `claude plugin --help`.
- [ ] Detect hook/plugin capability.
- [ ] Install plugin/hooks only through an explicit AgentLens-owned config block.
- [ ] Backup modified Claude settings before write.
- [ ] Remove only AgentLens-owned config on uninstall.
- [ ] Treat `--bare` as reduced-fidelity mode.
- [ ] Run:

```bash
pytest tests/integration/test_install_doctor.py -v
```

Expected: Claude capability detection does not require network and does not mutate real user config during tests.

### Task 7.2: Codex CLI Adapter

**Files:**
- Create: `src/agentlens/adapters/codex_cli.py`
- Modify: `src/agentlens/commands/install.py`
- Modify: `src/agentlens/commands/doctor.py`
- Modify: `tests/integration/test_install_doctor.py` (created in Task 6.2)

- [ ] Detect `codex --version`.
- [ ] Detect `codex plugin --help`.
- [ ] Detect `codex mcp --help`.
- [ ] Detect `codex app-server --help`.
- [ ] Use shim as the primary v0 integration.
- [ ] Mark plugin/MCP capability as optional and not required for recording.
- [ ] Run:

```bash
pytest tests/integration/test_install_doctor.py -v
```

Expected: Codex CLI reports `full` when shim plus required CLI probes are available.

### Task 7.3: Codex App Adapter

**Files:**
- Create: `src/agentlens/adapters/codex_app.py`
- Modify: `src/agentlens/commands/doctor.py`
- Modify: `tests/integration/test_install_doctor.py` (created in Task 6.2)

- [ ] Detect local Codex session directories:

```text
~/.codex/sessions
~/.codex/archived_sessions
```

- [ ] Detect app-server protocol availability through `codex app-server --help`.
- [ ] Classify integration:

```text
native-experimental when app-server is available
watcher-only when session directories are available
unavailable when neither is available
```

- [ ] Do not promise stable full integration for Codex App.
- [ ] Run:

```bash
pytest tests/integration/test_install_doctor.py -v
```

Expected: Codex App capability is reported conservatively and always includes fallback limitations in doctor output.

---

## 11. M8 - Security, Redaction, Retention

### Task 8.1: Redaction Engine

**Files:**
- Create: `src/agentlens/redaction/patterns.py`
- Create: `src/agentlens/redaction/redact.py`
- Create: `tests/unit/test_redaction.py`

- [ ] Redact secret-like values:

```text
API key
token
password
secret
cookie
authorization header
private key
sk- prefixed key
absolute home path
```

- [ ] Redact command excerpts before writing artifacts.
- [ ] Redact path labels before writing durable store.
- [ ] Preserve hashes for correlation.
- [ ] Run:

```bash
pytest tests/unit/test_redaction.py -v
```

Expected: fixture secrets and absolute home paths do not appear in serialized run artifacts.

### Task 8.2: Retention and Garbage Collection

**Files:**
- Create: `src/agentlens/store/retention.py`
- Create: `src/agentlens/commands/gc.py`
- Create: `tests/unit/test_retention.py`

- [ ] Implement default retention:

```yaml
sealed_runs_days: 30
large_artifacts_days: 7
max_artifact_mb_per_run: 50
max_total_store_gb: 5
keep_eval_summaries: true
```

- [ ] Implement `agentlens gc --dry-run`.
- [ ] Implement `agentlens gc`.
- [ ] Keep `eval.json`, `final.json`, and `manifest.json` summaries when configured.
- [ ] Delete large artifacts according to policy.
- [ ] Enforce `max_total_store_gb`: delete oldest sealed-run artifacts first; never delete eval/final/manifest summaries.
- [ ] Reindex after garbage collection.
- [ ] GC must operate from durable-store full-scan when SQLite is missing (fallback path).
- [ ] Run:

```bash
pytest tests/unit/test_retention.py -v
```

Expected: old large artifacts are removed in real mode and listed only in dry-run mode. SQLite absent + GC still functions.

### Task 8.3: Non-Blocking Invariant Regression Tests

**Files:**
- Create: `tests/integration/test_nonblocking.py`

This task locks down the core invariant from §11.3 of the architecture: AgentLens internal failure must never change the child agent's exit code.

- [ ] Fault-inject manifest write failure (monkeypatch `store.manifest.write` to raise), wrap a child `sh -c 'exit 0'` via `agentlens run`, assert exit code 0.
- [ ] Fault-inject evaluator crash (monkeypatch `evaluator.engine.evaluate` to raise), wrap `sh -c 'exit 42'`, assert exit code 42.
- [ ] Fault-inject SQLite index update failure, wrap `sh -c 'exit 0'`, assert exit code 0 and run directory still on disk.
- [ ] Fault-inject pre_eval seal failure, assert manifest gets `sealed_phase: recording_incomplete` and exit code preserved.
- [ ] Send SIGINT to a long-running child during `agentlens run`, assert:
  - exit code = 128 + SIGINT
  - `final.json.agent_outcome == "cancelled"`
  - `final.json.exit_signal == "SIGINT"`
- [ ] Run:

```bash
pytest tests/integration/test_nonblocking.py -v
```

Expected: every fault-injection scenario preserves child exit code; SIGINT path writes cancelled final and re-raises signal.

### Task 8.4: Determinism Regression Fixture

**Files:**
- Create: `tests/integration/test_eval_determinism.py`

- [ ] For each fixture in `tests/fixtures/*_run/`, run evaluator twice and compare `eval.json` byte-equal after normalizing timestamps to `0000-00-00T00:00:00Z`.
- [ ] Run:

```bash
pytest tests/integration/test_eval_determinism.py -v
```

Expected: deterministic evaluator emits byte-identical output across runs given identical inputs.

---

## 12. Cross-Cutting Acceptance Criteria

- [ ] `agentlens start` creates a durable run directory under `~/.agentlens/runs/<workspace_id>/<run_id>/`.
- [ ] Workspace `.agentlens/` contains only config, `current-runs/<run_id>` markers (multi-concurrent), and pointers.
- [ ] Deleting workspace `.agentlens/` does not delete canonical run artifacts.
- [ ] Deleting `agentlens.sqlite` and rebuilding restores query behavior; GC works without SQLite via full-scan.
- [ ] Two concurrent `agentlens` runs in the same workspace do not corrupt each other's events.jsonl (advisory flock).
- [ ] Nested shim invocation honors `AGENTLENS_NESTED_POLICY` (default passthrough).
- [ ] `final.json` and `eval.json` are separate and never conflated.
- [ ] `eval.json` is preferred over `final.json` for success/failure status.
- [ ] Manifest goes through two seal phases (`pre_eval`, `final`) and includes `eval.json` hash in `final` phase.
- [ ] `AGENTLENS_DISABLE=1` prevents recording.
- [ ] `AGENTLENS_MODE=off` prevents recording unless command flag explicitly enables it.
- [ ] AgentLens internal errors do not change child agent exit code (verified by Task 8.3 fault injection).
- [ ] SIGINT/SIGTERM during `agentlens run` produces `agent_outcome=cancelled` and re-raises signal with exit code 128+signum.
- [ ] No absolute home path is stored by default.
- [ ] No secret-like value is stored by default.
- [ ] `excerpt` fields are bounded to `max_chars` (4096) and produced only by allow-list extractors.
- [ ] All query commands (status, latest, show, failures, risks, doctor) support `--format json`.
- [ ] All timestamps serialize as UTC ISO8601 with trailing `Z`.
- [ ] `workspace_id` includes `id_basis` distinguishing git-based and path-based identity.
- [ ] Shim directory is 0700 and lockfile-verified before each invocation.
- [ ] Codex App is labeled `native-experimental` or `watcher-only`, not stable full.
- [ ] Legacy log import commands are not present in v0 CLI help.
- [ ] Dashboard, MCP, patch queue commands are not present in v0 CLI help.

---

## 13. Recommended Commit Sequence

1. `docs: define agentlens v0 contract`
2. `feat: add agentlens schema validation`
3. `feat: add durable run store with two-phase manifest seal`
4. `feat: add vertical-slice evaluator stub and show --latest`
5. `feat: harden deterministic evaluator with full check set`
6. `feat: add sqlite run index with full-scan rebuild`
7. `feat: add status, failures, risks, --format json`
8. `feat: add process wrapper with SIGINT handling`
9. `feat: add install doctor and shims with permission + lockfile checks`
10. `feat: add claude stream-json and codex integration probes`
11. `feat: add redaction, retention, non-blocking fault-injection tests`
12. `docs: document v0 operations and limitations`

---

## 14. Final Verification Before v0 Tag

Run these commands from the AgentLens repo root.

```bash
ruff check .
pyright
pytest -v
python -m agentlens.cli --help
python -m agentlens.cli doctor integrations --format json
python -m agentlens.cli run -- sh -c 'echo hello'
python -m agentlens.cli latest
python -m agentlens.cli show --latest
python -m agentlens.cli show --latest --format json
python -m agentlens.cli eval --latest
python -m agentlens.cli failures
python -m agentlens.cli risks
python -m agentlens.cli gc --dry-run
```

Expected:

```text
lint and type-check pass
tests pass (including non-blocking fault-injection and determinism suites)
CLI help excludes deferred commands
doctor prints integration levels in both text and JSON
wrapper run creates durable artifacts with sealed_phase=final
latest/show/eval/failures/risks operate on the latest run
SIGINT during `agentlens run` produces agent_outcome=cancelled and exit code 128+signum
```

---

## 15. Execution Guidance

Implement in milestone order. The first useful vertical slice — `start → mark → final → seal (pre_eval) → eval → seal (final) → show --latest` — is the **exit criterion for M1**, not a post-M4 goal.

M1 vertical slice (exit criterion):

```text
agentlens start --agent generic --mode cli
agentlens mark checkpoint.marked --name implementation.started
agentlens final --outcome success
agentlens seal           # pre_eval
agentlens eval --latest  # writes eval.json
agentlens seal --final   # final seal including eval.json hash
agentlens show --latest  # prints run_id, agent_outcome, eval_status, sealed_phase
```

Do not start adapters (M7) before the core run contract (M1) and full evaluator (M2) are passing. Do not add Dashboard, MCP, patch queue, or legacy importer commands while building v0.

When the M1 vertical slice works end-to-end, layer evaluator hardening (M2) and SQLite index (M3) before adding the wrapper (M5) and shim/install (M6) infrastructure that adapters (M7) depend on.

