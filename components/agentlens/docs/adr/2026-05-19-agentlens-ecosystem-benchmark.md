# AgentLens Ecosystem Benchmark and Adoption Strategy

| Field | Value |
|---|---|
| Date | 2026-05-19 |
| Status | Draft |
| Scope | AgentLens positioning, external-tool benchmark, feature adoption roadmap |
| Local baseline | `docs/contract.md`, `docs/security.md`, `docs/integrations.md`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`, `docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md` |

## 1. Executive Summary

The Claude Code / Codex session tooling ecosystem is already useful for reading logs, replaying sessions, tracking token spend, and browsing local JSONL files. AgentLens should not compete by becoming another raw transcript viewer. Its defensible position is stronger:

> AgentLens is the local, agent-agnostic run record and evaluation substrate: it imports or captures agent activity, normalizes it into a locked v1 contract, redacts aggressively by default, seals evidence with hashes, and evaluates whether the run actually deserves to be trusted.

The best outside ideas to adopt are not broad product surfaces. They are specific proven patterns:

- `ccusage`: usage/cost ledger and JSON-friendly reporting.
- `Cogpit`: one-screen operational awareness and activity visualization.
- `claude-replay`: transcript auto-detection, replay export, and share-safe redaction warnings.
- `codlogs`: large-session bounded scanning and sanitization reports.
- `CodexMonitor`: pragmatic Codex session discovery and title heuristics.
- `codex-sessions` / `codex-logs`: keyboard-first session discovery, fuzzy search, latest/tail/status UX.

AgentLens should copy these patterns only where they reinforce its core promise: reliable capture, safe storage, deterministic evaluation, evidence-linked inspection, and stable machine-readable outputs.

## 2. Local AgentLens Baseline

Current AgentLens design already has a sharper trust model than most viewer tools:

- Canonical artifacts live under `~/.agentlens/runs/<workspace_id>/<run_id>/`.
- The source of truth is JSON on disk: `run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`.
- SQLite is only a rebuildable index.
- Writers redact before persistence and validate against JSON Schema.
- Full prompts and full command output are not stored by default.
- `manifest.json` seals files with sha256 hashes in `pre_eval` and `final` phases.
- The evaluator emits structured failures such as `MISSING_VERIFICATION_EVIDENCE`, `UNACKNOWLEDGED_FAILED_COMMAND`, `SUCCESS_WITH_RESIDUAL_RISK`, `ARTIFACT_HASH_MISMATCH`, and `RECORDING_INCOMPLETE`.
- Query commands promise stable `--format json` output and no absolute path leakage.

This means AgentLens should remain an evidence/evaluation layer first. Any viewer, dashboard, importer, or usage feature should serve that model.

## 3. External Ecosystem Snapshot

External facts below were checked against public project READMEs on 2026-05-19.

| Tool | Primary strength | Relevant source |
|---|---|---|
| `ccusage` | Daily/monthly/session token and cost reporting across Claude Code, Codex, OpenCode, Amp, and pi-agent; JSON output, model breakdown, cache-token accounting. | [ryoppippi/ccusage](https://github.com/ryoppippi/ccusage) |
| `Cogpit` | Real-time dashboard for Claude Code and Codex sessions; live monitoring, timeline, token analytics, file changes, tool-call visualization. | [gentritbiba/cogpit](https://github.com/gentritbiba/cogpit) |
| `claude-replay` | Converts Claude Code, Cursor, Codex CLI, Gemini CLI, and OpenCode logs into self-contained HTML replays; auto-detects formats; supports redaction and live watch. | [es617/claude-replay](https://github.com/es617/claude-replay) |
| `codlogs` | Searches, exports, and sanitizes local Codex sessions; handles large sessions with bounded scanning and partial/skipped states. | [tobitege/codlogs](https://github.com/tobitege/codlogs) |
| `CodexMonitor` | Lists, shows, and watches local Codex sessions; understands `CODEX_HOME`; has practical title heuristics from first user message. | [Cocoanetics/CodexMonitor](https://github.com/Cocoanetics/CodexMonitor) |
| `codex-sessions` | Cross-platform TUI with fuzzy session search, keyboard navigation, and quick resume / print-id behavior. | [Uri2001/codex-sessions](https://github.com/Uri2001/codex-sessions) |
| `codex-logs` | Lightweight shell UX: `list`, `latest`, `tail`, `status`, fzf selection, previews, git context. | [wondercoms/codex-logs](https://github.com/wondercoms/codex-logs) |

## 4. Strategic Positioning

### 4.1 What AgentLens Should Be

AgentLens should be:

- A stable local run ledger for agent work.
- A privacy-preserving normalized record of agent activity.
- A deterministic evaluator that separates "agent said it succeeded" from "the evidence supports success."
- A source of machine-readable records for dashboards, audits, and downstream tooling.
- A bridge between raw vendor session formats and a durable agent-agnostic contract.

### 4.2 What AgentLens Should Not Become

AgentLens should not become:

- A full interactive agent control center.
- A replacement for Claude Code, Codex, or their session resume flows.
- A worktree, PR, or undo/redo manager.
- A raw full-transcript archive by default.
- A tool that rewrites vendor session files or mutates Codex/Claude state as part of normal operation.

The strong line is important. Cogpit-style controls, branch/undo, and live chat are valuable in that product category, but they would blur AgentLens's read-only audit/evaluation posture.

## 5. Feature Patterns Worth Adopting

### 5.1 Robust Session Importers

Source inspiration: `claude-replay`, `codlogs`, `CodexMonitor`.

AgentLens v1 should prioritize importers before dashboard polish:

- `agentlens import claude-session`
- `agentlens import codex-session`

The importer should treat raw session JSONL as an input artifact, not the canonical model. The expected output is:

```text
~/.agentlens/runs/<workspace_id>/<run_id>/
  run.json
  events.jsonl
  final.json
  eval.json
  manifest.json
  artifacts/transcripts/<source-session-id>.jsonl
