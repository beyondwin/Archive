# D001 — Initial design decisions (per-run shard, helper subcommands, scope)

**Date**: 2026-05-13
**Status**: Decided

## Context

Adopting `kws-codex-plan-executor`'s learning-log pattern for the Claude
executor. Codex side uses a single user-local JSONL (`~/.codex/learning/.../events.jsonl`)
with implicit POSIX `O_APPEND` atomicity. Claude side has additional concurrency
surface: a single repo may host multiple concurrent orchestrators (different
plans, different worktrees), and each orchestrator spawns several sub-agents
that may emit events. Three design questions had to land before writing the spec.

## Question 1 — Log layout: single file vs per-run shard

**Options considered**:

- **A. Single `events.jsonl` + `fcntl.flock(LOCK_EX)` + line size cap** — Codex parity, simple aggregate, but lock contention + atomicity risk above ~3KB lines.
- **B. Date-sharded `events-YYYY-MM-DD.jsonl`** — reduces contention but does not eliminate it; midnight boundary edge cases.
- **C. Per-run directory `runs/<date>/<run_id>/{meta.json, events.jsonl}`** — zero concurrent write to the same file; one directory per orchestrator run; `rm -rf <run-dir>` cleanup; mirrors `~/.claude/tasks/<task-uuid>/` pattern.

**Decision**: **C (per-run shard)**.

Rationale:
- Concurrent-write safety becomes a property of the layout, not a property of
  the helper. No lock code to maintain or get wrong.
- A run's full story (meta + ordered events) is co-located in one directory —
  easier debugging, easier delete/archive.
