# D001 — MAST coverage matrix as the authoritative eval-coverage doc (J1)

**Date**: 2026-06-08
**Status**: Decided (implemented)

## Context

The fixture suite (01–08) had no explicit map of *which* multi-agent failure modes
each fixture exercises. New fixtures were added by intuition, risking duplication or
leaving high-frequency failure classes uncovered. MAST (Cemri et al. 2025) gives a
14-mode / 3-category taxonomy with frequency data (~42% spec/design, ~37%
coordination, ~21% verification), which is a principled lens for "what do we NOT
measure".

## Options considered

- **A — Keep coverage implicit.** Map fixtures to failure modes ad hoc in PR
  discussion. Cheap, but the gap analysis is never authoritative and rots.
- **B — Encode coverage in fixture YAML only.** A `mast_coverage:` key per fixture,
  no central doc. Machine-readable but no single place to see the gap list.
- **C — Authoritative doc + per-fixture annotation.** `docs/eval-coverage-mast.md`
  holds the 14-mode table, the fixture↔FM matrix, the gap list with revisit
  triggers, and an update protocol; each fixture carries a `mast_coverage:` comment
  that the matrix mirrors 1:1.

## Analysis

The annotation alone (B) is not discoverable for the cross-cutting question "which
modes are uncovered and why". The doc alone risks drifting from the fixtures. C
binds them: the doc is the authority, the annotation is the local pointer, and the
update protocol (§4) makes the writer keep them in sync. Critically, the annotation
must be **runtime-inert**: `run.sh` whitelists `_meta.json` keys
(`name/description/bootstrap/invocation/expected/cost_budget`) so `mast_coverage`
is dropped, and `rubric.py` reads only `expected.rubric` — so the annotation cannot
change any scoring.

## Decision

**Option C.** Ship `docs/eval-coverage-mast.md` as authoritative; annotate fixtures
01–08 (09/10 native); the matrix maps all 10. The doc names the two gaps closed
this round (FM-3.3 rubber-stamp → fixture 09; error-propagation → fixture 10) and
the two left open with concrete triggers (FM-1.3 step-repetition, FM-1.5
termination-unawareness — revisit only when a real incident surfaces in the
`events.jsonl`/`run_report.json` corpus).

## Consequences

- Eval coverage is now auditable; new fixtures must update the matrix (§4 protocol).
- Zero runtime change (annotation inert) — verified against the harness whitelist.
- ARCHITECTURE.md untouched: per AGENTS.md §0.2 a new fixture inside an existing
  measurement layer is not an ARCHITECTURE trigger; the matrix doc is not a new layer.

## Open questions

- Whether to enforce annotation↔matrix consistency with a deterministic check in
  `check_doc_freshness.py`. Deferred — the §4 protocol + review is sufficient until
  a drift incident shows otherwise (avoid speculative tooling).
