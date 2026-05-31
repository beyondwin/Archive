# D003 — `dispatch_via_api.py` is the single helper for all API-direct roles

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase B1)

## Context

Phase B replaces `claude -p --dangerously-skip-permissions` headless dispatches
for the mechanical roles with direct Anthropic Messages API calls. The roles
that go API-direct are `plan_reviewer`, `verifier`, `docs_updater`, and the
merged `transition_combined`. Each needs prompt construction, the API call,
`tool_choice` enforcement so the result is a structured tool call rather than
free text, response parsing, and cost-ledger accounting.

## Options considered

- **A**: One helper per role (`dispatch_verifier.py`, `dispatch_docs.py`, ...).
- **B**: A single shared helper `scripts/dispatch_via_api.py` that takes a role
  and its scaffold/payload and runs the same call/parse/account path.

## Analysis

Per-role helpers duplicate the API call, the `tool_choice` forcing, the
prompt-cache wiring, and the cost accounting four times — four places to drift
and four places to fix a caching or pricing bug. A single helper makes the
caching contract (D004) and the no-fallback contract (D005) enforceable in one
place. The roles differ only in their tool schema and payload, which are
parameters, not separate code paths.

## Decision

`scripts/dispatch_via_api.py` is the **single** Anthropic Messages API helper
for every API-direct role. It forces `tool_choice` so every role returns a
structured result, and it owns the scaffold/payload caching split and the
cost-ledger write for those dispatches.

## Consequences

- One place to enforce caching (D004), no-`-p`-fallback (D005), and cache-token
  cost accounting.
- New API-direct roles plug in by supplying a tool schema + payload, not new
  dispatch code.
- Concentrates the API surface, so an API-key or model-id change is one edit.
