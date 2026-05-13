# kws-claude-multi-agent-executor

A Claude Code skill that autonomously executes an implementation plan via an
Opus **Orchestrator** + Sonnet **sub-agents** (Implementer / Reviewer /
Verifier / Plan Reviewer / Docs Updater). The orchestrator drives a deterministic
3-phase lifecycle, isolates each plan run in a git worktree, scores each task
with a structured rubric, and persists notable-boundary events to a user-local
learning log for future skill improvements.

**Current version**: `2.9.0` (2026-05-14) — see [`HISTORY.md`](./HISTORY.md) for
the version timeline.

## Quick start

The skill is installed at `~/.claude/skills/kws-claude-multi-agent-executor/`
(symlinked from this source). Invoke it from Claude Code:

```
/kws-claude-multi-agent-executor plan=<path-to-plan.md> spec=<path-to-spec.md>
```

Optional invocation parameters: `risk=<low|mid|high>`, `docs_scope=<file1,file2>`,
`plan2=<chained-second-plan.md>`, `mode=<interactive|headless>`. Full invocation
contract: see [`SKILL.md`](./SKILL.md) Phase 0.

## Document map — where to find what

### I want to understand…

| Question | Document |
|----------|----------|
| What this skill is and a quick mental model | This file (above) + [`ARCHITECTURE.md`](./ARCHITECTURE.md) §1 |
| The complete runtime behavior — phases, sub-agents, dispatch, scoring | [`ARCHITECTURE.md`](./ARCHITECTURE.md) §2-§12 |
| A guided walkthrough of one plan execution | [`docs/how-it-works.md`](./docs/how-it-works.md) |
| What every term means (orchestrator / sub-agent / worktree / risk tier / …) | [`docs/glossary.md`](./docs/glossary.md) |
| How version 2.X differs from 2.Y | [`HISTORY.md`](./HISTORY.md) §1 |
| Which improvement areas have been touched and when | [`HISTORY.md`](./HISTORY.md) §2 |

### I want to run / operate the skill…

| Task | Document |
|------|----------|
| Invoke the skill on a plan | [`SKILL.md`](./SKILL.md) Phase 0 §Invocation |
| Run the regression eval suite | [`evals/README.md`](./evals/README.md) |
| Read or analyze the learning log | [`references/learning-log.md`](./references/learning-log.md) |
| Diagnose a failed run | [`docs/troubleshooting.md`](./docs/troubleshooting.md) |
| Replay a specific session for debugging | [`docs/how-it-works.md`](./docs/how-it-works.md) §Replay |

### I want to contribute / change behavior…

| Task | Document |
|------|----------|
| Where AI contributors should start | [`docs/onboarding-for-ai-agents.md`](./docs/onboarding-for-ai-agents.md) |
| Required record-keeping protocol (experiment / history / advisor) | [`AGENTS.md`](./AGENTS.md) |
| Start a new experiment (≥50-line change or non-trivial hypothesis) | [`docs/experiments/README.md`](./docs/experiments/README.md) + [`docs/experiments/_template/`](./docs/experiments/_template/) |
| Add a new eval fixture | [`evals/README.md`](./evals/README.md) §Fixture format |
| Understand why a design decision was made | [`docs/decision-log.md`](./docs/decision-log.md) |
| Bump version + release | [`AGENTS.md`](./AGENTS.md) §ARCHITECTURE.md sync + [`HISTORY.md`](./HISTORY.md) §Update protocol |

### I want to understand limits and future work…

| Question | Document |
|----------|----------|
| What's known to be unreliable / fragile / partially-validated | [`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) |
| What's been considered and deliberately deferred | [`docs/deferred-candidates.md`](./docs/deferred-candidates.md) |
| Why a specific decision was made (and the alternatives considered) | [`docs/decision-log.md`](./docs/decision-log.md) → individual D### files |
| What recent experiments produced | [`docs/experiments/`](./docs/experiments/) |

### I'm an AI agent continuing this work in a future session

Read **in this order**:

1. This README (you are here)
2. [`docs/onboarding-for-ai-agents.md`](./docs/onboarding-for-ai-agents.md) — operating norms, where to start
3. [`AGENTS.md`](./AGENTS.md) — record-keeping protocol (REQUIRED)
4. [`ARCHITECTURE.md`](./ARCHITECTURE.md) §1-§4 — orchestrator-worker mental model
5. [`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) — known fragilities
6. [`HISTORY.md`](./HISTORY.md) §1 most-recent two entries — what changed recently
7. [`docs/decision-log.md`](./docs/decision-log.md) — index into the deeper "why"s

Then load specifics (SKILL.md, learning-log.md, fixture YAMLs, etc.) on demand.

## Key invariants (memorize these)

These are the load-bearing rules. Violating them breaks the skill in ways
that may not surface until much later.

1. **One orchestrator, one git worktree, one `state.json`.** Plan execution is
   sequential per worktree. Concurrent runs use separate worktrees (no shared
   state). See [`ARCHITECTURE.md`](./ARCHITECTURE.md) §5-§6.
2. **Sub-agents NEVER call the learning-log helper directly.** They write
   candidate JSON to `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`;
   the orchestrator (single writer) invokes `append`. See [`references/learning-log.md`](./references/learning-log.md).
3. **Step 7.5 init-run is MANDATORY** (v2.8.1). Skipping it breaks
   observability for the entire run — no meta.json, no events.jsonl. The
   `LEARNING_LOG_INIT:` marker in run.jsonl is the post-run audit signal.
4. **`close-run` runs on every exit path**: `outcome=success` (Phase 2 done),
   `outcome=blocked` (state-write failure, exhausted escalation), `outcome=aborted`
   (user/hook abort). Hard crash leaves `outcome=unknown` (honest).
5. **Risk tiering drives TDD strictness, not model selection.** Model
   selection is documented as Orchestrator=Opus / Sub-agents=Sonnet but the
   `--model` flag is not yet passed to `claude -p` subprocesses ([`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) §Headless model gap).