- Empty events file is fine: `meta.json` alone is a negative signal ("this run
  finished without notable boundaries").
- Forward-compat: aggregator just globs `runs/**/events.jsonl`.
- Tradeoff: more inodes, but at typical use (≤ tens of runs/day) this is irrelevant.

## Question 2 — `run_id` format

**Decision**: `<UTC-compact-timestamp>-<session_short>-<pid>`

Example: `20260513T143321Z-188042f4-48211`

- Timestamp is sort-friendly (lexical order = chronological order).
- `session_short` = first 8 hex chars of `$CLAUDE_SESSION_ID` (matches
  `~/.claude/projects/<encoded-cwd>/<full-uuid>.jsonl` for transcript join).
- `pid` disambiguates two starts in the same second.
- Z suffix on timestamp makes UTC explicit.

If `CLAUDE_SESSION_ID` is unavailable in the env, fall back to `nosession`.

## Question 3 — Helper interface

**Options considered**:

- **A. Single `append` subcommand** — Codex parity. Helper must auto-create
  run dir on first append. State is implicit in the JSON line itself.
- **B. Three subcommands `init-run` / `append` / `close-run`** — explicit
  lifecycle. `init-run` returns the run_id and creates `meta.json`. Orchestrator
  exports `MAE_LEARNING_RUN_ID` env var → sub-agents inherit it. `close-run`
  updates `meta.json` with `ended_at`, `outcome`, `event_count`.

**Decision**: **B (three subcommands)** with **idempotent fallback** (append
creates run dir if missing, close-run creates meta if missing).

Rationale:
- Explicit lifecycle gives us run-level metadata that survives even when zero
  events are emitted — important for measuring run success rate over time.
- Sub-agents inheriting `MAE_LEARNING_RUN_ID` via env is clean and survives
  `claude -p` subprocess boundary.
- Idempotency makes failure recovery trivial: if `init-run` was skipped, first
  `append` self-heals; if `close-run` was missed, the `meta.json` is incomplete
  but still readable.

## Out-of-scope decisions (recorded but deferred)

### Headless `--model` flag (v2.8.x mini-PR, not this experiment)

Audit revealed SKILL.md documents "Orchestrator=Opus, Sub-agents=Sonnet" but
none of the 6 `claude -p` dispatch sites pass `--model`. Actual model is
inherited from the user's Claude Code CLI default. Fix is ~6 one-line changes
but is a *behavior* change, not an *observability* change. Bundling it with
learning log would mix change responsibility.

**Decision**: separate v2.8.x mini-PR after v2.8 lands.

### Skill-invocation asymmetry (INCLUDED in v2.8)

Audit revealed only Orchestrator (2 sites) and Implementer (4 sites) invoke
superpowers. Plan Reviewer / Reviewer / Verifier prompts have zero
`Skill("superpowers:...")` calls — the review side is empty.

**Decision**: include in v2.8 scope. Three single-line additions to prompts:

- `references/plan-reviewer-prompt.md` → `Skill("superpowers:writing-plans")`
- `references/reviewer-prompt.md` → `Skill("superpowers:requesting-code-review")`
- `references/verifier-prompt.md` → `Skill("superpowers:verification-before-completion")`

Cheap, high-leverage, and the learning log will tell us whether the additions
actually fire by capturing reviewer-fail / verifier-fail event quality over time.

### Learning-log → experiment auto-trigger (v2.9+, not this experiment)

Aggregator that consumes recent events to surface candidate experiments is a
natural follow-on but requires real event corpus first. Defer.

## Consequences

- Helper has 3 subcommands instead of 1 → ~30 extra lines vs Codex helper.
- `meta.json` schema is a new artifact (not in Codex side).
- Events emitted before `init-run` ran will self-heal but lose run metadata
  until `init-run` is called.
- No `flock`/size cap means a single oversized event line (> 4KB) might still
  cause partial write under exotic FS, but per-run isolation contains the
  damage to a single run's events file.

## Post-advisor corrections (Round 1)

After the design draft + advisor review on 2026-05-13, four gaps were patched.

### Q4 — Sub-agent invocation contract (BLOCKING gap)

Original draft said "Both Agent-tool sub-agents (Implementer/Reviewer) and
`claude -p` sub-agents read `MAE_LEARNING_RUN_ID` env var and call the helper
themselves." This conflated two dispatch paths with different env semantics:

- `claude -p` subprocess: POSIX env inheritance ✓
- Agent tool dispatch: subagent runs in same Claude Code session; no
  guaranteed env propagation to its `Bash` tool calls

**Decision**: sub-agents **never invoke the helper directly**. They write event
candidate JSON files under `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`.
The orchestrator (which owns `MAE_LEARNING_RUN_ID`) reads candidates and calls
`append`. `MAE_LEARNING_RUN_ID` env inheritance is relevant only for `claude -p`
dispatch paths that the orchestrator runs **itself** — and even there, the
orchestrator can pass it explicitly via `env MAE_LEARNING_RUN_ID=... nohup ...`.

This removes the entire "sub-agent env propagation" ambiguity. One contract,
one writer (the orchestrator), no concurrent helper invocations within a run.

### Q5 — close-run in error paths (BLOCKING gap)

Original draft only mentioned `close-run` at Phase 2 final. But Phase 1
escalation halt, HEADLESS_HALTED, hook denial, or hard crash all skip Phase 2,
leaving `meta.json` with `outcome=unknown` forever.

**Decision**: `close-run` must be invoked from **every orchestrator exit path**:

- Phase 2 success → `outcome=success`
- ESCALATE that halts → `outcome=blocked`
- User abort / hook denial → `outcome=aborted`
- Hard crash / unhandled exception → unreachable (acceptable: `outcome=unknown`
  is honest because nothing ran the cleanup)

Implementation: orchestrator wraps the whole flow with a structured exit —
either by trapping in shell or by always going through a single "exit point"
helper section in SKILL.md that calls `close-run` before any halt.

### Q6 — Resume Chain × run_id (gap)

SKILL.md's Resume Chain spawns a new `claude -p` subprocess when
`compaction_points ≥ 2 AND complete ≥ 8`. Original draft didn't specify
whether the chained subprocess inherits the run.

**Decision**: **Resume Chain preserves `MAE_LEARNING_RUN_ID`**. The chained
orchestrator does NOT call `init-run`. One plan execution = one run record,
even across multiple Claude sessions.

Implementation: Resume Chain's `nohup claude -p --session-id ...` command
prepends `env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID"` so the new
subprocess sees it.

**Schema addition**: `meta.json` gains `session_ids: ["<uuid1>", "<uuid2>"]` —
an array that lets future analysis follow chain handoffs back to multiple
transcripts.

### Q7 — F001 smoke needs a fixture that actually triggers events

Original Task 7 used `evals/fixtures/01-trivial-typo.yaml` (LOW, single file).
That smoke only validates `init-run` + `close-run`. The `append` path stays
untested.

**Decision**: F001 runs **two smokes**:

- Smoke A: `01-trivial-typo.yaml` — happy-path; expected events = 0;
  `meta.outcome=success`, `meta.event_count=0`.
- Smoke B: `08-subtle-input-validation.yaml` (from v2.7) — designed-to-WARN;
  expected events ≥ 1 with at least one `reviewer_warn_or_fail`.

F001 is PASS iff both succeed and event_count matches expectation in each.

### Q8 — Non-blocking touchups

- `CLAUDE_SESSION_ID` env var existence is unverified — check once before
  T2 lands; if absent, `session_short` legitimately falls back to `nosession`.
- SKILL.md step numbers will drift — describe edit locations narratively
  ("after worktree setup", "after state.json initial write") rather than
  numerically in the plan.
- Branch hygiene — current branch `codex/executor-learning-log` is shared
  with the Codex sibling work. Acceptable because file paths don't overlap,
  but commits MUST stage only Claude executor files per commit.

## Links

- Sibling design: `docs/superpowers/specs/2026-05-13-kws-codex-plan-executor-learning-log-design.md`
- Sibling plan: `docs/superpowers/plans/2026-05-13-kws-codex-plan-executor-learning-log.md`
- Experiment scaffolding pattern: D005 in `../v2.7-quality-mode/decisions/`
- AGENTS.md protocol for experiment record-keeping
