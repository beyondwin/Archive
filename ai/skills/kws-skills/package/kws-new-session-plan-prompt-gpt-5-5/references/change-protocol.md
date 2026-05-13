# Change Protocol

Use this before editing `kws-new-session-plan-prompt-gpt-5-5`.

## Goal

Improve the skill incrementally without losing history, weakening the generated
prompt contract, or bloating the runtime context.

## Edit Loop

1. Check `git status` and preserve unrelated work.
2. Read `SKILL.md`, `templates/fresh-session-prompt.txt`,
   `references/pre-send-checklist.md`, and this file.
3. If the change affects current behavior, also read `ARCHITECTURE.md`,
   `HISTORY.md`, and relevant `evals/fixtures/`.
4. Classify the change:
   - **Patch**: wording, examples, checklist clarification, or fixture-only
     update.
   - **Minor**: new invariant, model-routing change, output-shape change,
     verification rule, or new maintenance artifact.
   - **Experiment**: uncertain hypothesis, >=50 lines of behavioral prompt
     change, model-routing proposal, new evaluation method, expected cost above
     1 hour, or a change that could reasonably produce a negative result.
5. Add or update a pressure fixture before behavioral changes when possible.
6. Make the smallest coherent patch.
7. Run validation:
   - Skill metadata validation when available.
   - Package sync validation when package metadata changes.
   - Manual fixture check for every fixture touched or newly relevant.
8. Update records in the same change:
   - `HISTORY.md` for every behavior or maintenance-protocol change.
   - `ARCHITECTURE.md` when generation flow, routing, validation, or structure
     changes.
   - Package `manifest.json`, package `README.md`, and package `CHANGELOG.md`
     when the skill version changes.

## History Rules

- Record what changed and why, not a full diff.
- Preserve negative results in `docs/experiments/`; do not bury them in commit
  messages only.
- Keep `HISTORY.md` readable on two axes: chronological timeline and improvement
  area.
- Link experiment records from `HISTORY.md` Section 3 when an experiment opens
  or closes.

## Experiment Rules

Open `docs/experiments/<version>-<short-name>/` when any of these are true:

- The change has a hypothesis that may be wrong.
- The change introduces model routing beyond the existing conservative Spark
  evidence-packing rule.
- The change rewrites a core invariant block in the fresh-session template.
- The change requires a new scoring method or fixture design.
- The change is large enough that a future maintainer will need the reasoning,
  not just the final wording.

Use the template under `docs/experiments/_template/`. Update `JOURNAL.md` as
work happens, not only at close-out.

## Hard Guardrails

- Do not weaken the default `gpt-5.5 high` ownership of implementation, review,
  root-cause, verification interpretation, and completion decisions.
- Do not add broad Spark/model-routing exceptions unless the user explicitly
  asked for them or an experiment ships them with recorded evidence.
- Do not add low-risk main-agent implementation shortcuts unless the user
  explicitly requested lean/cost-optimized execution.
- Do not leave unresolved `{{...}}` template tokens in generated prompts.
- Do not put long rationale or experiment narrative into `SKILL.md`; use
  `references/`, `evals/`, or `docs/experiments/`.
- Do not update package metadata without aligning `SKILL.md` frontmatter and
  `manifest.json` `skill_versions`.
