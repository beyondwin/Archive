---
name: archive-docs-organizer
description: Organize the Archive repository's documentation inbox. Use when the user asks to sort, classify, clean up, or file documents placed in `docs/_inbox` or when they mention organizing unclassified Archive docs into topic folders under `docs/`.
metadata:
  version: "1.1.1"
  updated_at: "2026-04-30"
---

# Archive Docs Organizer

## Purpose

Organize unclassified documents from the Archive repository's `docs/_inbox`
folder into stable topic folders under `docs/`, then update the repository's
document index.

Use this as a curator workflow, not a blind file mover. Prefer a small number of
clear topic folders over a deep taxonomy.

Indexing model:

- `docs/_index/catalog.yml` is the source of truth for document metadata.
- `docs/_index/topics.yml` is the topic registry.
- `docs/INDEX.md` is the human-readable index derived from the catalog.

## Workflow

1. Confirm the workspace root and inspect `docs/`:
   - Run `pwd`, `find docs -maxdepth 3 -type d -print | sort`, and
     `find docs/_inbox -maxdepth 1 -type f -print | sort` when available.
   - Ignore `.DS_Store` and other OS/editor metadata.
2. Read existing index data:
   - `docs/_index/catalog.yml`
   - `docs/_index/topics.yml`
   - `docs/INDEX.md`
   - If these files do not exist, create them.
3. Read each inbox document enough to identify:
   - primary topic
   - document type
   - intended future use
   - whether it is source material, a polished note, a plan, or mixed content
4. Choose a destination:
   - Reuse an existing `docs/` folder when it clearly fits.
   - Create a new top-level topic folder only when no existing folder fits.
   - Keep mixed, unclear, or source-heavy material in `docs/_inbox` if moving it
     would make retrieval worse.
5. Rename files only when the new name improves scanning:
   - Use lowercase kebab-case for English filenames.
   - Preserve language suffixes such as `_kr` when useful.
   - Avoid clever or overly broad names.
6. Move files with normal filesystem commands after deciding the destination.
7. Update index data:
   - Add or update the document's `catalog.yml` entry.
   - Add a `topics.yml` entry only when a new stable topic is created.
   - Keep catalog entries sorted by topic, then title.
   - Rebuild `docs/INDEX.md` so it matches `catalog.yml`.
8. Update nearby README files when the move creates a new convention or topic
   folder that future documents should follow.
9. Summarize:
   - moved files and destinations
   - index updates
   - new folders created
   - files left in `_inbox` and why
   - any uncertain classifications

## Classification Guidelines

Use the document's main reuse case as the deciding factor.

- `docs/skills/`: Skill design, skill usage, Codex workflows, agent behavior,
  or reusable AI-agent procedures.
- `docs/superpowers/`: Existing Superpowers material, plans, specs, or related
  methodology already represented by the repository.
- New topic folders: Product notes, business research, app ideas, marketing,
  operations, reference material, or other recurring categories that do not fit
  existing folders.
- `docs/_inbox/`: Documents that need manual review, contain multiple unrelated
  topics, or should remain as raw source material.

## Catalog Schema

Each `docs/_index/catalog.yml` entry should use this shape:

```yaml
- title: Human-readable title
  path: docs/topic/file.md
  topic: topic/subtopic
  type: research-note
  language: ko
  status: organized
  summary: One concise sentence explaining why this document exists.
  source: https://example.com/original-source
  updated: 2026-04-29
```

Use `unknown` for `source` only when no source is available. Prefer these
statuses:

- `organized`: filed into a stable topic folder
- `inbox`: intentionally left in `docs/_inbox`
- `needs-review`: classification or metadata is uncertain

Prefer these types unless a document clearly needs another label:

- `research-note`
- `guide`
- `spec`
- `plan`
- `reference`
- `workflow`

## INDEX.md Format

Maintain `docs/INDEX.md` as a compact table:

```markdown
| Title | Topic | Type | Language | Status | Path |
|---|---|---|---|---|---|
| Example | topic/subtopic | research-note | ko | organized | [docs/topic/example.md](topic/example.md) |
```

Paths in `docs/INDEX.md` should be relative links from the `docs/` folder.

## Guardrails

- Do not reorganize outside `docs/` unless the user explicitly asks.
- Do not delete documents during organization.
- Do not rewrite document content unless asked; moving and light README updates
  are the default scope.
- Do not flatten meaningful existing structure.
- If a file has unrelated user edits or unclear ownership, preserve it and
  explain the uncertainty.
- Do not create vector databases or heavyweight search infrastructure until the
  user explicitly asks; `catalog.yml`, `INDEX.md`, and `rg` are the default.
