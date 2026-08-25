# D005 — SKILL.md split boundary (reaffirm + extend v2.19 D001)

**Date**: 2026-05-29
**Status**: Decided (supersedes the "pending user review" status of v2.19 D001)

## Context

v2.19 D001 already designed the split (Phase axis + cross-cutting axis, Option C
hybrid) and extracted Phase -1 as the PoC. The remaining extraction stalled in
"사용자 검토 대기" (awaiting user review). The user has now approved the full
undertaking (2026-05-29), so this ADR confirms the v2.19 boundary and notes the
deltas v2.21 adds.

## Decision

Adopt the v2.19 D001 hybrid layout verbatim:

```
references/
├── phases/
│   ├── phase-minus-1-args-and-spawn.md   # DONE (v2.19 T1.1)
│   ├── phase-0-setup.md
│   ├── phase-1-task-cycle.md             # normal path
│   ├── phase-1-parallel-subflow.md       # P2
│   ├── phase-1-spec-edit-branch.md       # P15
│   ├── phase-transition.md               # T1–T3 + Resume Chain
│   └── phase-2-finalization.md
└── cross-cutting/
    ├── state-schema.md                   # full JSON schema (single + plan_chain)
    ├── multi-plan-chain.md               # plan_chain + active_plan resolution
    ├── agentlens-emit-sites.md           # emit sites + candidate drain
    ├── safety-hooks.md                   # Pre/Post/SubagentStop hooks
    └── decisions-register.md             # v2.15 C2 mechanism
```

SKILL.md entrypoint keeps (~8–10k tokens): path layout, active-tree resolution,
lifecycle one-pager, phase-entry "Read references/phases/phase-N.md" rules,
cross-cutting reference pointers, output format, safety gates / ESCALATE enum, arg
summary table, and the full Guardrails table (the guardrails are the load-bearing
invariants — keep them in the entrypoint, with detail in references).

Flat vs nested: keep the `phases/` and `cross-cutting/` subdirs (v2.19 D001 open
question). The existing flat `references/*-prompt.md` files stay flat; the new
split content is numerous enough that subdirs aid navigation, and the prefix makes
intent obvious.

## Deltas v2.21 adds on top of v2.19 D001

1. During extraction, **wire the new helpers** (`state_set.py`,
   `phase_boundary.py`) into the phase references — replacing the inline-jq R-M-W
   and the scattered emit/timing/cost prose. The split and the enforcement land in
   the same edit so those regions are touched once.
2. `cross-cutting/multi-plan-chain.md` is written **post-D004** — i.e., it
   describes only the `plan_chain` path; the `plan2_state` legacy branch is gone
   (replaced by the one-paragraph resume-shim note).
3. `cross-cutting/agentlens-emit-sites.md` documents the **health probe** (item 5)
   alongside the emit sites.

## Migration order

Per v2.19 D001, with v2.21 helper-wiring folded in:
1. state_set + phase_boundary helpers exist & tested (v2.21 prerequisite).
2. Phase 0 → phase-0-setup.md (wire helpers).
3. Phase 1 normal → phase-1-task-cycle.md (wire helpers; this is where D003's T1.2
   subagent-state-read change also lives — already partly done in v2.19).
4. Phase 1 special (parallel, spec-edit).
5. Phase Transition.
6. Phase 2.
7. Cross-cutting 5 files (multi-plan-chain post-D004).
8. Entrypoint final trim.

Run a free contract check (`check_skill_contract.py`, `check_doc_freshness.py`)
after each extraction; one paid fixture regression at the end (user-approved).

## Consequences

- Single-source principle: cross-cutting content lives in one file, phase files
  link to it. No duplication.
- One extra Read per phase entry; amortized by cache_read within the phase.
- Risk: behavioral drift during extraction. Mitigation: extract verbatim first
  (no rewrites), wire helpers as a separate reviewable step, eval at the end.
