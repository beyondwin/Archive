# D002 — detach conflict handling

**Date**: 2026-06-04
**Status**: Decided

## Context

`"agent"` gates only reach the subscription pool when the orchestrator runs
**attached** (in the user's session). Under `detach=true` the orchestrator is
itself a `claude -p` process; Agent sub-agents it spawns bill against that
metered parent. So `detach=true` + `agent` gate silently defeats the billing
goal. Since v2.22.0, attached is the default and `detach=true` is an explicit
opt-in, so the conflict only arises when the user explicitly asks for detach.

## Options considered

- **A**: Warn + proceed (run metered under detach).
- **B**: Hard halt — the combination is contradictory; force the user to choose.
- **C**: Auto-prefer attached whenever any gate is `"agent"`.

## Analysis

In the only case that actually occurs — an *explicit* `detach=true` — options A
and C converge (C's "prefer attached" only matters when detach is not explicit,
but bare invocations are already attached, so no conflict exists there). B halts
on a deliberate, explicit user choice, which is paternalistic friction. The
distinction that matters is whether the `"agent"` value was a *deliberate choice*
or merely the *new default*: combining explicit detach with a defaulted agent is
likely an accident; combining it with an explicitly-set agent is the user's
contradiction to own.

## Decision

Refined Option A, splitting on default vs explicit (evaluated in Phase -1 args
parsing, after mode determination; result written to `state.dispatch_config`):

| Situation | Action |
|-----------|--------|
| `detach=true` + gate at **agent default** | Fall those gates back to `"api"` + one-line warning. Pre-feature behavior; the default never causes surprise metering. |
| `detach=true` + gate **explicitly** `"agent"` | Warn + proceed (respect explicit intent, no halt). |

## Consequences

- No hard halt for this conflict — detached runs always proceed.
- The agent default is context-adaptive ("explicit wins, defaults adapt").
- Requires Phase -1 to distinguish defaulted from explicitly-set gate values
  (track provenance during arg parsing).

## Open questions

None.
