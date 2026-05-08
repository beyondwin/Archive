# Archive Docs Organizer

Use `$archive-docs-organizer` when `docs/_inbox` contains unclassified
documents that should be sorted into `docs/raw/` or `docs/notes/`.

The skill should:

1. Inspect the existing `docs/` folder structure.
2. Read `docs/_index/catalog.yml` and `docs/_index/topics.yml`.
3. Read each inbox document enough to identify its main topic and reuse case.
4. Preserve source captures under `docs/raw/` when original wording or
   provenance matters.
5. Reuse existing `docs/notes/` folders and topics when they fit.
6. Create a new topic folder under `docs/notes/` only when no existing folder is
   appropriate.
7. Move documents out of `docs/_inbox` only when the classification is clear.
8. Update `docs/_index/catalog.yml`.
9. Update `docs/_index/topics.yml` when a new stable topic is created.
10. Regenerate or manually update `docs/INDEX.md` from the catalog.
11. Leave ambiguous or mixed-topic documents in `docs/_inbox`.
12. Treat `docs/wiki/` as generated navigation, not as a primary destination.
13. Summarize moved files, index updates, new folders, and uncertain cases.

Default command:

```text
Use $archive-docs-organizer to organize documents from docs/_inbox.
```

Indexing model:

- `docs/_index/catalog.yml` is the source of truth.
- `docs/INDEX.md` is the human-readable view.
- `docs/_index/topics.yml` prevents duplicated topic names and folder drift.
- `docs/raw/` preserves source material.
- `docs/notes/` stores the human-curated library.
- `docs/wiki/` stores AI-generated summaries and relationship pages only.
