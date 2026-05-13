# F001 — Shell-level integration smoke

**Date**: 2026-05-13 (initial), 2026-05-13 evening (full-fixture run)
**Status**: PARTIAL PASS — Smoke A clean; Smoke B workflow OK but learning-log adherence FAIL

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

## Full-fixture smoke (2026-05-13 evening) — ACTUAL RESULTS

### Smoke A — fixture 01-trivial-typo (PASS)

Wall: ~6 min (22:40:06 → 22:46:17 UTC compact).
Baseline: judge mean **0.96**, PASSED. Rubric pass_rate: null (no rubric block).

Learning log:
- Run dir created: `~/.claude/learning/kws-claude-multi-agent-executor/runs/2026-05-13/20260513T134006Z-eval-86243/`
- `meta.json` populated: `outcome=success`, `event_count=0`, `session_id="eval"`,
  `started_at=2026-05-13T13:40:06Z`, `ended_at=2026-05-13T13:46:17Z`.
- `events.jsonl`: not created (zero events emitted, as expected for a trivial typo task).
- Helper invocations in run.jsonl: 2 — one `init-run`, one `close-run --outcome success`.

**Verdict**: clean PASS. The full v2.8 contract (init-run → close-run on
success path → meta.json with outcome=success and event_count=0) works
end-to-end under real `claude -p --dangerously-skip-permissions`.

### Smoke B — fixture 08-subtle-input-validation (PARTIAL)

Wall: ~22 min. Baseline: judge mean **1.0**, PASSED. Rubric pass_rate **1.0**
(all 20 checks satisfied, including `parse_duration("30m20m")` → ValueError).

Learning log:
- **No run dir created.** The only run dir in `runs/2026-05-13/` is Smoke A's.
- **No `init-run`, `append`, or `close-run` invocation** in Smoke B's
  47 total Bash tool calls. The orchestrator referenced `MAE_LEARNING_RUN_ID`,
  `init-run`, `append_learning_event`, etc. 19+ times in thinking/text
  content but **never actually executed** the helper script.

**Implementation correctness**: PASS. The orchestrator ran end-to-end —
worktree created, state.json populated, 2 tasks completed (parse_duration
+ tests), Reviewer ran, Verifier ran, commits visible.

**Learning-log adherence**: FAIL. Step 7.5 (init-run) of Phase 0 was not
executed under real `claude -p` for this fixture.

**Verdict**: PARTIAL. The implementation contract works (Smoke A proves it);
the *adherence* contract is unreliable on longer multi-task plans.

### Why Smoke B skipped the helper (hypothesis)

Fixture 01 is single-task LOW-risk: SKILL.md Phase 0 dominates the
orchestrator's first response. Phase 0 Step 7.5 (init-run) is reached and
executed before TDD context loads.

Fixture 08 is two-task MID-risk: Phase 0 → Phase 1 (TDD cycle) → Reviewer
→ Verifier → Phase 2 loops dominate the response. Step 7.5's `RUN_ID=$(... || echo "")`
shell-fallback semantics (designed to fail silently if the helper is
unavailable) appear to also fail silently if the orchestrator simply *skips*
the call. There is no enforcement mechanism — only prose instruction.

This is a real adherence-vs-contract gap. The SKILL.md contract is correct;
the orchestrator's adherence to it under heavy contextual load is unreliable.

### Implications for v2.9 measurement

v2.9 design specifies fallback to rubric-only signal if Smoke B does not
emit `reviewer_warn_or_fail` events. Smoke B's result triggers that
fallback. Two concrete impacts:

1. v2.9 T5 cannot use `events.jsonl` count of `reviewer_warn_or_fail` as
   evidence. Instead, v2.9 T5 inspects raw Reviewer output from the harness's
   `run.jsonl` directly (stream-json format).
2. v2.9 T6 finding doc must record the F001 adherence gap explicitly under
   "residual risks" — `30m20m` rejection rate is the primary metric; raw
   Reviewer `SPEC_COVERAGE_WALK:` output is the secondary inspection target.

### Implications for v2.8.1 (follow-up)

The adherence gap is a separate observation about SKILL.md instruction
strength. Candidate fixes for a future v2.8.1:

- Replace Step 7.5's silent-fallback `|| echo ""` with a louder error +
  retry, so adherence is visible.
- Promote init-run from "Step 7.5 with silent fallback" to a Phase 0
  mandatory checkpoint (similar to git worktree creation).
- Hook-based enforcement (PreToolUse hook that init-runs on first Bash call).

None of these are in v2.9 scope. They are recorded here for the v2.8.1
backlog. v2.9 proceeds with the documented fallback.

## Updated residual risks (post full-fixture run)

5. **Orchestrator adherence to Step 7.5 under heavy contextual load**.
   Confirmed by Smoke B: longer plans skip the init-run call. This is the
   single most important observation from F001's full run — it changes how
   v2.9 and any future learning-log-dependent experiment must measure.
   Mitigations: v2.9 falls back to rubric-only signal; v2.8.1 candidate
   fixes recorded above.

6. **`30m20m` rejection variance is wide**. Single Smoke B rep produced
   `rubric=1.0` (Implementer caught `30m20m`), matching the 1/4 "lucky"
   bucket in F002 baseline. n=1 is insufficient to bound miss rate from
   above. v2.9 T5's n=3-4 should re-confirm the baseline variance before
   attributing any reduction to the prompt change.
