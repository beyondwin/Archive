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
