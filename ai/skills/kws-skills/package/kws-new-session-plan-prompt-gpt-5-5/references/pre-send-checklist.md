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
- conservative automatic Spark evidence packing is present unless the user forbids Spark/model optimization or requests `gpt-5.5 only`
- conservative automatic Spark evidence packing is limited to `gpt-5.3-codex-spark high` for read-only commands/files selected by `gpt-5.5 high`
- conservative automatic Spark cannot choose relevant source files, broaden exploration, infer root cause, review code, interpret verification, make completion decisions, edit files, or mutate repo/process state
- when broader Spark scout mode is included, it uses `gpt-5.3-codex-spark high`
- when broader Spark scout mode is included, it uses `templates/spark-scout-bullets.ko.txt` exactly for Korean output or a constraint-preserving translation for another requested language
- broader Spark/model-usage optimization routing is absent unless the user explicitly requests it
- other model routing outside conservative automatic Spark evidence packing is allowed only when the user explicitly requests a model-specific exception
- first task wording covers both Task 0 and Task 1 plans
- per-task `TASK EXECUTION CONTRACT` is explicit with scope, files to inspect, allowed edits, forbidden edits, and acceptance command or honest substitute
- broad tasks are handled by intra-task phases centered on one layer/module without expanding plan scope
- repo-local instructions, isolated worktree, and original workspace handling are explicit
- per-task subagent cleanup and session-scoped resource cleanup by owner/PID/port are explicit
- broad process cleanup is forbidden
- semantically complete Task/Phase handoff checkpoints are explicit
- checkpoint length is constrained, delta-focused, and uses fixed fields for status, completed scope, changed files, confirmed contracts, verification, raw output, remaining risk, next action, worktree/branch, and session-owned resources
- summaries and checkpoints preserve only restart-critical facts, not long logs or generic narration
- continue-to-end default is explicit
- continuation prompt is exception-only for user-blocking ambiguity, unresolved root-cause/verification failure, inability to reconstruct the next high-risk task safely, or clear context pressure
- verification ladder is explicit: no full suite on every phase, targeted checks for implementation phases, broader checks for task completion/high-risk changes, final full check at the end
- verification failures preserve raw output by file path or short excerpt plus repro command
- same-root-cause fix retries are capped at 3 before an error/blocked checkpoint
- final documentation impact check is explicit without requiring KWS-only review skills
- final summary includes documentation updates when made, or a no-documentation-impact reason when docs stay unchanged
- final worktree/branch reporting is explicit
- finish-to-end requirement is explicit
- final verification requirement is explicit
- prompt-only requests return exactly one fenced `text` block and no lead-in
- no-Spark or `gpt-5.5 only` requests remove both conservative automatic Spark routing and broader Spark scout bullets

For failure analysis or substantial future edits, also inspect `references/common-mistakes.md`.
