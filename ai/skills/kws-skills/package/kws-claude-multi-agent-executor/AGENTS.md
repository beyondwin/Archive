# AGENTS.md — kws-claude-multi-agent-executor

Conventions for any agent (Claude, GPT, etc.) editing this skill.

## Experiment & history record-keeping (REQUIRED)

When you are about to do **any** of the following on this skill, **first** start
an experiment record before substantive work:

- SKILL.md change ≥ 50 lines
- Multi-file behavioral change
- Anything with a hypothesis that could be wrong
- New fixture design, new evaluation method, new judge prompt
- Cost > $20 in API or > 1 hour of substantive work

Bypass this protocol only for: mechanical edits (typo, rename, dep bump),
single-line bug fixes, or doc-only updates.

### Protocol

1. **Create the experiment directory** before any code change:
   ```
   docs/experiments/<version>-<short-name>/
   ├── README.md         # copy from docs/experiments/_template/
   ├── JOURNAL.md        # copy from template
   ├── decisions/        # ADRs land here as decisions accrue
   └── findings/         # data + close-out land here
   ```

2. **Update JOURNAL.md as you go.** Each significant decision, each advisor
   review, each pivot. Timestamps + reasoning. Future-you needs to resume
   from cold context.

3. **Write an ADR for any decision that** required judgment, could be revisited,
   or was rejected. Use `D###-<topic>.md`. Template: `_template/decisions/D000-template.md`.

4. **Reference ADRs in commit messages**: `feat(skill): X (per D003)`.

5. **At close-out**: write `findings/F##-close-out.md` with explicit ship/skip
   decision. Update the experiment's README status. Update the index in
   `docs/experiments/README.md` and the §3 table in `../HISTORY.md`.

6. **Before substantive code work**, call advisor. Before claiming work done,
   call advisor again. (See parent CLAUDE Code's advisor tool.)

### Why this matters

Past experiments on this skill (v2.5.x P1–P6, v2.6.0 harness stabilization,
v2.7 quality-mode) involved multi-turn judgment calls, advisor reviews, and
pivots that produced essential knowledge — but that knowledge dissolves at
session end if not durably recorded. The `docs/experiments/` structure is
this skill's institutional memory.

If you find yourself making a non-trivial decision without an experiment
directory open, STOP and create one. Then resume.

## Learning log operational protocol (v2.8+)

The skill emits structured learning events to a user-local per-run sharded
log. As an agent editing this skill, you should:

- **Read recent events when starting work on a related area.** Glob
  `~/.claude/learning/kws-claude-multi-agent-executor/runs/**/events.jsonl`
  and look for repeated `issue_key`s, `improvement.target`s, or
  `event_type`s touching the file you're about to edit. Past run data is
  cheap context.
- **Do not write events yourself when running the skill.** The skill's
  own runtime (orchestrator) handles emission. Manual writes from
  outside an orchestrator run would pollute the dataset.
- **Treat the log as observability, not state.** Plan execution must never
  depend on it; conversely, deleting old run directories never breaks the
  skill. The `meta.json` `outcome` field is the canonical "did this run
  finish cleanly?" signal — use it when summarizing skill performance.
- **When changing event types or schemas**, update `references/learning-log.md`,
  ARCHITECTURE.md §14, and `evals/check_learning_log.py` in the same commit.
  Bump skill minor version. Past events on disk retain the older schema —
  the `schema_version` field on each event records which contract it was
  written under.
- **Privacy is non-negotiable.** If you encounter an event with a secret,
  absolute home path, full transcript, or other forbidden content, treat
  it as a helper bug and fix the rejection path. Do not weaken redaction
  to make a candidate pass.

See `references/learning-log.md` for the full schema and `docs/experiments/v2.8-learning-log/`
for the implementation history.

## File responsibilities (quick reference)

- **`README.md`** (root) — navigation hub. Update when adding a new top-
  level doc or moving file locations.
- **`SKILL.md`** — current skill behavior. The runtime reads this. Treat
  edits with care; any change here can affect every future invocation.
- **`ARCHITECTURE.md`** — comprehensive overview of how the skill is built.
  Update whenever you change any topic listed in its §13 Update protocol
  (sub-agent catalog, state schema, isolation, risk tiers, scoring,
  eval harness, failure modes). Same commit as the SKILL.md change.
- **`HISTORY.md`** — narrative history of versions + improvement areas.
  Update on every shipped version. Cross-references ARCHITECTURE.md.
- **`DESIGN-v<X>.md`** — point-in-time design doc for that version. Frozen.
- **`references/`** — sub-agent prompt templates (Implementer, Reviewer,
  Verifier, Documenter, Plan Reviewer, etc.). Versioned together with
  SKILL.md.
- **`evals/`** — fixtures, harness, judge, baselines. Independent of SKILL.md
  changes — eval improvements ship orthogonally.
- **`docs/experiments/`** — institutional memory. One subdirectory per
  experiment. Read before starting related work; write as you do related work.
- **`docs/`** (top-level, non-experiment) — navigation + cross-cutting
  docs. Glossary, decision-log, risks-and-limitations, deferred-candidates,
  onboarding-for-ai-agents, troubleshooting, doc-update-protocol,
  snapshots, how-to. Owned by whoever ships the relevant change — see
  `docs/doc-update-protocol.md` for what to update when.

## Doc-update protocol (REQUIRED on every non-trivial change)

When you ship anything that's not a typo or whitespace fix, consult
**`docs/doc-update-protocol.md`** to determine which docs need updating.
The protocol has a per-change-type checklist (skill behavior / new event /
new fixture / risk / decision / etc.). It is your obligation to:

1. Read the relevant checklist before opening the commit.
2. Do every required update in the same commit (atomicity matters —
   docs and code drift apart fastest when they ship separately).
3. Run `evals/check_doc_freshness.py` before commit (or rely on
   `evals/run.sh` preflight, which invokes it non-blocking).

The freshness check catches:
- Version mismatch across SKILL.md / manifest / README
- Broken internal markdown links
- HISTORY.md missing an entry for the current SKILL.md version
- Minor-version bumps without a `docs/snapshots/v<X>.md` snapshot
- ADRs in `docs/experiments/*/decisions/` not indexed in `docs/decision-log.md`
- Stale TODO/FIXME/XXX/WIP marker counts (reported, not failed)

Strict mode (`DOC_FRESHNESS_STRICT=1`) makes the check fail the preflight.
Use strict mode in CI; non-strict for interactive development.

## ARCHITECTURE.md sync (REQUIRED on behavior changes)

When changing SKILL.md behavior, ARCHITECTURE.md §13 lists what triggers an
update. Examples that REQUIRE ARCHITECTURE.md update in the same commit:

- Add/remove/rename a sub-agent role
- Add/remove a state.json field, or change a field's semantics
- Change a risk-tier criterion or upgrade rule
- Change quality-score thresholds or tier definitions
- Add a new failure-mode response or escalation category
- Add a new hook category
- Add a new measurement layer to the eval harness

Do NOT update ARCHITECTURE.md for: new fixture, bug fix, prose tweak,
typo, refactor that doesn't change behavior. Those go in SKILL.md /
commit message only.

## When in doubt

- Ask first: does this need an experiment record? (If unsure, yes — it's
  cheap to create one and skip it later.)
- Prefer additive changes to SKILL.md over rewrites. Each version of
  SKILL.md is load-bearing for runs that depend on its specific behavior.
- Production SKILL.md edits happen on `main` only after the experiment
  branch's findings justify them. Branch-based experimentation is the norm.
