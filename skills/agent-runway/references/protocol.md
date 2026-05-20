Source-of-truth: the design document wins when this reference and code disagree.

# Protocol

Host session invokes `scripts/agentrunway.py`, reports status, and does not orchestrate workers from conversation context.

Runner owns SQLite, packets, worktrees, scheduling, AgentLens emission, merge decisions, and lifecycle state.

Worker receives one task packet, edits only claimed files, and returns a bounded result artifact.
