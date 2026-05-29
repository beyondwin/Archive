# D003 — headless self-spawn default vs cache-warmth preference

**Date**: 2026-05-29
**Status**: Decided (keep headless default; correct the cache analysis; document)

## Context

User memory (`feedback_agent_invocation_style`): the user runs role agents
manually one-per-terminal and avoids auto-fan-out. The stated *why* is specific
and technical, and it is sharper than an earlier draft of this ADR assumed:

> Anthropic prompt cache is keyed on `(API key, model, exact prefix tokens +
> cache_control breakpoint)` — `session_id` is NOT part of the server key.
> `claude -p` headless drifts because **(a)** SessionStart hooks inject dynamic
> context (timestamps, git status, system-reminders) that shift prefix tokens
> turn-to-turn, and **(b)** wall-clock gaps between invocations often exceed the
> 5-min TTL.

This skill defaults to **headless self-spawn** (Phase -1): the orchestrator
detaches as a `claude -p --dangerously-skip-permissions` subprocess, and runs
Verifier / Plan Reviewer / Docs Updater via one-shot `claude -p` each.

## Options considered

- **A — keep headless default**; keep `claude -p` for Verifier/Docs. Status quo.
- **B — make `mode=interactive` the default** for this user (single-session,
  subscription pool), reserving headless for explicit `mode=headless`.
- **C — keep headless default but convert Verifier/Docs to Agent-tool dispatch**
  so they share the warm orchestrator session.

## Analysis (corrected)

An earlier draft argued "the headless orchestrator is a long-lived multi-turn
session, so its cache stays warm." That was too rosy. The user's point **(a)** is
correct and applies *to this skill*: the headless orchestrator is itself a
`claude -p` process that **does** receive SessionStart hooks (this session shows
a `SessionStart:compact` hook firing). Each such injection shifts the prefix, so
cache hits degrade even within one long-lived session — not only across one-shot
`-p` calls. So headless is genuinely worse for cache than an interactive terminal.

What still argues against a blind default-flip:

- **Autonomy is the skill's purpose.** Headless self-spawn is what lets the run
  proceed start-to-finish without occupying the user's interactive session. That
  is a real capability, not just a cache choice; flipping the default trades it
  away for everyone, not only for cache-sensitive runs.
- **v2.21 slimming directly mitigates (a).** After the SKILL.md split (item 1)
  the orchestrator prefix shrinks ~70%. A cache miss on a small prefix is cheap,
  so the *cost* of the prefix-drift the user describes drops sharply regardless
  of mode. The slim attacks the root magnitude of the problem.
- **Verifier/Docs `claude -p` calls are cold either way** (each has a different
  per-task/per-phase prompt → ~zero cross-dispatch reuse even if warm), so
  option C trades cold-process startup for added orchestrator-context turns with
  no clear cache win and more result-file plumbing. Reject C.
- **The escape hatch already exists.** `mode=interactive` is a first-class arg.
  The user's documented workflow (manual, per-terminal) maps onto it directly.

## Decision

**Keep A as the shipped default, with two concrete actions:**

1. **Correct and document the reasoning in the skill** so it is not
   re-litigated: headless self-spawn favors *autonomy*; it is *not* cache-optimal
   because SessionStart injection drifts the prefix (user's point (a)). The
   v2.21 slim makes the resulting miss cheap. Cache-sensitive or attended runs
   should pass `mode=interactive`.
2. **Honor the user preference:** add **no** new auto-fan-out anywhere in v2.21.
   Sub-agent dispatch stays demand-driven (one per task/role), and the parallel
   sub-flow remains opt-out via `parallel=off`. For *this* user, `mode=interactive`
   is the recommended invocation.

Reject B (default-flip) and C (Agent-tool Verifier/Docs) for now. B is a
behavioral change with an autonomy cost that deserves explicit user sign-off
before flipping; it is offered to the user as a follow-up, not made silently.
This ADR does not block the other five items.

## Follow-up offered to the user (non-blocking)

If the user's lived experience is that attended runs feel cold, flip the default
to `mode=interactive` (option B) — a small Phase -1.1 change (default mode when
neither `mode=` nor the headless sentinel is present). Left as the user's call.

## Open questions

- Empirical: measure headless orchestrator cache_read ratio before vs after the
  v2.21 slim on one fixture, to quantify how much (a) actually costs post-slim.
