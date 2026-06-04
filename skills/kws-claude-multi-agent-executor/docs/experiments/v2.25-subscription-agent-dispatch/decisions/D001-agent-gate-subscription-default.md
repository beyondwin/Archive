# D001 — Agent gate value + subscription-by-default

**Date**: 2026-06-04
**Status**: Decided

## Context

The headless roles (Plan Reviewer, Verifier, Docs Updater) dispatch via `claude
-p` or the Messages API. Both are metered (off-subscription). `claude -p`
billing is changing, prompting the user to want these roles on the subscription
pool. Only the in-session Agent tool reaches the subscription, and only the
Implementer/Reviewer currently use it.

## Options considered

- **A**: Add `"agent"` as a third gate value, keep default `"api"` (opt-in).
- **B**: Add `"agent"` and flip the default `"api"` → `"agent"` (subscription by
  default).
- **C**: Replace the `-p`/api transports entirely with agent dispatch (no choice).

## Analysis

The whole motivation is to avoid metered billing on the default path. Opt-in (A)
means a user who does nothing keeps paying metered — it does not solve the stated
problem for the common case. Removing the metered transports (C) loses the
ability to run roles off the subscription when the user explicitly wants the
isolation/parallelism of `-p`/api (e.g. detached runs). B keeps both: the
default is free (subscription), and metered transports remain reachable by
explicitly setting a gate to `"api"`/`"p"`.

## Decision

Option **B**. Each role gate becomes `"p" | "api" | "agent"` (and `final_sweep`
gains `"agent"`); all seven defaults flip to `"agent"`. Explicit `"api"`/`"p"`
still selects a metered transport per gate.

## Consequences

- A bare invocation runs every role on the subscription pool, `$0` metered.
- The metered transports are preserved as explicit opt-outs.
- The `"agent"` path is a prose dispatch pattern (Agent-tool call), not a helper
  script — a script cannot invoke the Agent tool.
- Interacts with detach (a detached orchestrator re-meters its Agent
  sub-agents) — handled in D002.

## Open questions

None.
