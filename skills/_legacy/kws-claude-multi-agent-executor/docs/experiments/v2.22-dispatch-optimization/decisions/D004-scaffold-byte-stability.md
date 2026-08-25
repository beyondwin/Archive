# D004 — Scaffold/payload split is byte-stability-linted at Phase 0 Step 6.7

**Date**: 2026-05-31
**Status**: Decided (shipped, Phase B3)

## Context

Prompt caching only pays off when the cached prefix is byte-identical across
calls. Each API-direct prompt (D003) is therefore split into a **scaffold**
(the stable, cacheable prefix: role instructions, rubric, schema) and a
**payload** (the per-call variable part: this task's files, diff, state slice),
delimited by four markers: `SCAFFOLD_BEGIN` / `SCAFFOLD_END` and
`PAYLOAD_BEGIN` / `PAYLOAD_END`. If a stray timestamp, run id, or reordered
field leaks into the scaffold, the cache key changes every call and the cache
benefit silently evaporates — with no error, just a low cache-hit ratio.

## Options considered

- **A**: Trust authors to keep the scaffold stable; catch drift later via the
  cache-hit-ratio metric.
- **B**: Lint the scaffold for byte stability at boot so drift fails loudly
  before any dispatch runs.

## Analysis

Option A makes a caching regression a *forensics* finding weeks later, after the
cost has already been paid. A boot-time lint turns it into a fast, deterministic
failure. The check belongs on the boot path, before the first API-direct
dispatch.

## Decision

`scripts/validate_scaffold_split.py` byte-stability-lints every scaffold/payload
split at **Phase 0 Step 6.7**. Step 6.7 is used (not 7.5) because the as-shipped
Task 5 deviation found Step 7.5 already taken by the v2.17 boundary-emit; 6.7 is
the free slot before dispatch.

## Consequences

- Scaffold drift fails loudly at boot, not silently as a degraded cache-hit
  ratio in post-run forensics.
- The four-marker contract is mechanical and eval-checkable.
- New API-direct prompts must conform to the marker split or fail the lint.