6. **Reviewer emits `SPEC_COVERAGE_WALK:` before scoring** (v2.9.0). Two
   sub-steps: A enumerate stated bullets, B adversarial generation from
   meta-rules. See [`references/reviewer-prompt.md`](./references/reviewer-prompt.md).

## Repo layout

```
package/kws-claude-multi-agent-executor/
├── README.md                       ← you are here
├── SKILL.md                        ← the executable skill (v2.9.0)
├── ARCHITECTURE.md                 ← system-level design (14 sections)
├── AGENTS.md                       ← AI-contributor operational protocol
├── HISTORY.md                      ← version timeline + improvement areas + experiment index
├── docs/
│   ├── how-it-works.md             ← guided runtime walkthrough  [NEW]
│   ├── glossary.md                 ← terminology  [NEW]
│   ├── decision-log.md             ← ADR cross-index  [NEW]
│   ├── risks-and-limitations.md    ← consolidated risk register  [NEW]
│   ├── deferred-candidates.md      ← future-work shelf  [NEW]
│   ├── onboarding-for-ai-agents.md ← what an AI agent reads first  [NEW]
│   ├── troubleshooting.md          ← common issues + fixes  [NEW]
│   └── experiments/
│       ├── README.md               ← experiment index
│       ├── _template/              ← scaffold for new experiments
│       ├── v2.7-quality-mode/      ← closed (negative result on quality_plus)
│       ├── v2.8-learning-log/      ← shipped (full-fixture smoke PARTIAL, v2.8.1 closes the gap)
│       └── v2.9-reviewer-spec-coverage/  ← shipped 2026-05-14
├── references/
│   ├── implementer-prompt.md       ← sub-agent prompt template
│   ├── reviewer-prompt.md          ← sub-agent prompt template (v2.9.0 Spec Coverage Walk)
│   ├── verifier-prompt.md          ← sub-agent prompt template
│   ├── plan-reviewer-prompt.md     ← sub-agent prompt template
│   ├── docs-updater-prompts.md     ← Phase 2 docs-update sub-agent prompts
│   ├── escalation-playbook.md      ← ESCALATE-type → event severity mapping
│   ├── learning-log.md             ← schema + single-writer contract + 10 event types
│   └── best-of-n-judge-prompt.md   ← orphan reference (v2.7 deferred)
├── evals/
│   ├── README.md                   ← eval harness explainer
│   ├── run.sh                      ← per-fixture harness (bash + jq)
│   ├── rubric.py                   ← deterministic correctness measurement
│   ├── judge.md                    ← LLM-as-judge prompt
│   ├── check_learning_log.py       ← 16 deterministic checks (helper)
│   ├── check_skill_contract.py     ← 18 deterministic checks (skill contract)
│   ├── fixtures/                   ← 8 YAML fixtures (01-08)
│   ├── baselines/                  ← per-version judge mean + scores
│   └── calibration/                ← judge calibration test runner (v2.7 artifact)
├── scripts/
│   └── append_learning_event.py    ← 4-subcommand helper (init-run / append / close-run / append-session-id)
└── templates/
    └── (currently empty — reserved for future scaffolds)
```

## Cross-Archive context

This skill lives inside the `kws-skills` plugin at the Archive-level repo.
Related artifacts outside this directory:

- **Design specs**: `docs/superpowers/specs/2026-05-13-kws-claude-multi-agent-executor-*.md`
- **Implementation plans**: `docs/superpowers/plans/2026-05-13-kws-claude-multi-agent-executor-*.md`
- **Sibling skill** (Codex executor parallel design): `package/kws-codex-plan-executor/`
- **Plugin manifest**: `kws-skills/manifest.json`, `kws-skills/README.md`, `kws-skills/CHANGELOG.md`

## What's proposed but not yet written

If you want to extend the doc set, these are next-natural additions:

- `docs/how-to/add-a-fixture.md` — step-by-step for extending the eval suite
- `docs/how-to/investigate-regression.md` — debugging guide when a rep regresses
- `docs/how-to/extend-event-type.md` — adding a new learning-log event type
- A versioned snapshot doc per major version (e.g., `docs/snapshots/v2.9.0.md`)
  capturing the complete state at ship-time for archaeological reference

None of these block normal operation. Open them when the corresponding need
arises (the pattern: write the doc *while* you do the thing, then it's both
done and recorded).
