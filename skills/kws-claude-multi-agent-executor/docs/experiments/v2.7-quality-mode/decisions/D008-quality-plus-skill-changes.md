# D008 — quality_plus mode: SKILL.md change design

**Date**: 2026-05-13 (evening)
**Status**: Draft (pending ceiling check #2 result)

## Goal

Add `mode=balanced|quality_plus` invocation parameter to SKILL.md on the
experiment branch. When `mode=quality_plus`, MID and HIGH risk tasks
dispatch N=3 parallel Implementer candidates (Opus model) followed by an
Opus judge that picks the winner. The winner's commit is cherry-picked
into the main worktree; losers are discarded.

`mode=balanced` (default) preserves v2.6.0 behavior exactly. quality_plus
is feature-flagged on this parameter only.

## Change surface (minimal-invasive)

### 1. Phase 0 — invocation parsing (small)

Add to Phase 0 Step 1 (parse invocation arguments):

> `mode=balanced|quality_plus` — defaults to `balanced`. Record in
> `state.json.mode`. Validate: only those two literals; any other value →
> halt with "unknown mode: <value>; supported: balanced | quality_plus".

### 2. Phase 0 — risk adjustment (small)

Add to Phase 0 Step 4 (assign risk levels), after the LOW→MID overlap
upgrade rule:

> **quality_plus mode adjustment:** if `state.mode == "quality_plus"`, any
> task still classified LOW after the overlap-upgrade step is upgraded to
> MID. Reason: per the v2.7 quality-mode design, batch verifier and
> SMALL bucket are disabled in quality_plus.

### 3. Phase 1 — Step 1 branch (small)

In Phase 1 Step 1 (Dispatch Implementer), add a branch at the start:

> **Mode-gated branch:**
> - If `state.mode == "quality_plus"` AND task risk is MID or HIGH AND
>   parallel-group size is 1 (i.e., this task would be a standard
>   sequential dispatch): run the **Best-of-N Sub-Flow** described in
>   the new section below, then continue to Step 2 (Combined Reviewer).
> - Otherwise: run the standard single-Implementer dispatch as documented.

Parallel groups (P2 multi-task) still take the existing P2 Parallel
Sub-Flow path — best-of-N applies only to singleton groups, to avoid
combinatorial worktree explosion.

### 4. New section — Best-of-N Sub-Flow (medium)

Insert after the existing Parallel Sub-Flow section. Procedure:

**Step B.1: Create N candidate sub-worktrees**

Reuse the same sub-worktree pattern as P2. Path:
`<worktree_path>/.bestofn/candidate_<i>` for i in 0..N-1, where N=3.
Replicate safety hooks identically to P2 Step P.1.

**Step B.2: Dispatch N Implementers in parallel, all Opus**

In a single assistant message, emit N `Agent` tool calls. Each:
- `subagent_type=general-purpose` (no specialized sub-agents needed)
- `model="opus"`
- Prompt built from `references/implementer-prompt.md` with the SAME
  template fields as the standard dispatch (same spec, same Files,
  same effort_guidance). The only differences across candidates are
  (a) the sub-worktree path, and (b) the candidate index, which is
  passed as a small "you are candidate i of N — work independently"
  preamble so candidates know they are part of a best-of-N.

**Step B.3: Collect results**

For each candidate:
- `STATUS: DONE` → record sub-worktree path, commit SHA, FILES_CHANGED, diff
- `STATUS: ESCALATE` → record escalation reason; do not include in judge input

If 0 candidates DONE: all escalated → handle as a single Implementer
ESCALATE (Escalation Protocol). Discard sub-worktrees.

If 1 candidate DONE: skip judge, use that candidate directly. (Justification:
no selection signal possible; the lone DONE candidate is the only option.)

If 2+ candidates DONE: proceed to Step B.4.

**Step B.4: Run judge**

Build judge prompt from `references/best-of-n-judge-prompt.md`. Pass
candidate diffs collected in B.3, the task spec, task rubric (if
available — see `expected.rubric` in fixture; for non-fixture runs,
omit).

Dispatch via `claude -p --dangerously-skip-permissions --model opus`
(headless subprocess, NOT Agent tool — needs deterministic JSON
parsing). Result path: `<worktree_path>/.bestofn/judge_decision.json`.

Parse winner. If `escalate: true` in judge output: discard all
candidates and re-dispatch as standard Implementer in main worktree
(Escalation Protocol). Record in state.json:
`task_N.bestofn_escalations += 1`. Cap at 2.

**Step B.5: Cherry-pick winner**

```
cd <worktree_path>
git cherry-pick <winner_sub_worktree_HEAD_sha>
```

If cherry-pick produces no conflicts (expected — each candidate started
from same pre_task_sha): proceed. If conflicts: log diagnostic, treat
as Escalation Protocol with reason "best-of-n cherry-pick conflict —
likely candidate touched files outside FILES_CHANGED scope."

**Step B.6: Cleanup**

```
git worktree remove --force <worktree_path>/.bestofn/candidate_0
git worktree remove --force <worktree_path>/.bestofn/candidate_1
git worktree remove --force <worktree_path>/.bestofn/candidate_2
rm -rf <worktree_path>/.bestofn
```

Record in state.json `task_N.bestofn`:
```json
{
  "n": 3,
  "winner_candidate": <int>,
  "judge_scores": [...],
  "judge_reasons": "<string>",
  "discarded_commits": ["<sha>", "<sha>"]
}
```

**Step B.7: Continue**

Return to Phase 1 Step 2 (Combined Reviewer) with the merged main-worktree
state. Combined Reviewer is unaware of the best-of-N internal mechanism;
it sees the winning candidate's diff exactly as it would see a standard
Implementer's diff.

### 5. state.json schema additions (small)

```diff
  "schema_version": "2",
  "mode": "balanced",                          // NEW: "balanced" | "quality_plus"
  "tasks": {
    "task_N": {
      "status": "...",
      "risk": "...",
      ...
+     "bestofn": {                              // present only if mode=quality_plus AND task is MID/HIGH
+       "n": 3,
+       "winner_candidate": 1,
+       "judge_scores": [...],
+       "judge_reasons": "...",
+       "discarded_commits": ["...", "..."]
+     },
+     "bestofn_escalations": 0                  // counter, cap at 2
    }
  }
```

## Risk-mitigation guardrails

- best-of-N applies only to singleton parallel groups, never to multi-task
  parallel groups (avoid 3 × group_size sub-worktree explosion)
- if N candidates collectively touch files outside their task's declared
  Files: block, the FILES_CHANGED check catches this (existing P2 logic
  reused)
- escalation cap = 2 best-of-N retries per task; on 3rd failure, fall
  back to standard single Implementer in main worktree

## What is NOT changed

- Combined Reviewer prompt, Verifier prompt — unchanged. They see merged
  diff, agnostic to whether single or best-of-N produced it.
- Docs Updater — unchanged.
- Plan Reviewer (P3) — unchanged.
- v2.6.0 balanced behavior — bit-for-bit unchanged (the new logic is
  gated entirely on `mode == "quality_plus"`).

## Cost projection per task

- balanced (MID task): ~$3–8 per Implementer + ~$2 Reviewer + ~$1 Verifier
- quality_plus (MID task): 3× Opus Implementer (~$15–30) + Opus judge
  (~$5–10) + Reviewer (~$2) + Verifier (~$1) = **~$25–45 per task**

For fixture 08 (2 MID tasks): balanced ~$12–18, quality_plus ~$50–90.

## Open questions

1. **Should N be configurable?** Default N=3 per advisor's research-blog
   reference. Could expose `--n=2|3|5` later. Defer.
2. **What if judge picks a candidate that fails Combined Reviewer?**
   Existing retry flow handles it (counts against `review_retries`).
3. **Token budget**: Opus Implementer on a small fixture could blow
   budget. Add fixture-level `cost_budget` check before best-of-N
   dispatch? Defer — fixture-level budget is already tracked by harness.
