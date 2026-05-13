# Archive

Archive is a personal knowledge and AI tooling repository. It keeps long-lived
documents and reusable AI-agent executor skills in one checkout.

## Layout

- `AGENTS.md` - repository instructions for coding agents.
- `docs/` - source captures, curated notes, generated wiki navigation, and
  index metadata.
- `docs/superpowers/` - working implementation plans and design specs for
  skill work. These are project artifacts, not the curated library index.
- `skills/` - source of truth for the personal executor skills installed into
  Claude Code and Codex through symlinks.
- `graphify-out/` - local generated knowledge graph output, ignored by Git.

## Working Rules

- Treat `docs/notes/` and `docs/raw/` as source material.
- Treat `docs/wiki/`, `docs/_graph/`, and `graphify-out/` as generated
  navigation layers.
- Keep `docs/_index/catalog.yml`, `docs/_index/topics.yml`, and
  `docs/INDEX.md` aligned when documents are moved or added.
- Edit AI skill source under `skills/<skill-name>/`.
- Do not treat working implementation plans under `docs/superpowers/` as
  source code. Update current runtime docs instead unless the plan itself is
  being corrected as a record.

## Git Hygiene

The repository tracks source files, curated documents, scripts, tests, and
lightweight README placeholders. It ignores local machine metadata, editor
state, dependency caches, local environment files, and generated navigation
outputs.

Generated Graphify output should stay in `graphify-out/` locally and be
refreshed after code changes with:

```bash
graphify update .
```

The generated docs wiki can be rebuilt locally, but only
`docs/wiki/README.md` is kept in Git as a placeholder.
