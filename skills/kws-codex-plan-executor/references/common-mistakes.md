# Common Mistakes

Use this for failure analysis or substantial edits to this skill.

- Do not let prompt export drift from runtime execution policy. If interactive
  mode uses `.codex-orchestrator/runs/<run_id>/state.json` and subagent opt-in,
  prompt and handoff output must use the same source of truth and delegation
  boundary.
- Do not validate only field presence when a hard gate depends on a nested
  contract. The state validator should reject missing task contract fields.
- Do not classify dirty files before plan parsing. Dirty classification depends
  on declared task file blocks.
- Do not treat `interactive` as permission to implement from `main` or the
  caller's original checkout. Execution modes require a dedicated
  non-conflicting `codex/...` git worktree before task contracts or edits.
- Do not start baseline verification in a fresh worktree before checking
  machine-local prerequisites such as Android `local.properties`, package
  manager install state, Docker daemon/memory availability, and intentional
  local `.env` absence. Report blockers or get explicit approval before
  copying ignored files.
- Do not turn Docker or Gradle resource failures into source-code changes
  without evidence. Check Docker OOM state, Gradle daemon disappearance causes,
  JVM/metaspace pressure, and Kotlin daemon memory before root-causing a build
  failure as a compile error.
- Do not under-scope React Router lazy-route tasks. Route test harness helpers,
  async assertions, `hydrateFallbackElement`, and request shim timing may be
  legitimate allowed edits for lazy-route conversion, even when product
  behavior is intended to stay unchanged.
- Do not document a headless artifact path without creating its parent directory
  before shell redirection.
- Do not add a user-facing argument such as `headless_sandbox=read-only` without
  defining what happens when that argument conflicts with implementation edits.
- Do not let prompt export drift from execution-mode learning-log policy.
  Prompt and handoff generation do not log events themselves, but generated
  execution prompts must carry the same execution-only contract.
- Do not put learning events in the target repository. Use the user-local
  `~/.codex/learning/kws-codex-plan-executor/runs/<YYYY-MM-DD>/<run_id>/events.jsonl`
  path.
- Do not reuse a root `.codex-orchestrator/state.json` as the primary state for
  concurrent execution. Treat it only as a latest-state compatibility copy or
  pointer.
- Do not store secrets, full transcripts, long raw logs, or absolute home paths
  in learning events.
- Do not parse executable tasks, `Files` blocks, or dependency markers from
  fenced code, HTML comments, or indented code.
- Do not report `lifecycle_outcome=finished` without a passing
  `completion_audit` containing `prompt_to_artifact_checklist` and
  `verification_evidence`.
- Do not use `current_phase` as a substitute for terminal
  `lifecycle_outcome`.
- Do not let optional DAG metadata bypass per-task execution contracts.
- Do not store source snapshots outside
  `.codex-orchestrator/runs/<run_id>/context.json`.