```

Importer requirements:

- Locate active and archived sessions under the standard tool paths.
- Support explicit path, latest, id, since, and all modes.
- Parse line-by-line rather than loading the whole transcript into memory.
- Preserve original transcript order when copied into artifacts.
- Generate `run.json` with `recording.has_transcript=true` and a source-specific `input.import_key`.
- Map vendor events to namespaced AgentLens events such as `claude.tool_use`, `codex.tool_use`, `codex.message`, `codex.reasoning`, while preserving only safe summaries in canonical events.
- Never store full prompt/output in canonical `events.jsonl`.
- Keep full imported transcript under `artifacts/transcripts/`, manifest-covered and retention-managed.
- Make imports idempotent by scanning `input.import_key`.

Implementation mapping:

| Concern | AgentLens module |
|---|---|
| Codex session discovery | `src/agentlens/store/codex_session.py` |
| Claude session discovery | `src/agentlens/store/claude_session.py` |
| Import commands | `src/agentlens/commands/import_codex_session.py`, `src/agentlens/commands/import_claude_session.py` |
| Event appending | `src/agentlens/store/writer.py::append_event` |
| Artifact manifest | `src/agentlens/store/manifest.py` |
| Idempotency lookup | `src/agentlens/store/query.py` or a rebuildable import index |

### 5.2 Large-Session Safety

Source inspiration: `codlogs`.

Large Codex rollouts can be unwieldy. AgentLens should adopt explicit analysis states:

- `full`: all lines parsed within configured limits.
- `partial`: file parsed until bounded limit, oversized row, unsupported event, or timeout.
- `skipped`: file too large for automatic deep parse; transcript can still be copied as an artifact.

Recommended importer behavior:

- Probe file size before parsing.
- Stream JSONL line-by-line.
- Cap maximum bytes read for automatic deep parse.
- Treat a malformed or oversized line as partial analysis, not total import failure.
- Emit a structured `import_report` artifact or field with counts:
  - total lines scanned
  - parsed lines
  - skipped lines
  - unsupported event types
  - oversized row count
  - first error location
  - whether transcript artifact was copied

This preserves AgentLens's non-blocking philosophy: the user gets a run record even when the source transcript is imperfect.

### 5.3 Usage and Cost Ledger

Source inspiration: `ccusage`, `Cogpit`.

Usage/cost should be added, but not as the central truth model. It should be a derived summary attached to a run:

```json
{
  "input_tokens": 0,
  "output_tokens": 0,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 0,
  "reasoning_tokens": 0,
  "model_breakdown": [],
  "cost_usd": null,
  "pricing_source": "cached|bundled|unknown",
  "confidence": "exact|estimated|unknown"
}
```

Design constraints:

- Token accounting must be optional and additive.
- If source logs do not contain trustworthy token fields, report `confidence="unknown"` rather than guessing silently.
- Pricing data should be cacheable and versioned.
- `eval.json` should not fail because pricing is missing.
- Query output should expose usage in `latest`, `show`, and dashboard endpoints only when present.

Best home:

- v1.x: additive `usage` block in query projection, derived from imported transcript artifacts.
- v2 candidate: dedicated `usage.json` if usage becomes central enough to require its own schema.

### 5.4 Evidence-Linked Dashboard

Source inspiration: `Cogpit`, `claude-replay`.

The AgentLens dashboard should not lead with "pretty transcript replay." It should lead with the trust split:

```text
Agent outcome: success
AgentLens eval: failed
Reason: MISSING_VERIFICATION_EVIDENCE
Evidence: command.started without passing verification, failed command unresolved, manifest not sealed, etc.
```

Dashboard v1 should emphasize:

- Runs list with `agent_outcome`, `eval_status`, `sealed_phase`, `recording_incomplete`, duration, workspace, agent, usage if available.
- False-success highlighting: `agent_outcome=success|unknown` and `eval_status=failed|incomplete`.
- Run detail with failures first, not transcript first.
- Evidence links into the event timeline and transcript artifact.
- Manifest integrity panel: sealed phase, file count, hash mismatch status.
- Redaction badge: full prompts not stored, full output excerpted, paths/secrets masked.

Transcript replay can be secondary. It is useful when investigating a failure, but it is not AgentLens's differentiator.

### 5.5 Shareable Export

Source inspiration: `claude-replay`.

AgentLens should eventually support shareable run reports, but with a stricter privacy model than replay tools:

- Default export should contain `run.json`, `final.json`, `eval.json`, selected `events.jsonl` excerpts, manifest summary, and failure evidence.
- Full transcript artifact export should require an explicit flag.
- Export should include a redaction report and warning if transcript artifacts are embedded.
- HTML export should be self-contained for bug reports and PR reviews.

Possible command:

```bash
agentlens export --run <id> --format html --safe
agentlens export --run <id> --format html --include-transcript
```

Default mode should be `--safe`.

### 5.6 Title and Session Discovery Heuristics

Source inspiration: `CodexMonitor`, `codex-logs`, `codex-sessions`.

AgentLens needs readable titles without storing sensitive full prompts. Good heuristics:

- Prefer explicit title metadata when present.
- Otherwise use the first user message excerpt after stripping:
  - AGENTS / system instruction blocks
  - environment context
  - absolute file paths
  - control characters
  - very long code blocks
- Cap title length.
- Store only the redacted title or title hash in canonical run metadata.

This should be implemented as a pure function with fixtures from Codex and Claude sessions.

### 5.7 Keyboard-First Query UX

Source inspiration: `codex-sessions`, `codex-logs`.

AgentLens already has query commands. A future TUI should stay read-only:

```bash
agentlens sessions
agentlens sessions --agent codex_cli
agentlens sessions --failed
agentlens sessions --print-run-id
```

Useful interactions:

- fuzzy search by run id, workspace, title, failure category, agent
- enter opens `agentlens show <run_id>`
- key to copy/print run id
- key to open dashboard route
- no deletion in v1 TUI; keep destructive GC in explicit CLI commands

## 6. What Not to Copy

| External pattern | Why not copy into AgentLens core |
|---|---|
| Interactive chat with running agents | Breaks read-only audit posture and expands security surface. |
| Undo/redo of file operations | Turns AgentLens into an execution controller, not a recorder/evaluator. |
| Mutating Codex `session_index.jsonl` | Risks corrupting vendor state and conflicts with source-of-truth separation. |
| Default full transcript export | Violates AgentLens's privacy-first posture. |
| Aggressive blob stripping as canonical import | Can destroy evidence; make it a derived sanitized copy only. |
| Deleting vendor sessions from TUI | Too risky for v1. AgentLens GC should manage only AgentLens-owned store. |
| Cost guesses without source confidence | Makes financial reporting look more precise than the data supports. |

## 7. Proposed Roadmap

### Phase A: Importer Hardening

Goal: make AgentLens useful for existing Claude/Codex history.

Deliverables:

- `store/claude_session.py`
- `store/codex_session.py`
- `import claude-session`
- `import codex-session`
- line-by-line JSONL parser
- idempotency via `input.import_key`
- transcript artifact copy under `artifacts/transcripts/`
- import report for full/partial/skipped state
- fixtures for Codex CLI, Codex Desktop, archived sessions, subagent sessions, malformed rows, and oversized rows

Success criteria:

- Re-importing the same session is a no-op.
- A malformed row does not abort the whole import.
- Full raw transcript is never copied outside `artifacts/transcripts/`.
- Canonical `events.jsonl` contains only schema-valid events.
- `manifest.json` covers transcript artifacts.

### Phase B: Usage Summary

Goal: let users answer "what did this run cost?" without leaving AgentLens.

Deliverables:

- usage extractor for Claude and Codex imported sessions
- model/cost summary with confidence level
- `agentlens show --latest --format json` additive usage fields
- dashboard usage column
- tests with exact, estimated, and unknown usage sources

Success criteria:

- Unknown pricing does not fail evaluation.
- Usage summaries can be regenerated from artifacts.
- Query shape remains backward-compatible.

### Phase C: Dashboard Trust View

Goal: make false-success and residual-risk runs visually obvious.

Deliverables:

- runs list
- run detail
- failure panel
- manifest integrity panel
- event timeline
- transcript artifact link
- empty/demo state

Success criteria:

- A user can identify a false-success run in under 10 seconds.
- Failure rows link to concrete evidence.
- Dashboard uses query facade only; no direct file IO from web routes.

### Phase D: Safe Export

Goal: produce shareable evidence without leaking raw transcripts by default.

Deliverables:

- `agentlens export --format html --safe`
- optional `--include-transcript`
- redaction report
- manifest digest summary

Success criteria:

- Safe export contains enough evidence for PR review or bug reports.
- Full transcript export requires explicit opt-in.
- Export output is self-contained.

### Phase E: Read-Only TUI

Goal: give terminal users fast local navigation.

Deliverables:

- `agentlens sessions`
- fuzzy search
- filters by status/agent/failure category
- print run id
- open dashboard route

Success criteria:

- TUI never mutates AgentLens or vendor stores.
- Works against filesystem full-scan if SQLite is unavailable.

## 8. Schema and Contract Implications

AgentLens should keep the v1 core schema stable. Most ecosystem-inspired work should be additive:

- Add optional fields only.
- Prefer derived query projections for UI conveniences.
- Use artifacts for bulky transcripts, reports, exports, screenshots, and sanitized copies.
- Use `manifest.json` to cover every artifact.
- Keep `events.jsonl` as the normalized timeline, not a vendor transcript dump.

Likely v1 additive fields:

```text
run.json
  run_kind
  agent.label
  recording.has_transcript
  recording.transcript_source
  input.import_key

