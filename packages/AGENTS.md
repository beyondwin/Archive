# Packages Agent Instructions

- Filesystem JSON/JSONL artifacts are source of truth; SQLite is rebuildable.
- Providers do not write Lens storage or SQLite directly.
- Event changes require contract, projector, and consumer coverage.
- Changes spanning two or more `packages/*` use the offline closure gate.
