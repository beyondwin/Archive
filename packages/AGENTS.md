# Packages Agent Instructions

- Filesystem JSON/JSONL files are the saved record; SQLite is rebuildable.
- Providers do not write Lens storage or SQLite directly.
- Event changes require contract, view, and consumer coverage.
- Changes spanning two or more `packages/*` use the offline closure gate.
