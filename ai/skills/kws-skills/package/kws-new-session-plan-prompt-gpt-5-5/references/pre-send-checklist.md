# Pre-Send Checklist

Before sending the generated prompt, confirm:

- plan path is present
- workspace path is present when known
- required local paths were checked for existence/readability
- no placeholder paths or template tokens such as `/absolute/path/to/plan.md`, `{{PLAN_PATH}}`, `{{OPTIONAL_DOCUMENT_BULLETS}}`, or `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` remain
- only real spec/design/extra document bullets are included
- requested output language is respected, or template language is preserved when unspecified
- subagent-driven requirement is explicit
- quality-first model routing is explicit
- `gpt-5.5 high` required paths are explicit
- Spark/model-usage optimization routing is absent unless the user explicitly requests it
- when Spark scout mode is included, it uses `gpt-5.3-codex-spark high`
- when Spark scout mode is included, it uses the concrete replacement body from `SKILL.md`
- when Spark scout mode is included, it is limited to read-only exploration, read-only inspection commands, non-mutating verification commands selected by `gpt-5.5 high` plus raw output collection, file/resource inventory, and `HANDOFF CHECKPOINT` drafts
- when Spark scout mode is included, it forbids implementation direction, root-cause, review conclusions, verification interpretation, completion judgment, file edits, formatters, dependency installs, migrations, cleanup commands, service lifecycle commands, staging, commits, merges, pushes, PR creation, PR merge, release/version/changelog decisions, and other repository state mutations
- when Spark scout mode is included, it states Spark output is only input to `gpt-5.5 high`, and `gpt-5.5 high` must directly verify key files and conclusions
- when Spark scout mode is included, it says not to create Spark scouts for small tasks, obvious single-file edits, or fixes with confirmed root cause
- other model routing is allowed only when the user explicitly requests a model-specific exception
- first task wording covers both Task 0 and Task 1 plans
- repo-local instructions, isolated worktree, and original workspace handling are explicit
- per-task subagent cleanup and session-scoped resource cleanup by owner/PID/port are explicit
- broad process cleanup is forbidden
- semantically complete Task/Phase handoff checkpoints are explicit
- checkpoint wording does not imply the model can control system compaction
- checkpoint length is constrained and delta-focused
- continue-to-end default is explicit
- continuation prompt is exception-only for user-blocking ambiguity, unresolved root-cause/verification failure, inability to reconstruct the next high-risk task safely, or clear context pressure
- verification ladder is explicit: no full suite on every phase, targeted checks for implementation phases, broader checks for task completion/high-risk changes, final full check at the end
- final `$kws-doc-prompt-review` project documentation review/update is explicit, with `$kws-skill-prompt-review` used instead for Codex `SKILL.md` or skill bundle artifacts
- final summary includes documentation updates
- final worktree/branch reporting is explicit
- finish-to-end requirement is explicit
- final verification requirement is explicit
- prompt-only requests return exactly one fenced `text` block and no lead-in

## Common Mistakes

- Starting implementation in the current session instead of generating the prompt.
- Using vague document descriptions instead of absolute paths.
- Leaving placeholder bullets or placeholder paths in the generated prompt.
- Omitting repo-local instructions, worktree isolation, cleanup, or handoff checkpoint rules.
- Omitting quality-first routing and the default `gpt-5.5 high` requirement.
- Including Spark/model-usage optimization rules when the user did not explicitly request them.
- Letting Spark scout mode make implementation, review, root-cause, verification, completion, git mutation, PR, merge, or release decisions.
- Letting Spark scout mode run broad commands such as formatters, installers, migrations, cleanup commands, or service lifecycle commands.
- Re-synthesizing `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` instead of using the concrete replacement body from `SKILL.md`.
- Starting at Task 1 when the plan starts at Task 0.
- Allowing model exceptions the user did not explicitly request.
- Requiring subagent-driven execution but not task closure: implementation, review, fixes, verification, and agent cleanup.
- Encouraging broad cleanup such as `killall node`, `pkill node`, `killall chrome`, or `pkill playwright`.
- Writing compact rules as if the model can prevent system compaction.
- Emitting long repetitive checkpoints that consume context faster.
- Handing off mid-task, mid-review, or during failed-verification analysis.
- Splitting at non-semantic boundaries such as file reads or partial edits.
- Treating task count, area switches, file count, or log volume as automatic stop conditions instead of checkpoint-and-continue signals.
- Treating every context boundary as a full-test boundary, causing repeated full-suite runs for small phases.
- Skipping verification without recording why and where the next honest verification will happen.
- Omitting the final `$kws-doc-prompt-review` documentation update step, or failing to route Codex `SKILL.md` and skill bundle artifacts to `$kws-skill-prompt-review`.
- Using weak language such as "review and report" instead of task-by-task execution across continuation sessions.
- Adding explanation when the user asked for prompt-only output.
