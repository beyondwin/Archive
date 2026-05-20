Source-of-truth: the design document wins when this reference and code disagree.

# Protocol

Host session invokes `scripts/agentrunway.py`, reports status, and does not orchestrate workers from conversation context.

Runner owns SQLite, packets, worktrees, scheduling, AgentLens emission, merge decisions, and lifecycle state.

Worker receives one task packet, edits only claimed files, and returns a bounded result artifact.

## Superpowers Contract Preflight

AgentRunway consumes Superpowers design and implementation plan documents. It
does not generate them. Before dispatch, the runner writes immutable
`contract.json` with:

- spec path and canonical hash
- plan path and canonical hash
- base commit and workspace id
- parsed task packets
- task `spec_refs`, file claims, dependencies, required skills, and acceptance commands
- adapter and model profile
- initial coverage summary

Preflight rejects missing `spec_refs`, empty acceptance commands, missing file
claims for implementation tasks, dirty source checkouts without explicit
allowance, and plans that cannot produce deterministic task packets.
