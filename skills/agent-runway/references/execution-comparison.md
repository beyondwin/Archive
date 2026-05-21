Source-of-truth: current eval output wins when this comparison and code disagree.

# Three-Skill Execution Comparison

Input used for the 2026-05-21 Trust Console comparison:

- `docs/superpowers/plans/2026-05-21-agentlens-agentrunway-trust-console.md`
- `docs/superpowers/specs/2026-05-21-agentlens-agentrunway-trust-console-design.md`

## AgentRunway

AgentRunway is the best fit for this plan format.

- Parses the fenced `yaml agentrunway-task` metadata.
- Preserves canonical task ids such as `task_001`.
- Preserves dependencies, risk, phase, `spec_refs`, file claims, and acceptance commands.
- Produces `contract.json`, `coverage.json`, `artifact_graph.json`, `events.jsonl`, and per-task packet files.
- Resolves bare numeric spec refs such as `6` and `10.1` into manifest ids such as `S1.6` and `S1.10.1`.

Improvement selected from this run: AgentRunway must emit raw AgentLens v2
event envelopes to the AgentLens run, not v2 envelopes nested inside a v1
payload wrapper. The emitter now targets the AgentLens container run id at the
envelope level while preserving the AgentRunway run id inside the payload.

## KWS Codex Plan Executor

KWS CPE remains useful for context budgeting and conservative execution
contracts, but it is weaker for AgentRunway-native plans.

- Parses the Markdown task headings and file blocks.
- Does not parse the fenced `agentrunway-task` metadata.
- Loses dependency edges, `spec_refs`, risk/phase, and acceptance commands.
- Falls back to broad full-spec packets for most tasks because it cannot map
  task metadata to spec sections.

Takeaway for AgentRunway: keep task-packet context budgets, but do not inherit
CPE's legacy `kws-cpe.*` AgentLens event namespace or metadata-blind parser.

## KWS Claude Multi-Agent Executor

KWS CME's spec-manifest script is useful as a lightweight cross-check.

- Builds a flat section map with `S1`, `S1.6`, `S1.6.3`, etc.
- Does not provide the full run/packet/evidence contract that AgentRunway now
  owns.
- Its process model still assumes the legacy CME orchestration namespace.

Takeaway for AgentRunway: reuse the manifest shape as a compatibility sanity
check, but keep AgentRunway as the only AgentLens executor integration.

## Decision

The optimal AgentRunway improvement is not another compatibility bridge. The
right direction is a stricter AgentRunway-only trust path:

- AgentRunway emits `agentlens.event.v2` raw envelopes.
- AgentLens accepts raw v2 envelopes and rejects legacy KWS event families.
- AgentLens materializes `agentrunway_projection.json` and `trust_report.json`.
- CLI/API/dashboard surfaces read the same `trust_report.json`.

This closes the main risk found by the three-skill comparison: AgentRunway had
the strongest planning contract, but AgentLens could not yet consume that
contract as first-class trust evidence.
