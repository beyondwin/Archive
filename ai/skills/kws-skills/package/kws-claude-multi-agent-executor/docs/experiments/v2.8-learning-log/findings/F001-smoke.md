# F001 — Shell-level integration smoke

**Date**: 2026-05-13
**Status**: PASS (shell-level); full-fixture smoke DEFERRED

## What was tested

A shell script simulated the full orchestrator learning-log lifecycle end-to-end
without invoking `claude -p`:

1. `init-run` with realistic args → directory created at
   `<log_root>/runs/<YYYY-MM-DD>/<run_id>/meta.json` with `outcome=unknown`,
   `event_count=0`, `session_ids=[<initial_uuid>]`.
2. Sub-agent (Reviewer) writes a `reviewer_warn_or_fail` event candidate to
   `<worktree>/.orchestrator/learning_events/task_3-reviewer.json` with an
   absolute path in `context.evidence[0].value`.
3. Orchestrator calls `append --repo-root <worktree>`. Helper validates,
   relativizes the absolute path to `src/config.py`, computes `event_id`,
   writes one compact JSON line to `events.jsonl`.
4. Simulated Resume Chain handoff: `append-session-id` adds a second session
   UUID to `meta.session_ids[]`.
5. `close-run --outcome success` finalizes `meta.json` with `ended_at`,
   `outcome=success`, `event_count=1`.

All five steps succeeded. All seven assertions passed (run dir created, meta
created, events.jsonl created, exactly 1 event line, path relativized to
`src/config.py`, session_ids has 2 entries, close-run records outcome+count).

## Concrete output (one run)

```
RUN_ID=20260513T130523Z-188042f4-29587
event_id eb3d8f65eb6ad2ef
Relativized path: src/config.py
session_ids[]=['188042f4-d69e-45d2-91ad-91ad91ad91ad', '7d13e7b9-d69e-45d2-91ad-91ad91ad91ad']
close-run result: success 1 2026-05-13
```

The relativization (`<TMP>/worktree/src/config.py` → `src/config.py`) confirms
the worktree-path redaction rule from `references/learning-log.md` operates
correctly in real filesystem conditions.

## What this validates

- Helper subcommand integration (4 subcommands chain cleanly).
- Per-run sharded directory layout.
- meta.json schema (matches `references/learning-log.md`).
- events.jsonl line schema (with `event_id` injection).
- Privacy guard: absolute worktree path → relative path.
- Resume Chain handoff (append-session-id without re-init).
- Close-run finalization on success.

## What this does NOT validate (DEFERRED to full-fixture smoke)

- **Smoke A** (`evals/fixtures/01-trivial-typo.yaml`): Does the orchestrator
  actually call `init-run`, scan `.orchestrator/learning_events/`, and call
  `close-run` when running under `claude -p --dangerously-skip-permissions`?
  Or does it skip the helper calls entirely under real conditions? This needs
  a real run.
- **Smoke B** (`evals/fixtures/08-subtle-input-validation.yaml`): Does the
  Reviewer sub-agent actually write a candidate file when it returns WARN?
  Even though the prompt instructs it to, real Sonnet behavior may differ.

## Why the full-fixture smoke is deferred

Each `evals/run.sh` invocation:
- Spawns `claude -p` for orchestrator + Plan Reviewer + Verifier + Docs
  Updater + judge — ~5-7 separate `claude -p` calls in one fixture.
- Estimated cost: $5-15 per fixture, $10-30 for both fixtures together.
- Estimated wall time: 15-30 minutes per fixture.

These are real production-cost API calls. The user controls the budget. The
shell-level smoke above validates the static integration (file paths, helper
correctness, schema, privacy guard). The full-fixture smoke validates the
behavioral integration (orchestrator + sub-agent actually invoke the new code
paths under real LLM behavior).

The deterministic preflight (`evals/check_learning_log.py` 16 checks +
`evals/check_skill_contract.py` 17 checks) already gates the contract. The
full-fixture smoke is a stronger validation but not a release blocker — the
preflight + shell smoke + advisor review collectively de-risk the change
enough to ship.

## Recommendation

**Ship v2.8.0 as draft on branch.** Run the full-fixture smoke when budget
allows. If Smoke A succeeds (meta.json + outcome=success + event_count=0)
and Smoke B produces at least one `reviewer_warn_or_fail` event, mark this
finding as full PASS and merge.

If full-fixture smoke fails, the most likely failure mode is the orchestrator
not actually executing the new helper-invocation snippets in SKILL.md. Fixes
would land as follow-up commits, not a v2.8.1 — the contract is correct;
only the runtime adherence needs verification.

## Residual risks (carried forward)

1. **Real claude orchestrator behavior** — instruction adherence under
   `--dangerously-skip-permissions` headless mode is not guaranteed by static
   contract.
2. **Resume Chain not exercised by shell smoke** — only `append-session-id`
   was exercised; the actual `env MAE_LEARNING_RUN_ID="$..." nohup claude -p`
   handoff is not validated.
3. **ESCALATE path not exercised by either smoke** — would need a fixture
   designed to fail in a way Implementer can detect (e.g., spec contradiction).
4. **CLAUDE_SESSION_ID env propagation** — currently the helper falls back to
   `nosession` if unset. The actual env var availability under various
   invocation modes (interactive / headless / Agent-tool) has not been
   measured. Worst case: `session_short=nosession` makes run_ids less unique
   when multiple runs start in the same second (mitigated by pid in run_id).

These are all acceptable residual risks for a v2.8.0 ship — they affect
observability quality, not skill correctness.
