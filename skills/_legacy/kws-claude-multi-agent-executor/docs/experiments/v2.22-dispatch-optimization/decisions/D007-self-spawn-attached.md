# D007 — Self-Spawn default flips to attached, with a deprecation warning

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase C2)

## Context

Historically a bare invocation self-spawned a **detached headless** `claude -p`
instance (`mode=headless_*`). That default optimized for fire-and-forget
autonomy, but it detaches before the user sees the parsed-args echo, runs with
`--dangerously-skip-permissions`, and (per user feedback) loses the prompt-cache
warmth that an attached in-session run keeps alive. Once Phase B moved the
mechanical roles onto the API, the headless wrapper is no longer carrying its
original weight for most runs.

## Options considered

- **A**: Keep detached-headless as the default.
- **B**: Flip the default to **attached in-session**; make headless self-spawn
  opt-in.
- **C**: Remove headless self-spawn entirely.

## Analysis

Option C is too abrupt — some users genuinely want detached headless runs.
Option B preserves that path behind an explicit opt-in while making the safer,
cache-warm, permission-visible attached mode the default. A hard default flip
can surprise users with muscle memory, so it ships with a time-boxed
deprecation warning rather than silently.

## Decision

The Self-Spawn default flips to **attached** (`mode=interactive_attached`). A
bare invocation now runs in-session; detached headless self-spawn is opt-in via
`detach=true` (explicit or NL). `mode=interactive` still forces legacy
single-session. A **2-week deprecation warning** (gated by
`state.deprecation_warnings.attach_default`) fires on bare invocations so users
notice the changed default. Opt-in self-spawn stays gated by Phase 0 Steps 1, 2,
2.5.

## Consequences

- Default runs are cache-warm, permission-visible, and show the args echo before
  doing work.
- `interactive_attached` joins the `mode` enum (SKILL.md Guardrails).
- Headless autonomy is preserved behind `detach=true`.
- The deprecation warning is time-boxed; remove it after the 2-week window.
