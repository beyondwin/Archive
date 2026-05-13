# JOURNAL — v2.8 Learning Log

Chronological log. Update **as you go**.

---

## 2026-05-13

### Late afternoon — Origin

User asked: "kws-codex-plan-executor에 적용한 learning-log 패턴을 kws-claude-multi-agent-executor에도 차용하려고 한다. 어떻게 구성할지 플랜 제안해줘."

Pattern reference: Codex side's two-doc design — spec at
`docs/superpowers/specs/2026-05-13-kws-codex-plan-executor-learning-log-design.md`
and plan at `docs/superpowers/plans/2026-05-13-kws-codex-plan-executor-learning-log.md`.
4-axis contract: `execution-only` × `notable-boundaries` × `redacted-context`
× `schema + helper script`.

### Late afternoon — Design iteration round 1

Initial proposal:
- single `~/.claude/learning/kws-claude-multi-agent-executor/events.jsonl`
- 7 Codex event types + 3 Claude-specific (`reviewer_warn_or_fail`,
  `escalation`, `parallel_dispatch_failure`)
- phase + risk_tier as scope dimensions instead of Codex's mode dimension
- schema extensions: `phase`, `risk_tier`, `scores` (P4), `subagent`,
  `improvement.experiment_link`

### Late afternoon — Design iteration round 2 (concurrency question)

User asked: "동시에 여러 레포에서 실행할 경우도 고려해야 해."
Response: identity block (`host`, `pid`, `session_id`, `started_at`,
`worktree_path`) + `fcntl.flock(LOCK_EX)` + 3KB line size cap.

### Evening — Design iteration round 3 (per-run shard pivot)

User pushed back: "아예 한 프로젝트에서도 여러 개 돌릴 수도 있는데 차라리
타임스탬프나 그런 걸로 한 번 동작할 때마다 아예 파일이나 경로 다르게 가져가는
게 낫지 않나?" Right call. Pivoted to per-run directory layout:

```
~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/
├── meta.json
└── events.jsonl
```

`run_id = <UTC-compact-timestamp>-<session_short>-<pid>` e.g.
`20260513T143321Z-188042f4-48211`. Drops the need for `flock` + size cap.
Helper becomes 3 stateless subcommands: `init-run`, `append`, `close-run`.
Empty runs still leave `meta.json` (negative signal).

This pivot recorded as D001.

### Evening — Sub-discovery: headless model gap

User asked how headless dispatch uses model + effort. Investigation revealed:

- SKILL.md:1015 documents "Orchestrator=Opus, Sub-agents=Sonnet" but **no
  `--model` flag is passed** to any `claude -p` subprocess (6 dispatch sites).
  Actual model is whatever the user's Claude Code CLI default is at invocation.
- "Effort" is not Claude API thinking-budget; it's a prompt-injection variable
  `{effort_guidance}` driven by P5 task_complexity buckets (SMALL/MEDIUM/LARGE),
  scaling tool-call budget and TDD strictness.

Recommendation: keep model-explicit-flag fix as a separate v2.8.x mini-PR
(out of scope for v2.8 learning log). Recorded but not actioned here.

### Evening — Sub-discovery: skill-invocation asymmetry

User asked whether headless / sub-agents use superpowers. Audit found:

- Orchestrator: 2 Skill invocations (`using-git-worktrees`, `finishing-a-development-branch`)
- Implementer: 4 Skill invocations (`test-driven-development`, `systematic-debugging`, `verification-before-completion`, `receiving-code-review`)
- **Plan Reviewer / Reviewer / Verifier: 0 invocations** — review side is empty
- Docs Updater: 0 invocations (acceptable — coherence work)

Recommendation A from chat: add `superpowers:writing-plans` (Plan Reviewer),
`superpowers:requesting-code-review` (Reviewer), `superpowers:verification-before-completion`
(Verifier) to their prompts as part of v2.8. Cheap, high-leverage.

### Evening — Scope locked

