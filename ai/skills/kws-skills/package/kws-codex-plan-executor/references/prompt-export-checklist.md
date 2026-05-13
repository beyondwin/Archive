# Prompt Export Checklist

Before sending the generated prompt, confirm:

## Paths And Output

- plan path is present; workspace path is present when known; required local paths were checked for existence/readability
- no placeholder paths or template tokens such as `/absolute/path/to/plan.md`, `{{PLAN_PATH}}`, `{{OPTIONAL_DOCUMENT_BULLETS}}`, or `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` remain
- only readable real spec/design/extra document bullets are included; requested language and prompt-only output are respected
- if progress checkboxes/status in source-of-truth plan docs may be updated, the prompt tells agents to inspect and report those docs' tracked/untracked/dirty status and commit handling

## Model Routing

- non-delegable implementation/review/root-cause/verification interpretation/completion decisions stay on `gpt-5.5 high`
- conservative automatic Spark evidence packing is present unless forbidden or `gpt-5.5 only`, and is limited to `gpt-5.3-codex-spark high` for read-only commands/files selected by `gpt-5.5 high`
- conservative automatic Spark cannot choose source files, broaden exploration, infer root cause, review code, interpret verification, decide completion, edit files, or mutate repo/process state
- broader Spark scout mode appears only on explicit request, uses `gpt-5.3-codex-spark high`, and uses `templates/spark-scout-bullets.ko.txt` exactly for Korean output or a constraint-preserving translation
- other model routing outside conservative automatic Spark requires explicit model-specific exception; no-Spark or `gpt-5.5 only` removes every Spark route

## Execution Invariants

- task-by-task local implementation by default, subagent opt-in only, two-stage review, and Task 0/1 start handling are explicit
- per-task `TASK EXECUTION CONTRACT` is explicit with scope, files to inspect, allowed edits, forbidden edits, and acceptance command or honest substitute
- lightweight `.codex-orchestrator/state.json` ledger is explicit and includes workspace, plan, branch, worktree, current task/phase, task state, risk levels, issue keys, verification, session-owned resources, and last checkpoint
- task-level `low | mid | high` risk ledger is explicit, with same-file later tasks upgraded to at least `mid`
- broad tasks are handled by intra-task phases centered on one layer/module without expanding plan scope
- retry reviews or verification failures use stable `ISSUE_KEY=<file>:<line-or-symbol>:<category>` records and label repeated keys as `[RECURRING - previous fix did not address this]`
- repo-local instructions, isolated worktree, original workspace handling, unrelated-change handling, and scoped cleanup are explicit; broad process cleanup is forbidden
- session-owned process checks are scoped to ledger-recorded PID/session id/port/worktree path, not broad unrelated Node/Java/Playwright process lists
- Task/Phase checkpoints are semantically complete, delta-focused, limited, and use fixed fields for status, scope, files, contracts, verification, raw output, risk, next action, worktree/branch, and session-owned resources
- summaries and checkpoints preserve only restart-critical facts, not long logs or generic narration
- continue-to-end default is explicit
- continuation prompt is exception-only for user-blocking ambiguity, unresolved root-cause/verification failure, inability to reconstruct the next high-risk task safely, or clear context pressure

## Verification And Finish

- verification ladder is explicit: no full suite on every phase, targeted checks for implementation phases, broader checks for task completion/high-risk changes, final full check at the end
- targeted checks for test config, build input, test property, Dockerfile, migration, or generated-artifact input changes either bypass up-to-date/cache behavior or explicitly record cache behavior plus the broader verification that closes the risk
- ENV_BLOCKER triage is explicit: command runs at all, dependencies, path/config, and required service checks before reporting blocker
- verification failures preserve raw output by file path or short excerpt plus repro command, and same-root-cause fix retries are capped at 3 before an error/blocked checkpoint
- doc safety/link scans default to changed docs or added lines unless public release/scanner changes justify a full scan; existing false positives are separated from newly introduced risk
- final documentation impact check is explicit without requiring KWS-only review skills
- final summary includes doc update/no-impact reason, worktree/branch, finish-to-end status, and final verification

For failure analysis or substantial future edits, also inspect `references/common-mistakes.md`.
