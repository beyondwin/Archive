# Waygent Skill

Waygent is the active product skill for running local agent executions. The
skill is intentionally thin: it maps natural language to `waygent` CLI commands
and lets the runtime own state, scheduling, providers, verification, AgentLens
events, resume, and apply.

KWS executor skills may remain in this repository, but they are outside the
Waygent product boundary.

## Common Commands

```bash
waygent run --latest
waygent run --plan docs/migration/example.md --provider fake
waygent status --last
waygent events --run run_example --json
waygent inspect --run run_example --json
waygent explain --last
waygent resume --last
waygent apply --run run_example
```
