# Deferred candidates — future-work shelf

Candidate changes that have been considered, deliberately deferred, and
remain on the shelf pending evidence or scope. Each entry has:

- A **proposed change** (what would land if pursued)
- **Origin** (where the idea came from)
- **Why deferred** (the specific reason it's not in current scope)
- **Revisit criteria** (concrete trigger to reconsider)

This file is the answer to "what's the next plausible thing?". Read it
when planning a new experiment or major version bump. Update it when an
item is either pursued or dropped permanently.

---

## omc-inspired candidates (deferred 2026-05-14 after T5 PASS)

These six items came from a 2026-05-13 analysis of
`https://github.com/yeachan-heo/oh-my-claudecode` (omc), a 33K-star
Teams-first multi-agent orchestration project. v2.9.0 shipped only item C
(Reviewer "What's Missing" walk — the only one with measured KCMAE
failure evidence). The other six remain on this shelf.

| Item | Description | Defer reason | Revisit when |
|------|-------------|--------------|--------------|
| **D — Governance flags** | Defensive config flags for autonomous skill invocation (e.g., max-recursion depth, max-cost per run, allowlist for skill chaining) | No measured KCMAE incident requiring this; defensive surface; would touch SKILL.md broadly | Any "self-spawn went wild" or "cost runaway" event surfaces in the learning log; OR after 1-2 weeks of v2.8.1 runtime data |
| **E — Heartbeat freshness** | Monitor process emits periodic heartbeat; orchestrator detects subprocess hang via heartbeat staleness | No measured hang case in F001/F002 (`kill -0 $PID` already detects most issues) | A `claude -p` subprocess hangs without exiting in a real run |
| **F — Conflict-mailbox event type** | New learning-log event type for cross-agent merge collisions (omc uses this for parallel-branch auto-merge) | v2.8 learning log not yet event-rich; KCMAE is in-process Phase 1 (no parallel branches at orchestrator level) | Real `parallel_dispatch_failure` event surfaces OR v2.10 introduces parallel-branch dispatch |
| **G — Sentinel READY gate** | Explicit "ready" sentinel emitted by sub-agent before dispatch unblocks the next step (omc pattern for tmux-pane orchestration) | KCMAE's 3-sec sleep + kill check has not failed in eval corpus; sub-agent dispatch is in-process, no race | A sub-agent dispatch race / premature progression is observed |
| **A — Inbox/Outbox messaging** | Per-pane JSONL messaging for cross-agent communication (omc uses this because it runs N CLI processes in tmux) | KCMAE uses in-process Agent-tool dispatch + Resume Chain `claude -p`. Current ESCALATE mechanism not insufficient for any measured case | KCMAE topology changes to multi-process (currently no plan); OR cross-orchestrator messaging need surfaces |
| **B — Auto-merge orchestrator** | Auto-merge logic for parallel branches (omc M1-M6 hardening for its multi-pane topology) | KCMAE merges in-process; no parallel orchestrator-level branches. Topology mismatch | Topology pivot to multi-orchestrator parallel work (not currently planned) |

**Re-rank trigger** (whole-set): 1-2 weeks of v2.8.1 runtime usage with the
learning log capturing real failures. Re-evaluate each item against actual
event-stream evidence, not analogy from omc.

**Reference**: `docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md` §Out-of-scope.

---

## Hook-based enforcement of Step 7.5

**Proposed change**: A PreToolUse hook that auto-runs `init-run` before
the orchestrator's first non-trivial Bash call. Replaces v2.8.1's prose
+ marker mechanism with structural enforcement.

**Origin**: v2.8 F001 Smoke B adherence gap + risks-and-limitations
"Adherence marker is spoofable".

**Why deferred**:
- Scoping issue: SessionStart hook would fire on every `claude -p`
  including non-orchestrator runs.
- PreToolUse hook fires too late (after orchestrator already started)
  and on the wrong context.
- These hooks live in `.claude/hooks/` settings, not inside the skill —
  adding them blurs the boundary between skill and environment.

**Revisit when**:
- v2.8.1's marker-based detection misses a real adherence regression in
  production runtime.
- Hook framework gains skill-scoped event types (e.g., "fires only for
  skills X, Y, Z").

---

## Headless model flag

**Proposed change**: Pass `--model claude-opus-4-7` (orchestrator) and
`--model claude-sonnet-4-6` (sub-agents) explicitly on all 6 `claude -p`
dispatch sites in SKILL.md.

**Origin**: v2.8 design audit found documented model assignment doesn't
match runtime behavior (model is inherited from CLI default).

**Why deferred**:
- Behavior change, not observability change. Bundling with v2.8 (an
  observability addition) would conflate scopes.
- A separate v2.8.x mini-PR is the right shape — single-purpose, low risk.

**Revisit when**: Next time a user reports unexpected reasoning depth or
cost (likely indicator: orchestrator ran on Sonnet but user expected Opus).

**Reference**: `docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Out-of-scope.

---

## Verifier acceptance-criteria coverage walk

**Proposed change**: Extend the v2.9 Spec Coverage Walk pattern to the
Verifier — emit a `CRITERIA_COVERAGE_WALK:` block enumerating spec
acceptance criteria + adversarial criteria-violation inputs before
verifying.

**Origin**: v2.9 D001 §Open question Q3.

**Why deferred**:
- Verifier failure rate is not measured at this granularity (no F002-
  equivalent evidence for Verifier).
- v2.9's pilot-strength evidence is fixture-specific; generalizing the
  walk pattern to another role before validating on its own data would
  compound the over-tuning risk.

**Revisit when**: A measured Verifier failure (`verification_failure`
event in the learning log) surfaces a case the prompt missed.

---

## Walk pattern validator in `check_skill_contract.py`

**Proposed change**: Add a contract check that the Reviewer prompt's
walk template specifies the strict row format `"<frag>" :: <file>:<line>
| NOT FOUND | PARTIAL`. Currently the v2.9.0 check only verifies that
the section title is present.

**Origin**: v2.9 D001 §Open question Q2.

**Why deferred**:
- Adds eval surface for marginal benefit — the walk is a prompt-level
  discipline, not a structural contract.
- Would need iteration as the walk template evolves; risk of contract-
  check becoming the limiting factor on legitimate prompt improvements.

**Revisit when**: The walk template stabilizes across 2+ minor versions
without further iteration.

---

## Fixture spec audit (01-07)

**Proposed change**: Manually audit fixtures 01-07 for spec-vs-rubric
ambiguity (same kind that v2.9 Phase 2 fixed for fixture 08).

**Origin**: risks-and-limitations §Spec ambiguity vs rubric strictness.

**Why deferred**:
- Not blocking any current work.
- May produce false-positive flags on already-stable fixtures.

**Revisit when**: Any rerun of fixtures 01-07 produces a confusing
"rubric FAIL but Reviewer PASS" (or vice versa) — the inverse of the
v2.9 T4.5 finding.

---

## Aggregator / reporting CLI for the learning log

**Proposed change**: A small CLI that reads
`~/.claude/learning/kws-claude-multi-agent-executor/runs/**/events.jsonl`
and emits summaries (top event types, recurring failure signatures,
time series).

**Origin**: v2.8 D001 §Out-of-scope.

**Why deferred**: Requires a real event corpus first. v2.8 runtime data
is currently sparse (and v2.8.0's adherence gap means even sparser).

**Revisit when**: Post-v2.8.1, after 1-2 weeks of routine use with the
adherence fix in place.

---

## Auto-trigger from learning log → experiment scaffold

**Proposed change**: A meta-skill that watches the learning log for
recurring patterns and auto-generates an experiment scaffold (D001
template + README + plan stub) for the surfaced issue.

**Origin**: v2.8 D001 §Out-of-scope.

**Why deferred**: Requires the aggregator (above) as a prerequisite,
which requires the corpus, which requires v2.8.1 in production for 1-2
weeks. Two layers of prerequisites.

**Revisit when**: After the aggregator ships and identifies a manual
case the user already wishes had been auto-scaffolded.

---

## How to add a candidate

When you decide *not* to do something now but want to keep the option
open:

1. Add a section above with: proposed change, origin (commit / discussion /
   experiment), why deferred, revisit criteria.
2. Make revisit criteria *concrete* — "after 1-2 weeks", "when N events
   surface", "if X is reported" — not "in the future".
3. Add to [`decision-log.md`](./decision-log.md) §Overturned table if it
   supersedes a prior decision.
4. Update or remove the entry when the criterion is met (do the work) or
   the criterion becomes irrelevant (close as won't-do with a note).

The goal: never lose a good idea, never let an old idea become a hidden
backlog burden.
