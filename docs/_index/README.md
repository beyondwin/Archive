# Docs Index Data

This folder contains index metadata used to keep Archive documents findable.

- `catalog.yml` is the source of truth for document metadata.
- `topics.yml` is the topic registry used to avoid duplicate or vague folders.
- `../INDEX.md` is the human-readable index derived from `catalog.yml`.

Use `$archive-docs-organizer` to update these files when sorting documents from
`docs/_inbox`.

Catalog paths should point to human-curated documents under `docs/notes/`.
External source captures can be indexed under `docs/raw/` when they are useful
as standalone references. Generated wiki pages under `docs/wiki/` should not be
cataloged as primary sources.
