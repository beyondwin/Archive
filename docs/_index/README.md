# Docs Index Data

This folder contains index metadata used to keep Archive documents findable.

- `catalog.yml` is the source of truth for document metadata.
- `topics.yml` is the topic registry used to avoid duplicate or vague folders.
- `../INDEX.md` is the human-readable index derived from `catalog.yml`.

Use `$archive-docs-organizer` to update these files when sorting documents from
`docs/_inbox`.

Catalog paths usually point to human-curated documents under `docs/notes/`.
They may also point to `docs/_inbox/` while a document is still intentionally
unsorted, or to `docs/raw/` when an original capture is useful as a standalone
reference.

Generated wiki pages under `docs/wiki/` should not be cataloged as primary
sources. Executor-skill implementation records under
`skills/<skill>/docs/experiments/` are maintained from the skill docs, not this
library index, unless they are later promoted into curated notes.
