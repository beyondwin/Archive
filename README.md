# Archive

Archive is a personal knowledge and AI tooling repository. It keeps long-lived
documents and reusable AI-agent executor skills in one checkout.

## Layout

- `AGENTS.md` - repository instructions for coding agents.
- `docs/` - source captures, curated notes, generated wiki navigation, and
  index metadata.
- `skills/` - source of truth for the personal executor skills installed into
  Claude Code and Codex through symlinks. Durable skill implementation plans
  live under each skill's `docs/experiments/` directory.
- `graphify-out/` - local generated knowledge graph output, ignored by Git.

## Working Rules

- Treat `docs/notes/` and `docs/raw/` as source material.
- Treat `docs/wiki/`, `docs/_graph/`, and `graphify-out/` as generated
  navigation layers.
- Keep `docs/_index/catalog.yml`, `docs/_index/topics.yml`, and
  `docs/INDEX.md` aligned when documents are moved or added.
- Edit AI skill source under `skills/<skill-name>/`.
- Treat `skills/<skill-name>/docs/experiments/` as durable implementation
  records. Update current runtime docs instead unless an experiment record
  itself is being corrected.

## Git Hygiene

The repository tracks source files, curated documents, scripts, tests, and
lightweight README placeholders. It ignores local machine metadata, editor
state, dependency caches, local environment files, local agent runtime state
such as `.parallel/`, and generated navigation outputs.

Generated Graphify output should stay in `graphify-out/` locally and be
refreshed after code changes with:

```bash
graphify update .
```

The generated docs wiki can be rebuilt locally, but only
`docs/wiki/README.md` is kept in Git as a placeholder.

## AgentLens Dashboard

See `AgentLens/docs/dashboard.md`. Launch with:

```bash
agentlens serve --demo
```