events.jsonl
  allow lower-case namespaced events:
    claude.*
    codex.*
    kws-cme.*
    kws-cpe.*

query projections
  display_title
  usage
  import_state
  artifact_counts
```

Avoid adding high-churn fields directly to locked schema unless they are needed by downstream tooling. A derived query projection is safer than a contract field for UI-only values.

## 9. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Vendor transcript format changes | Importers break or silently misparse. | Pin parser fixtures by tool/version; fail partial with import report; keep raw transcript artifact. |
| Sensitive data in transcript artifacts | Local store becomes high-risk. | Do not export artifacts by default; manifest redaction notes; retention policy; explicit safe/sanitized export. |
| Large JSONL files slow the app | CLI/dashboard appears broken. | Bounded scanning, streaming parse, full/partial/skipped states. |
| Usage cost appears exact when estimated | User distrust or wrong financial decisions. | Add confidence field and pricing source. |
| Dashboard bypasses query facade | Multiple sources of truth. | Web routes call only `store.query`; test with SQLite missing/corrupt. |
| TUI deletes or mutates vendor state | Data loss. | Read-only TUI; GC only AgentLens-owned paths. |
| Feature creep into agent control center | Product position weakens. | Keep interactive control out of core; focus on audit/evaluation. |

## 10. Decision

Adopt the ecosystem's best local-session handling patterns, but keep AgentLens centered on trust:

1. Build robust importers first.
2. Add usage/cost as derived run metadata.
3. Build the dashboard around `agent_outcome` versus `eval_status`, not raw replay.
4. Add safe export later, with full transcript export as explicit opt-in.
5. Keep TUI/dashboard read-only.

This lets AgentLens coexist with `ccusage`, `Cogpit`, `claude-replay`, and Codex-specific browsers while owning a clearer niche: normalized, privacy-preserving, evidence-sealed agent run evaluation.

## 11. Concrete Backlog

| Priority | Item | Owner area |
|---|---|---|
| P0 | Implement streaming Codex JSONL discovery/parser with fixtures. | `store/codex_session.py` |
| P0 | Implement Claude session discovery/parser with fixtures. | `store/claude_session.py` |
| P0 | Add import commands and idempotency by `input.import_key`. | `commands/import_*_session.py` |
| P0 | Extend event schema for lower-case namespaced events. | `schema/jsonschema/event.schema.json` |
| P1 | Add import report artifact and partial/skipped states. | `store/*_session.py`, `artifacts/` |
| P1 | Add display-title extraction with redaction. | importer shared utility |
| P1 | Add usage extraction with confidence and pricing source. | new usage module |
| P1 | Surface usage/import state in query projections. | `store/query.py`, `commands/_format.py` |
| P2 | Dashboard false-success list and run detail. | `web/`, `commands/serve.py` |
| P2 | Safe HTML export. | `commands/export.py` |
| P3 | Read-only TUI. | `commands/sessions.py` |

## 12. References

- AgentLens local contract: `docs/contract.md`
- AgentLens local security model: `docs/security.md`
- AgentLens local integration levels: `docs/integrations.md`
- AgentLens dashboard design: `docs/spec/2026-05-19-agentlens-dashboard-design.md`
- AgentLens v1 unification plan: `docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`
- `ccusage`: <https://github.com/ryoppippi/ccusage>
- `Cogpit`: <https://github.com/gentritbiba/cogpit>
- `claude-replay`: <https://github.com/es617/claude-replay>
- `codlogs`: <https://github.com/tobitege/codlogs>
- `CodexMonitor`: <https://github.com/Cocoanetics/CodexMonitor>
- `codex-sessions`: <https://github.com/Uri2001/codex-sessions>
- `codex-logs`: <https://github.com/wondercoms/codex-logs>
