# Cross-cutting: decisions register (v2.15 C2)

Canonical reference for the per-plan `decisions_register` — the append-only log of
key cross-task decisions that keeps sub-agents consistent across a long run, and
its projection to `<orch_dir>/DECISIONS.md`. It is **best-effort enrichment, NOT
load-bearing**: every write failure logs a warning and continues.

See also: `references/phases/phase-1-task-cycle.md` (append + prompt
substitution), `references/phases/phase-transition.md` step 1.5 and
`references/phases/phase-2-finalization.md` (DECISIONS.md projection),
`references/reviewer-prompt.md` (the `decision_conflict` rubric).

## Storage

`decisions_register` lives under `<active>` (per-plan — top-level for single-plan,
`plan_chain[i]` for multi-plan; see `cross-cutting/multi-plan-chain.md`). It is a
list of entries:

```json
{
  "task": "task_<N>",
  "decision": "<key_decision text, verified ≤15 words>",
  "files": ["<paths touched>"],
  "made_at": "<iso8601>",
  "supersedes": null
}
```

**Append-only.** Entries are never deleted. A later decision that overrides an
earlier one records the earlier task id in `supersedes`; both entries stay in the
register (the superseded one is rendered with a strikethrough prefix).

## Append (Phase 1 Step 2.3)

After writing `task_summaries.task_N`, read its `key_decision`. Append a register
entry **only if** the value is non-empty AND not `"(none)"` AND not `"n/a"`
(case-insensitive after stripping). Use `state_set.py --field decisions_register`
(active-tree scope) or an atomic R-M-W. Failure → warn and continue.

## Prompt substitution (`{decisions_register}`)

Both the Implementer (Phase 1 Step 1) and the Combined Reviewer (Step 2) prompts
carry a `{decisions_register}` placeholder. It renders a `## Project decisions so
far` block from `<active>.decisions_register`, or the empty string when the
register is empty. Each line:

```
- [<task>] <decision> — <comma-joined files>
```

Superseded entries are prefixed `~~[SUPERSEDED by <task_id>]~~ `. The Reviewer's
"Decision consistency" rubric reads this block to flag conflicts.

## `decision_conflict` is a QUALITY issue, not SPEC

The Combined Reviewer flags `decision_conflict` under `QUALITY_ISSUES` with
`issue_key: decision_conflict::<file>:<line>`. It does NOT downgrade `SPEC_SCORE`,
and the standard `review_retries` budget applies — there is no spec-edit branch.
Its purpose is to nudge sub-agents toward consistency, not to halt the run.

**Intentional supersession** (the diff includes a `supersedes <task_id>` comment)
is NOT flagged — the Reviewer emits an ADVISORY note instead, and the append step
records the `supersedes` link.

## Projection to `DECISIONS.md`

- **Phase Transition T3 step 1.5** (intermediate): render `<orch_dir>/DECISIONS.md`
  from `<active>.decisions_register` as a markdown table
  `[Task, Decision, Files, Made at, Supersedes]`, sorted by `made_at` ascending,
  with superseded entries grouped in a bottom subsection. Atomic write
  (`DECISIONS.md.tmp` → `mv`). Empty register → stub
  `# Decisions register (empty)`.
- **Phase 2 Step 1** (canonical end-of-run): re-render from the full union of
  `decisions_register` across every plan (`plan_chain[*]` for multi-plan;
  top-level for single-plan). Same format and atomic-write contract. This is the
  authoritative snapshot; per-T3 projections are intermediate.

`DECISIONS.md` is included in the post-run archive tarball (F1).
