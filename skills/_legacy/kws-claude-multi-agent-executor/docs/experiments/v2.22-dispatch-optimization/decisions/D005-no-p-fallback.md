# D005 — API errors do NOT fall back to `claude -p`

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase B6)

## Context

Phase B routes the mechanical roles through the Anthropic Messages API
(`dispatch_via_api.py`, D003) instead of headless `claude -p`. The obvious
"robustness" instinct on an API error (rate limit, 5xx, parse failure) is to
retry the same dispatch via the old `claude -p` path. That instinct is a trap.

## Options considered

- **A**: On API error, fall back and retry the dispatch via `claude -p`
  (mixed-path retry).
- **B**: On API error, surface the error; never fall back to `claude -p`.

## Analysis

A mixed-path retry is harmful on three axes:
1. **Caching** — the `-p` path does not share the scaffold prompt cache, so the
   fallback pays full input cost and corrupts the cache-hit-ratio signal.
2. **Cost accounting** — the `-p` dispatch accounts differently, so the ledger
   no longer reflects a clean API-direct run.
3. **Surface area** — `-p --dangerously-skip-permissions` re-introduces exactly
   the headless permission surface Phase B is removing.

A clean API failure that surfaces is more debuggable than a silent fallback that
masks a misconfigured key or a transient outage as "it worked, just slower."

## Decision

API errors do **not** fall back to `claude -p`. The forbidden mixed-path retry
is prohibited; `dispatch_via_api.py` surfaces the error to the orchestrator
instead, which handles it through the existing escalation/halt guardrails.

## Consequences

- Caching and cost accounting stay clean — an API-direct run is uniformly
  API-direct.
- No silent reintroduction of the headless permission surface.
- API outages become visible failures, not degraded-but-hidden runs.
- In-role retries (within the API path) remain allowed; only the cross-path
  fallback is forbidden.
