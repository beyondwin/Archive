# Architecture - kws-new-session-plan-prompt-gpt-5-5

Status: deprecated compatibility wrapper. New prompt export behavior lives in
`../kws-codex-plan-executor/` as `mode=prompt`.

How this skill works, top to bottom. Runtime instructions live in `SKILL.md`.
Version history lives in `HISTORY.md`.

---

## 1. What The Skill Does

The legacy skill now redirects prompt-generation work to
`kws-codex-plan-executor mode=prompt`.

Historically, it generated a paste-ready Codex prompt from a verified
implementation plan path and optional spec/design/extra document paths.

It does not execute the plan, edit the plan, or create a new plan. The output
contract is preserved through the new executor skill's prompt mode.

Primary inputs:

- Implementation plan path - required.
- Workspace path - explicit when provided, otherwise inferred conservatively.
- Optional spec/design/extra docs - included only when real and readable.
- User output intent - prompt-only, language, Spark/model constraints, or
  continuation context.

Primary output:

- A single fenced `text` block by default, with all template tokens replaced or
  optional sections removed.

## 2. Artifact Layout

```text
kws-new-session-plan-prompt-gpt-5-5/
  SKILL.md                         # trigger, workflow, stop rules
  templates/
    fresh-session-prompt.txt        # generated prompt body
    spark-scout-bullets.ko.txt      # opt-in broader Spark scout section
  references/
    pre-send-checklist.md           # mandatory final checklist
    common-mistakes.md              # failure catalog for substantial edits
    change-protocol.md              # maintainer edit/release protocol
  evals/
    README.md                       # pressure-scenario protocol
    fixtures/*.yaml                 # regression cases
  docs/experiments/                 # experiment records for uncertain changes
  HISTORY.md                        # skill-level timeline
  ARCHITECTURE.md                   # this file
```

## 3. Legacy Generation Flow

The active generation flow is now `kws-codex-plan-executor mode=prompt`.

Historical flow:

1. Collect explicit user paths and infer missing workspace only when one root is
   unambiguous.
2. Stop if the implementation plan path is missing or unreadable.
3. Verify local paths before placing them in the generated prompt.
4. Load `templates/fresh-session-prompt.txt`.
5. Fill required tokens:
   - `{{WORKSPACE_PATH}}`
   - `{{PLAN_PATH}}`
   - `{{OPTIONAL_DOCUMENT_BULLETS}}`
   - `{{OPTIONAL_SPARK_SCOUT_BULLETS}}`
6. Remove optional bullets with no verified path.
7. Apply user model constraints:
   - Keep conservative automatic Spark evidence packing by default.
   - Remove every Spark route for `gpt-5.5 only`, no Spark, or no model
     optimization requests.
   - Include broader Spark scout bullets only when explicitly requested.
8. Run `references/pre-send-checklist.md`.
9. Return one fenced `text` block unless the user asked for surrounding
   explanation.

## 4. Invariant Blocks In The Template

`templates/fresh-session-prompt.txt` carries the stable execution contract that
fresh sessions must receive:

- Repo-local instruction checks.
- Task 0/Task 1 start handling.
- Task-by-task execution to the end.
- Per-task execution contracts.
- `.codex-orchestrator/session.json` restart ledger.
- Task risk ledger and same-file LOW to MID upgrade.
- Fresh implementation subagents and two-stage `gpt-5.5 high` review.
- Recurring issue tracking via stable `ISSUE_KEY`.
- Worktree isolation and unrelated-change handling.
- Session-owned cleanup only.
- Structured checkpoints and continuation stop rules.
- Retry budget and raw-output preservation.
- ENV_BLOCKER triage.
- Risk-scaled, cache-aware verification.
- Documentation impact check.
- Final summary.

## 5. Model Routing Contract

Default quality route:

- Implementation judgment, file edits, reviews, root cause, verification
  interpretation, architecture/state/auth/persistence/shared-module judgment,
  and completion decisions stay on `gpt-5.5 high`.

Default Spark route:

- `gpt-5.3-codex-spark high` may be used only for conservative evidence packing
  when the user has not forbidden Spark/model optimization.
- Spark can run or summarize read-only commands/files selected by `gpt-5.5 high`.
- Spark cannot choose source files, broaden exploration, infer root cause,
  review code, interpret verification, decide completion, edit files, or mutate
  repo/process state.

Broader Spark scout routing is opt-in only and comes from
`templates/spark-scout-bullets.ko.txt` for Korean output.

## 6. Validation Surface

The pre-send checklist guards the generated prompt before delivery. It checks:

- Paths and output shape.
- Model routing.
- Execution invariants.
- Verification and finish criteria.

`references/common-mistakes.md` is loaded for substantial future edits or
failure analysis, not every prompt generation.

`evals/fixtures/` captures pressure scenarios. The suite is currently a manual
or review-assisted regression set, not a fully automated harness.

## 7. Maintenance And Release Protocol

Use `references/change-protocol.md` before editing this skill.

Update this file when any of these change:

| Topic | Update trigger |
|-------|----------------|
| Generation flow | Token replacement, optional section handling, path inference, output shape |
| Template invariants | Adding/removing a required execution block |
| Model routing | Any GPT-5.5/Spark/default routing semantics |
| Validation | Checklist, common mistakes, eval fixture structure |
| Maintenance structure | History, architecture, experiment, or eval protocol changes |

Do not update this file for typo-only edits or package metadata-only changes.
