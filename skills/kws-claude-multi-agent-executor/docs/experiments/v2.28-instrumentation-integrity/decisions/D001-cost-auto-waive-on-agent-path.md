# D001 — Honest auto-waive for cost on the agent-dispatch path

**Date**: 2026-06-07
**Status**: Decided

## Context

v2.27 D002 elevated `cost_ledger.totals.dispatches == 0` from WARN to a blocking
finalize FAIL, suppressible only by a *manual* `cost_tracking_waived` flag. The
three post-v2.27 runs (2026-06-06) show what that produced in practice:

| Run | dispatch_config | cost_tracking_waived | finalize today |
|-----|-----------------|----------------------|----------------|
| `session-package-…-205440` (run 3) | all `agent` | **false** | `passed:false` — `cost_dispatches_zero` |
| `readmates-…-214931` (run 2) | all `agent` | **true** (reflexive) | passes the cost gate |
| `target-type-…-235331` (run 1) | all `agent` | **true** (reflexive) | passes the cost gate |

The block worked exactly as designed — and that is the problem. On the default
`agent` dispatch path, cost is **structurally unobtainable**, not merely skipped:

- The v2.25 default sets every role gate in `dispatch_config` to `"agent"` (the
  in-session Agent tool / subscription pool).
- The Agent tool returns only the sub-agent's final text. It exposes **no
  `usage` object** to the orchestrator. `accumulate_cost.py` requires
  `--usage-json` / `--usage-file`; there is nothing to feed it.
- `references/cross-cutting/agent-dispatch.md:38-42` and
  `phase-1-task-cycle.md:347-369` **falsely** claim "Subscription dispatches
  still report usage, so the ledger stays populated." They do not. This prose is
  the source of the orchestrator's confusion.

So a `dispatches==0` FAIL on an all-`agent` run is not evidence of drift — it is
the *only possible outcome*. v2.27 turned a structural impossibility into a
blocking gate, and the field response was the predictable one: operators either
reflexively set `cost_tracking_waived` (runs 1, 2 — the flag becomes noise,
defeating the gate everywhere) or the run wedges unfinalized (run 3). A gate that
fires on every default-config run trains operators to waive it blindly, which
also silences it on the `api`/`p` runs where `dispatches==0` *would* be real
drift.

## Options considered

- **A — Mandate cost capture on the agent path.** Reject. There is no usage to
  capture; the Agent tool does not surface it. This would mandate the impossible.
- **B — Reconstruct cost out-of-band** (parse the host session's own cost
  telemetry / ccusage-style logs and back-fill the ledger). Reject for v2.28.
  It couples the skill to host-session log formats that are outside the run's
  state, is brittle across CC versions, and attributes whole-session cost to a
  single run that may share the session. Explicitly **deferred**, not refused
  forever — recorded here as the rejected alternative so a future experiment can
  revisit it deliberately.
- **C — Honest, deterministic auto-waive.** When the effective dispatch
  configuration *cannot* yield usage, set `cost_tracking_waived = true`
  automatically with a recorded reason, as a single deterministic state write at
  Phase 0 (and on resume). A run with any `api`/`p` gate is left un-waived so it
  must accumulate real cost.

## Decision

**C**, paired with fixing the false prose. Specifically:

- **Phase 0 (`phase-0-setup.md` Step 7) + the resume path**: if the run is
  attached **and** no role gate is `api`/`p` (Implementer/Reviewer are always
  `agent`), write `cost_tracking_waived = true` and a new run-level
  `cost_tracking_waive_reason = "agent-dispatch-no-usage"` via `state_set.py`.
  Deterministic — derived from `dispatch_config`, not a prose judgement call.
- **`finalize_run.py`**: the `cost_dispatches_zero` FAIL logic is **unchanged**
  from v2.27 (still suppressed by `cost_tracking_waived`). The fix is upstream —
  the waive is now set honestly and automatically, so the gate only fires when a
  *metered* gate (`api`/`p`) genuinely produced no dispatches.
- **Doc corrections**: rewrite `agent-dispatch.md:38-42` and
  `phase-1-task-cycle.md:347-369` to state the truth — the Agent tool result does
  not expose `usage`; per-dispatch cost is unavailable on the agent path; that is
  *why* agent-default runs auto-waive; to get cost/budget enforcement, opt a gate
  into `api`/`p`.
- **Final Summary**: render `Cost tracking: WAIVED (agent dispatch — usage not
  observable)` when the reason is set, instead of an unexplained `$0.00`.

The distinction from v2.27 D002: D002 was right that a *metered* run finishing
with an empty ledger is drift worth blocking. D001 narrows that gate to the runs
where it is actually meaningful, and stops it from firing on the default config
where the empty ledger is a law of physics, not a mistake.

## Honest limitation

Auto-waiving cost also disables `budget_cap_usd` enforcement and the token-based
chain-resume trigger **on the default path**, because both read the (now-empty)
ledger. This is the accepted cost of the agent-pool default. Users who need
budget enforcement opt a role gate into `api`/`p`, which both produces real usage
and leaves the run un-waived. v2.28 does **not** reconstruct cost out-of-band
(option B, deferred). The value delivered is honesty: the run state and the
summary now *say* "cost not tracked because the transport can't observe it,"
instead of silently reporting `$0.00` or wedging on an unwinnable gate.

## Consequences

- All-`agent` runs (the default, all three observed runs) auto-waive → the cost
  gate no longer fires on them, and `cost_tracking_waived` stops being reflexive
  operator noise.
- `api`/`p` runs are left un-waived → a real empty ledger there still FAILs (the
  D002 protection is preserved exactly where it is meaningful).
- The false "usage stays populated" claim is removed from two reference files,
  closing the prose that misled the orchestrator in the first place.
- Regression replay: run 3 stops failing for `cost_dispatches_zero` (cost
  auto-waived) and instead fails for the *honest* reason — inverted timing (see
  [D003](./D003-timing-sanity-coverage-keys.md)). That hand-off is the point:
  cost stops masking the real defect.
