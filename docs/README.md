# Archive Docs

`docs/` is organized as a small knowledge system with separate layers for
intake, source material, curated notes, generated wiki pages, and metadata.

## Layout

- `_inbox/` - unclassified documents waiting to be sorted.
- `raw/` - immutable source captures such as copied articles, transcripts,
  exported PDFs converted to Markdown, or other reference material.
- `notes/` - human-curated documents organized by topic. This is the primary
  long-term library.
- `wiki/` - AI-maintained wiki pages compiled from `raw/` and `notes/`.
- `_index/` - catalog and topic metadata used to build `INDEX.md`.
- `_graph/` - notes about generated graph artifacts. Graphify's default runtime
  output remains `../graphify-out/`.

## Source Of Truth

Use this priority order when answers conflict:

1. Original material in `raw/`
2. Curated notes in `notes/`
3. Generated summaries and relationship maps in `wiki/` or `graphify-out/`

Generated wiki pages are useful for speed, but they are not the final authority.
Important claims should link back to a source file or curated note.

## Version Control

Track durable source documents, curated notes, and index metadata. Keep generated
navigation output local unless it is a lightweight placeholder:

- `docs/wiki/README.md` documents the generated wiki layer, but generated wiki
  pages are ignored.
- `docs/_graph/README.md` documents graph artifacts, but generated graph files
  are ignored.
- `graphify-out/` is a local generated knowledge graph and is ignored.

## Intake Workflow

1. Put new unsorted material in `_inbox/`.
2. Preserve source-heavy captures in `raw/` when the original wording matters.
3. Move polished or synthesized material into `notes/<topic>/`.
4. Update `_index/catalog.yml`, `_index/topics.yml`, and `INDEX.md`.
5. Regenerate `wiki/` or `graphify-out/` when enough material has changed.

## Graphify Workflow

Install or run Graphify with:

```bash
uvx --from graphifyy graphify --help
```

For Codex integration:

```bash
uvx --from graphifyy graphify codex install
```

Then run the Graphify skill against the docs corpus:

```text
/graphify docs
```

For deeper inferred relationships:

```text
/graphify docs --mode deep
```

Use generated graph files as an acceleration layer. Before answering important
questions, inspect the relevant files in `raw/` or `notes/`.
