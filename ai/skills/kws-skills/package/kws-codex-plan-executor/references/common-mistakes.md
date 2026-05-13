# Common Mistakes

Use this for failure analysis or substantial edits to this skill.

- Do not let prompt export drift from runtime execution policy. If interactive
  mode uses `.codex-orchestrator/state.json` and subagent opt-in, prompt and
  handoff output must use the same source of truth and delegation boundary.
- Do not validate only field presence when a hard gate depends on a nested
  contract. The state validator should reject missing task contract fields.
- Do not classify dirty files before plan parsing. Dirty classification depends
  on declared task file blocks.
- Do not document a headless artifact path without creating its parent directory
  before shell redirection.
- Do not add a user-facing argument such as `headless_sandbox=read-only` without
  defining what happens when that argument conflicts with implementation edits.
- Do not let prompt export drift from execution-mode learning-log policy.
  Prompt and handoff generation do not log events themselves, but generated
  execution prompts must carry the same execution-only contract.
- Do not put learning events in the target repository. Use the user-local
  `~/.codex/learning/kws-codex-plan-executor/events.jsonl` path.
- Do not store secrets, full transcripts, long raw logs, or absolute home paths
  in learning events.
