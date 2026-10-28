# AGENTS.md

This repo is an archive, not a product. There is no product to install or run.

## Rules

- Do not add an app, CLI, runtime, or `skills/` folder.
- Do not bring back the old product files. They stay in git history.
- Keep secrets and local junk out of git.
- When a fact in the docs changes, update the docs in the same change.
- Keep README.md, this file, and `docs/` saying the same thing.
- Keep shared instructions here; tool-specific files only link here.
- Keep the checkout small. Update the workflow's allowed file list when
  intentionally adding or moving an archive document or configuration file.
- Reply in Korean when the user writes Korean. Keep files in English.

## Where to look

- Docs: [docs/README.md](docs/README.md)
- Old files: [docs/history.md](docs/history.md)

## Check

GitHub runs the [archive check](.github/workflows/archive.yml) on every push
and pull request. It checks the allowed tracked files and local inline
Markdown file links. External URLs and heading anchors are not checked.
See the [repository guide](docs/README.md) for the check's scope.
