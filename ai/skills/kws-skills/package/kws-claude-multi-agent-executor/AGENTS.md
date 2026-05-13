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

## File responsibilities (quick reference)

- **`SKILL.md`** — current skill behavior. The runtime reads this. Treat
  edits with care; any change here can affect every future invocation.
- **`HISTORY.md`** — narrative history of versions + improvement areas.
  Update on every shipped version.
- **`DESIGN-v<X>.md`** — point-in-time design doc for that version. Frozen.
- **`references/`** — sub-agent prompt templates (Implementer, Reviewer,
  Verifier, Documenter, Plan Reviewer, etc.). Versioned together with
  SKILL.md.
- **`evals/`** — fixtures, harness, judge, baselines. Independent of SKILL.md
  changes — eval improvements ship orthogonally.
- **`docs/experiments/`** — institutional memory. One subdirectory per
  experiment. Read before starting related work; write as you do related work.

## When in doubt

- Ask first: does this need an experiment record? (If unsure, yes — it's
  cheap to create one and skip it later.)
- Prefer additive changes to SKILL.md over rewrites. Each version of
  SKILL.md is load-bearing for runs that depend on its specific behavior.
- Production SKILL.md edits happen on `main` only after the experiment
  branch's findings justify them. Branch-based experimentation is the norm.