In scope for v2.8:
1. Per-run shard learning log (helper, eval, references doc)
2. Reviewer / Verifier / Plan Reviewer Skill-invocation additions (A)
3. ARCHITECTURE.md §14, HISTORY.md v2.8.0, AGENTS.md learning-log protocol
4. Smoke verification

Out of scope:
- Headless `--model` flag fix → separate v2.8.x
- Learning-log → experiment auto-trigger (B) → v2.9+
- Aggregator / reporting CLI → optional, post-merge

### Evening — Experiment scaffold created

This directory created. Branch `codex/executor-learning-log` shared with
the Codex sibling work; Claude files isolated by path. Next: write D001,
spec doc, plan doc, then call advisor.

### Evening — D001 + spec doc + plan doc drafted

D001 captured 3 core design questions (per-run shard, run_id format, helper
subcommands) + 3 out-of-scope decisions (model fix deferred, skill invocation
additions included, aggregator deferred). Spec written to
`docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-learning-log-design.md`,
plan written to the sibling `plans/` path.

### Evening — ADVISOR REVIEW

Advisor flagged four gaps before commit, three blocking:

**Q4 (BLOCKING) — Sub-agent → helper invocation mechanism**
- Original draft said sub-agents call the helper via `MAE_LEARNING_RUN_ID` env
- This conflates Agent-tool dispatch (no env propagation guarantee) and
  `claude -p` subprocess (POSIX env works)
- Fix: sub-agents NEVER call helper. They write JSON candidates to
  `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`. Orchestrator
  reads candidates and invokes `append`. Single-writer contract.

**Q5 (BLOCKING) — close-run on every exit path**
- Original draft only mentioned close-run at Phase 2
- ESCALATE halt / hook denial / hard crash skip Phase 2 → meta.json stays
  `outcome=unknown` forever
- Fix: orchestrator wraps flow with structured exit; close-run on success
  (Phase 2), blocked (ESCALATE), aborted (user/hook). Honest unknown on hard
  crash is acceptable.

**Q6 (BLOCKING) — Resume Chain × run_id**
- Original draft didn't address what happens at compaction_points ≥ 2 handoff
- Fix: Resume Chain preserves `MAE_LEARNING_RUN_ID` via `env MAE_LEARNING_RUN_ID=...`
  prepended to `nohup claude -p ...`. Chained orchestrator calls
  `append-session-id` (new 4th subcommand), NOT `init-run`. meta.json gets
  `session_ids[]` array.

**Q7 — F001 smoke needs an event-triggering fixture**
- Original draft used `01-trivial-typo.yaml` only → validates init/close but
  never tests `append` under real conditions
- Fix: F001 runs TWO smokes — happy path (01) + designed-to-WARN (fixture 08
  from v2.7, known 75% reviewer WARN rate)

Non-blocking touchups also recorded in D001: CLAUDE_SESSION_ID verification,
SKILL.md step-number drift, branch-hygiene note.

### Evening — Patches applied

D001 §Post-advisor corrections section added. Spec doc patched in 5 places:
- Sub-agent invocation contract (single-writer)
- session_ids[] in meta.json
- append-session-id subcommand documented
- Runtime Flow updated with per-exit-path close-run
- Resume Chain handoff section added
- Testing extended to 16 checks (added close-run + append-session-id) +
  smoke-A/smoke-B fixture requirement
- Pre-T2 CLAUDE_SESSION_ID check noted

Plan doc patched in 6 places:
- Architecture summary mentions 4-subcommand helper + single-writer contract
- Task 5 Step 1 rewritten to describe SKILL.md edits narratively + Resume
  Chain handoff + every-exit-path close-run
- Task 5 Steps 2/3/5 reworded so sub-agents don't call helper
- Task 7 Step 1 rewritten for TWO smokes
- Task 7 Step 2 updated for both smokes + residual risks
- Plan Self-Review extended with helper-subcommand list + post-advisor patch
  summary

Design is now ready to commit. Next: commit experiment artifacts on
`codex/executor-learning-log` branch (Claude-only files), then await
implementation green-light from user before starting T1.

---

## On close-out

(filled at end)
