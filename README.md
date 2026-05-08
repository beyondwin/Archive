# Archive

Archive is a personal knowledge and AI tooling repository. It keeps long-lived
documents, reusable AI-agent skills, shell runtime helpers, and dotfile
bootstrap configuration in one checkout.

## Layout

- `AGENTS.md` - repository instructions for coding agents.
- `ai/` - AI tooling runtime, dotfiles, skill source packages, and operating
  docs.
- `docs/` - source captures, curated notes, generated wiki navigation, and
  index metadata.
- `.chezmoiroot` - points chezmoi at `ai/dotfiles/chezmoi`.

## Working Rules

- Treat `docs/notes/` and `docs/raw/` as source material.
- Treat `docs/wiki/`, `docs/_graph/`, and `graphify-out/` as generated
  navigation layers.
- Keep `docs/_index/catalog.yml`, `docs/_index/topics.yml`, and
  `docs/INDEX.md` aligned when documents are moved or added.
- Edit AI skill source under `ai/skills/kws-skills/package/`.
- Edit shell runtime behavior under `ai/runtime/`.

## Git Hygiene

The repository tracks source files, curated documents, scripts, tests, and
lightweight README placeholders. It ignores local machine metadata, editor
state, dependency caches, local environment files, and generated navigation
outputs.

Generated Graphify output should stay in `graphify-out/` locally and be
refreshed with:

```bash
graphify update .
```

The generated docs wiki can be rebuilt locally, but only
`docs/wiki/README.md` is kept in Git as a placeholder.
