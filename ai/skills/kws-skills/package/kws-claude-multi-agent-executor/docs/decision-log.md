# Decision log — ADR cross-index

A flat index of every Architecture/Design Decision Record (ADR) made across
this skill's experiments. ADRs live inside their parent experiment directory
(`docs/experiments/<version>-<name>/decisions/D###-<slug>.md`) because they're
*locally meaningful* — but it's hard to answer questions like "what design
choices have we made about scoring?" without a cross-cutting view.

This file is that view. Use it to:

- Locate the ADR explaining a current design (links per row).
- See what alternatives were considered.
- Find which experiment generated a decision.
- Audit whether a decision has been revisited / overturned.

---

## v2.7 — Quality-mode experiment (closed; negative on `quality_plus`, positive on rubric infrastructure)

| ADR | Subject | Outcome |
|-----|---------|---------|
| [D001 Floor level](../docs/experiments/v2.7-quality-mode/decisions/D001-floor-level.md) | Where to set the v2.6.0 baseline floor for comparison | **Decided** |
| [D002 Judge model](../docs/experiments/v2.7-quality-mode/decisions/D002-judge-model.md) | Sonnet vs Opus for LLM-as-judge | **Decided**: Opus + rubric.py hybrid |
| [D003 Rubric runner](../docs/experiments/v2.7-quality-mode/decisions/D003-rubric-runner.md) | Deterministic correctness measurement infrastructure | **Decided**: rubric.py |
| [D004 Pilot scope](../docs/experiments/v2.7-quality-mode/decisions/D004-pilot-scope.md) | How many reps + fixtures for the pilot | **Decided**: baseline-variance probe first |
| [D005 Experimental branch](../docs/experiments/v2.7-quality-mode/decisions/D005-experimental-branch.md) | Branch strategy for the experiment | **Decided** |
| [D006 Pilot first](../docs/experiments/v2.7-quality-mode/decisions/D006-pilot-first.md) | Pilot before full experiment build | **Decided**: pilot-first; saved 1.5+ days |
| [D007 Fixture realistic spec](../docs/experiments/v2.7-quality-mode/decisions/D007-fixture-realistic-spec.md) | Stopping fixture difficulty escalation | **Decided**: stop, avoid confirmation bias |
| [D008 quality_plus SKILL changes](../docs/experiments/v2.7-quality-mode/decisions/D008-quality-plus-skill-changes.md) | The 150-line SKILL.md change for best-of-3 + judge | **Designed but NOT shipped** — F002 ceiling killed it |

**v2.7 close-out**: see [F002-close-out.md](../docs/experiments/v2.7-quality-mode/findings/F002-close-out.md).
Negative result on the `quality_plus` hypothesis (only 0.05 of marginal gain
on the hardest fixture, not worth the surface area). Rubric infrastructure
shipped to main.

## v2.8 — Learning log (shipped, full-fixture smoke PARTIAL)

| ADR | Subject | Outcome |
|-----|---------|---------|
| [D001 Initial design](../docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md) | Per-run shard layout, run_id format, helper subcommands, scope | **Decided** + 4 advisor-patch corrections (Q4 single-writer, Q5 every-exit-path close-run, Q6 Resume Chain handoff, Q7 two-smoke fixture) |

**v2.8 close-out**: see [F001-smoke.md](../docs/experiments/v2.8-learning-log/findings/F001-smoke.md).
Smoke A clean PASS; Smoke B revealed the orchestrator-adherence gap on multi-task plans. v2.8.1 follow-up closes the gap.

## v2.8.1 — Step 7.5 enforcement (shipped, n=4 verification)

No experiment subdirectory — this was an empirical fix landed directly with
HISTORY.md entry and inline rationale. Decision substance lives in the v2.8.1
HISTORY.md entry and the commit message of `4afca2e`.

| Change | Why |
|--------|-----|
| Step 7.5 heading promoted to MANDATORY | Smoke B showed advisory framing was read as optional |
| `LEARNING_LOG_INIT:` marker emitted on both paths | Post-run adherence audit signal |
| `2>/dev/null` removed from helper call | Helper stderr surfaces if script breaks |
| `evals/run.sh` greps the marker per fixture | Adherence becomes a measurable property |
| 18th contract check in `check_skill_contract.py` | Locks the MANDATORY framing in place |

## v2.9 — Reviewer Spec Coverage Walk (shipped 2026-05-14)

