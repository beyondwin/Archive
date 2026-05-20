Source-of-truth: the design document wins when this reference and code disagree.

# Context Policy

The runner stores snapshot metadata and packet hashes outside conversation context.

Host compaction and rotation are safe because replay state lives in SQLite and artifacts, not hidden chat state.
