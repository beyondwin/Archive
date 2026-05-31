# Cross-cutting: AgentLens emit sites, candidate drain & health probe

Canonical catalog of where the orchestrator talks to AgentLens, the
sub-agent → orchestrator candidate-file handoff, and the v2.21 reachability probe.
The v2.17 cutover removed the legacy `append_learning_event.py` helper after
parity verification (`scripts/compare_agentlens_events.py`); AgentLens is now the
sole event sink. See `references/learning-log.md` for event-type semantics and
the privacy contract, and `cross-cutting/state-schema.md` for the two run-level
`agentlens_*` fields.

## Single-writer invariant

Only the **orchestrator** invokes `agentlens`. Sub-agents NEVER emit AgentLens
events directly — they write event *candidates* as JSON files under
`<orch_dir>/learning_events/<task_id>-<role>.json`, and the orchestrator reads,
validates, and forwards them. Any sub-agent prompt that instructs direct
`agentlens` invocation is a bug.

**Every `agentlens` invocation is `2>/dev/null || true`.** Observability failure
must never block plan execution. Emit sites guarded by `[ -n "${ORCH_RUN_ID:-}" ]`
become silent no-ops when no run is open.

## `ORCH_RUN_ID` lifecycle

- **Open** (Phase -1 step b): `agentlens run-open` returns the run ID, captured
  into `ORCH_RUN_ID` and persisted as `state.agentlens_orchestration_run`.
- **Resume** (any resume path): re-derive once near the top of Phase 0 Step 0 —
  `ORCH_RUN_ID="${AGENTLENS_PARENT_RUN_ID:-$(jq -r '.agentlens_orchestration_run // ""' "$ORCH_DIR/state.json")}"`.
  The env var (set by Phase -1 step d / Resume Chain) wins; state.json is the
  fallback. Empty → every emit no-ops.
- **Chain handoff**: Resume Chain propagates `AGENTLENS_PARENT_RUN_ID`
  (= parent `ORCH_RUN_ID`) into the chained child's env; the child re-exports it
  so the whole chain publishes to one run. Chained children do NOT open a new run.
- **Close** (Phase 2 Step 2): `agentlens run-close --outcome success` after the
  final emit. Idempotent — re-entry is a no-op.

## Emit-site catalog

| Phase / step | Event | Helper / mechanism |
|--------------|-------|--------------------|
| Phase -1 step b | run open | `agentlens run-open` (+ health probe) |
| Phase 0 Step 7.5 | `kws-cme.phase_0_started` | `phase_boundary.py phase-emit --type phase_0_started` (bundles `timestamps.started_at` setdefault) |
| Phase 1 Step 2.6 | `kws-cme.task_completed` | bundled into `phase_boundary.py task-complete` |
| Phase 1 Step 3.5 | `kws-cme.<event_type>` per candidate | drain `<orch_dir>/learning_events/` (see below) |
| Phase Transition T3 | `kws-cme.compaction` | `phase_boundary.py phase-emit --type compaction` (emit-only, no timestamp) |
| Phase Transition T3 | `kws-cme.context_health` | drain `context_health` candidates (observation-only) |
| Phase Transition T3 / Phase 2 Step 0 | `chain_trigger_eval` | one per evaluation regardless of decision (trigger-lift telemetry) |
| Phase 2 Step 2 | `kws-cme.phase_2_complete` | `phase_boundary.py phase-emit --type phase_2_complete` (bundles `timestamps.completed_at` overwrite) |
| Phase 2 Step 2 | run close | `agentlens run-close --outcome success` |
| Per API dispatch | `kws-cme.dispatch_via_api` | `scripts/dispatch_via_api.py` `dispatch()` `_emit_agentlens()` (see below) |
| Phase 2 Step 0 (batch fallback) | `kws-cme.batch_timeout` | `scripts/dispatch_final_sweep_batch.py` on poll-timeout before per-task API fallback |
| Hard-halt paths | `kws-cme.blocker` + run close | escalation-exhaustion / budget pause / T3 state-write failure → `run-close --outcome aborted\|blocked` |

The three boundary emits (`phase_0_started`, `compaction`, `phase_2_complete`)
and the two task-boundary writes (`task-start`, `task-complete`) are bundled into
`scripts/phase_boundary.py` so the paired state write + emit cannot be skipped
independently — the recurring "prose-only mandatory step silently skipped"
regression (v2.21 D002). `check_skill_contract.py`'s V221 block verifies these
emit sites are wired into the phase references.

## `kws-cme.dispatch_via_api` (per-dispatch observability, v2.22 §2.B5)

Emitted by `scripts/dispatch_via_api.py` `dispatch()` via the best-effort
`_emit_agentlens()` shim (a guarded `agentlens event append` subprocess, swallows
all failures). One event fires per API dispatch on BOTH outcomes:

- **Success** — after the tool result is extracted and the cost ledger is
  accumulated; carries the real usage/cache numbers.
- **Failed-after-retry (ENV_BLOCKER)** — when a retryable error exhausts
  `max_retries` (or a non-retryable error fires), just before the ENV_BLOCKER
  ESCALATE dict is returned; token/cache fields are zero (unknown on failure) so
  the schema stays uniform.

This event does NOT pass through the single-writer candidate-drain path: it is a
direct best-effort emit from the dispatch helper, not a sub-agent candidate file.

Field schema:

| Field | Type | Meaning |
|-------|------|---------|
| `event` | string | always `"kws-cme.dispatch_via_api"` |
| `role` | string | dispatched headless role (`plan_reviewer` / `verifier` / `docs_updater` / `transition_combined`) |
| `model` | string | claude model id used for the dispatch |
| `input_tokens` | int | API `usage.input_tokens` (`0` on failed-after-retry) |
| `cache_read_tokens` | int | API `usage.cache_read_input_tokens` (`0` on failed-after-retry) |
| `output_tokens` | int | API `usage.output_tokens` (`0` on failed-after-retry) |
| `cache_hit_ratio` | float | `cache_read_tokens / input_tokens`, rounded 4dp (`0.0` when no input tokens or on failure) |
| `wall_ms` | int | wall time from the pre-retry-loop `monotonic` start to emit, in ms |
| `retries` | int | retry attempt count (`0` = first attempt succeeded; on failure = attempts consumed) |

## Candidate drain (Phase 1 Step 3.5 & T3)

Sub-agents emit observations by writing JSON candidate files; the orchestrator
drains them:

1. Scan `<orch_dir>/learning_events/` for `<task_id>-<role>.json` candidates.
2. Validate against the privacy contract (no secrets, no absolute home/worktree
   paths, no full transcripts — see `references/learning-log.md`).
3. Publish each as `kws-cme.<event_type>` to the open run.

`context_health` is **observation-only** (v2.10): emitted at T3 and chained-child
startup, counting compaction index / completed tasks / chain handoffs. It MUST
NOT alter orchestrator control flow (Goodhart's-law guard) — behavior changes
require a follow-on experiment after ≥ 2 weeks of real-run data.

## Health probe (v2.21)

`state.agentlens_healthy` (`bool | null`, run-level) records the one-shot
reachability probe at Phase -1 step b: `true` iff `agentlens run-open` returned a
non-empty run ID (CLI present AND registry write succeeded), `false` otherwise.
Preserved across plan_chain swaps and Resume Chain handoffs like
`agentlens_orchestration_run`.

Purpose is post-run forensics: an empty event stream is otherwise ambiguous
(nothing happened vs. every emit silently no-op'd on an unreachable CLI), and this
boolean disambiguates. `null` means the probe never ran (pre-v2.21 state.json);
treat `null` like `false` for audit purposes.