| ADR | Subject | Outcome |
|-----|---------|---------|
| [D001 Initial design](../docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md) | Single-pass walk vs multi-perspective dispatch; evidence selection from omc 7-item shortlist; **§Q3 critical post-advisor-pre-check patch** adding adversarial generation for meta-rules | **Decided** |

**v2.9 findings**:
- [F001-T4.5-dry-run.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F001-T4.5-dry-run.md) — single-rep pilot; walk mechanism PASSED, failure mode shifted (silent miss → spec ambiguity surfaced)
- [F002-T5-n4-results.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md) — n=4 reps under v2.8.1 + clarified spec + v2.9 prompt; all four pass criteria satisfied; SHIP

---

## Cross-cutting decisions (not under one experiment)

### Orchestrator-Worker pattern (vs single-session)

Documented in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 + §11. Origin in
v2.4.0. Choice: Opus orchestrator + Sonnet sub-agents matches Anthropic
guidance for plan execution. Tradeoff vs single-session: better parallelism,
fresh context per sub-agent, costlier in tokens.

### Per-run sharded learning log (vs single `events.jsonl`)

ADR: v2.8 D001 §Question 1. Origin: user pushback during design round 3 of
v2.8. Choice: per-run directory layout eliminates concurrent-write
contention without `flock`. Empty runs still leave `meta.json` as a
negative signal.

### Single-writer contract on the learning-log helper

ADR: v2.8 D001 §Q4 (advisor-patch). Origin: pre-ship advisor review caught
that sub-agents calling the helper via `MAE_LEARNING_RUN_ID` would conflate
Agent-tool dispatch (no env propagation) with `claude -p` subprocess (POSIX
env works). Choice: sub-agents write JSON candidates; orchestrator is sole
caller.

### `close-run` on every exit path

ADR: v2.8 D001 §Q5 (advisor-patch). Origin: original design only invoked
`close-run` at Phase 2. ESCALATE / hook denial / hard crash would leave
`meta.outcome=unknown` forever. Choice: explicit close-run at success
(Phase 2), blocked (ESCALATE / state-write fail), aborted (user/hook).
Hard crash → `unknown` is honest.

### Adversarial generation from meta-rules in Spec Coverage Walk

ADR: v2.9 D001 §Q3. Origin: pre-advisor self-check caught that the initial
"strict-template enumeration only" design would not surface `30m20m` on
fixture 08 (the case is covered only by the spec's meta-rule). Choice: walk
has two ordered sub-steps; sub-step B explicitly requires ≥3 adversarial
inputs per meta-rule.

### MANDATORY framing for Step 7.5 (v2.8.1)

Empirical decision documented in HISTORY.md v2.8.1 entry. Origin: Smoke B
in F001-smoke.md showed 0 of 47 Bash invocations called the helper despite
SKILL.md instructing it. Choice: stronger prose + visible marker +
eval-level adherence check. Hook-based enforcement deferred to v2.10+
([`deferred-candidates.md`](./deferred-candidates.md) §Hooks).

---

## Decisions that have been overturned / superseded

| Original decision | Superseded by | Why |
|--------------------|---------------|-----|
| v2.8 Step 7.5 "advisory" framing (`2>/dev/null \|\| echo ""`) | v2.8.1 MANDATORY framing + marker | Empirical adherence regression in Smoke B |
| v2.8 D001 initial "sub-agents call helper via env" | v2.8 D001 §Q4 single-writer contract | Advisor caught env-propagation ambiguity |
| v2.8 D001 initial "close-run only at Phase 2" | v2.8 D001 §Q5 every-exit-path close-run | Advisor caught `outcome=unknown` regression |
| v2.9 D001 initial "strict-template enumeration only" | v2.9 D001 §Q3 enumeration + adversarial generation | Pre-advisor self-check caught `30m20m` not surfaced by enumeration alone |
| v2.7 D008 `quality_plus` design | (never shipped) | F002 ceiling result: marginal gain not worth implementation surface |

## How to add an ADR

New ADRs go inside their parent experiment directory:
```
docs/experiments/v2.X-<name>/decisions/D00N-<short-slug>.md
```

Use [`_template/decisions/D000-template.md`](../docs/experiments/_template/decisions/D000-template.md)
as the starting point. Standard sections: Context · Options · Decision ·
Rationale · Consequences · Links.

Then add a row to this file's relevant section (v2.X table) so it's
discoverable via cross-cutting search.

For *cross-cutting* decisions that span experiments (like the
Orchestrator-Worker pattern), add to the "Cross-cutting decisions" section
above with a pointer to whichever ARCHITECTURE.md section or HISTORY.md
entry holds the substance.
