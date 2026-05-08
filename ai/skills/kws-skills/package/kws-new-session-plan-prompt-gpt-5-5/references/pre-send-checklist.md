# Pre-Send Checklist

Before sending the generated prompt, confirm:

- plan path is present
- workspace path is present when known
- required local paths were checked for existence/readability
- no placeholder paths or template tokens such as `/absolute/path/to/plan.md`, `{{PLAN_PATH}}`, `{{OPTIONAL_DOCUMENT_BULLETS}}`, or `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` remain
- only real spec/design/extra document bullets are included
- requested output language is respected, or template language is preserved when unspecified
- task-by-task subagent implementation is explicit
- two-stage review is explicit and not delegated solely to the implementation subagent's self-report
- quality-first model routing is explicit
- non-delegable implementation/review/root-cause/verification interpretation/completion decisions stay on `gpt-5.5 high`
- Spark/model-usage optimization routing is absent unless the user explicitly requests it
- when Spark scout mode is included, it uses `gpt-5.3-codex-spark high`
- when Spark scout mode is included, it uses `templates/spark-scout-bullets.ko.txt` exactly for Korean output or a constraint-preserving translation for another requested language
- other model routing is allowed only when the user explicitly requests a model-specific exception
- first task wording covers both Task 0 and Task 1 plans
- repo-local instructions, isolated worktree, and original workspace handling are explicit
- per-task subagent cleanup and session-scoped resource cleanup by owner/PID/port are explicit
- broad process cleanup is forbidden
- semantically complete Task/Phase handoff checkpoints are explicit
- checkpoint length is constrained and delta-focused
- continue-to-end default is explicit
- continuation prompt is exception-only for user-blocking ambiguity, unresolved root-cause/verification failure, inability to reconstruct the next high-risk task safely, or clear context pressure
- verification ladder is explicit: no full suite on every phase, targeted checks for implementation phases, broader checks for task completion/high-risk changes, final full check at the end
- final documentation impact check is explicit without requiring KWS-only review skills
- final summary includes documentation updates when made, or a no-documentation-impact reason when docs stay unchanged
- final worktree/branch reporting is explicit
- finish-to-end requirement is explicit
- final verification requirement is explicit
- prompt-only requests return exactly one fenced `text` block and no lead-in

For failure analysis or substantial future edits, also inspect `references/common-mistakes.md`.
