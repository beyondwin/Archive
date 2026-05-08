## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

## Archive docs

Archive documents live under `docs/` with separate source, note, and generated
wiki layers.

Rules:
- Use `docs/_inbox/` only for unsorted intake.
- Preserve source captures in `docs/raw/` when original wording or provenance matters.
- Store human-curated documents in `docs/notes/<topic>/`; these are the primary library files.
- Treat `docs/wiki/` and `graphify-out/` as generated navigation layers, not as the source of truth.
- Keep `docs/_index/catalog.yml`, `docs/_index/topics.yml`, and `docs/INDEX.md` in sync when moving or adding documents.
- For important answers, verify claims against `docs/raw/` or `docs/notes/`, even if `docs/wiki/` or `graphify-out/GRAPH_REPORT.md` gives a fast route to the topic.
