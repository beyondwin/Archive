# Waygent Lens Workbench v1 Design

Date: 2026-05-22
Status: Approved in brainstorming, pending written-spec review

## Goal

Waygent Lens should feel like a real operator product, not a pilot dashboard
that happens to render many projections. The first product-grade slice is a
Workbench that answers one operator question quickly:

```text
What happened in this Waygent run, what is blocked, what evidence proves it,
what actions are safe, and what should the AI repair assistant receive next?
```

This design turns the existing Lens projections into a single operator loop:

1. choose the run that needs attention;
2. show the current outcome and blocker before raw detail;
3. explain the causal execution path with typed timeline rows;
4. attach bounded evidence refs to every recommendation;
5. separate deterministic policy decisions from AI repair planning;
6. keep Waygent runtime and apply readiness as the execution authority.

The Workbench is product surface for operating Waygent. It is not a generic LLM
trace viewer, not a chat transcript browser, and not a second runtime.

## Current Context

The active Waygent path already has many of the needed pieces:

- filesystem JSON and JSONL artifacts are the source of truth;
- `waygent.run_state.v2` is the runtime state contract;
- Lens projections live in TypeScript under `packages/lens-projectors`;
- the read API already exposes trust, apply readiness, execution explanation,
  operational maturity, dogfood evidence, runtime cost, and provider readiness;
- the console already renders run lists, task timelines, event timelines,
  failure barriers, apply status, operational maturity, execution intelligence,
  and operational evidence.

The gap is product composition. Today an operator must mentally reconcile
multiple panels. The console can show useful facts, but it does not yet provide
one canonical answer for:

- primary blocker;
- secondary blockers;
- allowed actions;
- blocked actions;
- apply availability;
- AI repair handoff context;
- evidence refs that justify the answer.

That answer should be computed once and shared by Console, API, and CLI.

## Research Summary

The design was informed by a multi-agent review of coding-agent products,
AI observability dashboards, and usage-monitoring tools. The important lesson
is that Lens should combine operator workflow from coding-agent products with
evidence discipline from observability tools, while avoiding the weaknesses of
both categories.

### Coding-Agent Product Surfaces

OpenHands and opencode show the value of a task-first workspace with visible
status, terminal/file context, and action affordances. They are useful for
working inside an active coding session, but their center of gravity is
"operate the agent workspace," not "audit a completed or blocked runtime
artifact."

AgentPulse, Cogpit, Claude Deck, and similar Claude/Codex companion tools are
closer to Lens because they expose sessions, stuck states, activity timelines,
todo progress, file changes, usage, MCP/agent configuration, and dashboard
summaries. Their strongest patterns are:

- an inbox for sessions needing attention;
- a detail page with session outcome before raw logs;
- a timeline that groups agent activity into meaningful rows;
- side panels for stats, file changes, and AI assistance;
- compact status chips for blocked, active, completed, or stale work.

Lens should borrow the operator inbox and session detail shape, but it should
not become a generic session browser. Waygent already owns runtime state and
apply policy, so Lens should project authoritative execution evidence rather
than replay chat as the primary object.

### AI Observability Dashboards

Langfuse and Phoenix are strong at trace search, trace trees, selected-span
detail, and evidence-oriented inspection. Their strongest patterns are:

- left search/list, center trace/tree, right selected detail;
- durable event/span identifiers;
- fast drilldown from summary to raw evidence;
- detail drawers that avoid losing the trace context;
- clear distinction between high-level run metadata and raw payloads.

These are useful for Lens, especially the tree/detail relationship and raw
fallback discipline. The weakness is that span-first observability can feel
generic. A Waygent operator does not primarily need every span; they need the
runtime decision: what is blocked, why, and what action is allowed.

### Usage And Monitoring Tools

OpenUsage, ccusage-style tools, Claude usage monitors, and similar TUI/web
dashboards are strong at compact metrics: token usage, cost, model/provider
breakdown, active sessions, burn rate, and historical trends. These patterns
are useful as secondary evidence in Lens, especially for provider readiness and
runtime cost. They should not dominate the main Workbench because cost does
not explain whether a run is safe to apply.

### Product Decision

The best v1 direction is not "make Lens a trace dashboard." It is:

```text
Waygent Lens Workbench:
a run-recovery and apply-readiness product for operating Waygent with evidence.
```

The Workbench should use a three-zone layout:

1. Run Board: choose active, blocked, approval-needed, ready, or completed
   runs by operator urgency.
2. Operator Timeline: show typed runtime milestones rather than raw event
   noise.
3. Decision and Evidence Rail: show the primary blocker, allowed actions,
   blocked actions, AI handoff packet, verification evidence, checkpoint refs,
   and raw fallback.

## Design Principles

1. Outcome first. The top of the screen must answer the current state before
   asking the operator to inspect logs.
2. Evidence-addressable recommendations. Every decision must point to source
   state, events, artifact refs, or explicit missing evidence.
3. Deterministic policy before AI. Logic classifies known blockers and action
   permissions. AI can summarize, draft repair plans, or propose next steps,
   but it does not become the authority for apply or recovery eligibility.
4. One read model. Console, API, and CLI should read the same operator
   decision projection instead of recomputing presentation-specific answers.
5. Raw fallback stays available. Product polish must not hide JSONL, state,
   patches, verification output, or provider artifacts.
6. Lens does not mutate runtime state. Waygent remains responsible for
   scheduling, verification, recovery execution, apply, and state transitions.
7. Unknown is a valid product state. When evidence is incomplete or rules do
   not cover the case, the product should say so and block unsafe actions.

## Non-Goals

- Do not reintroduce the legacy Python AgentLens tree.
- Do not revive KWS CPE or KWS CME routing as the active Waygent model.
- Do not replace `waygent.run_state.v2` with event-derived readiness when v2
  state exists.
- Do not make Lens perform apply, resume, recovery, or source mutation.
- Do not allow an AI recommendation to override apply readiness or runtime
  policy.
- Do not make raw chat transcript replay the primary UX.
- Do not build a generic Langfuse/Phoenix clone.
- Do not require live provider calls for the default Workbench projection.
- Do not store secrets or full unbounded transcripts in the AI handoff packet.

## Product Surface

### Run Board

The left side of the Workbench is an operator inbox, not a flat run list. It
groups runs by urgency:

- `blocked`: finished or paused with a hard blocker;
- `needs_input`: waiting for human input, approval, or missing context;
- `needs_approval`: recovery or apply is possible but requires explicit
  approval;
- `running`: active execution with latest phase and elapsed time;
- `recovering`: retry or recovery path is in progress;
- `ready_to_apply`: all apply readiness gates pass;
- `done`: completed and no operator action is needed;
- `failed`: terminal failure with no deterministic recovery action.

Each run row should show:

- run id or short label;
- status;
- primary blocker or current phase;
- next allowed action;
- apply readiness;
- last evidence timestamp;
- confidence.

Sort order should be operator urgency first:

1. `blocked`, `needs_input`, and `needs_approval`;
2. `recovering` and active `running` work;
3. `ready_to_apply`;
4. `failed`;
5. `done`.

This is the main product shift from pilot to operator tool: the screen starts
with "what needs my attention" rather than "which run did I click last."

### Sticky Outcome Strip

The top of the detail view should remain visible while the operator scrolls.
It shows the compressed run answer:

- current status;
- primary blocker;
- next safe action;
- apply readiness;
- confidence;
- source-of-truth state path or ref;
- last updated time.

Example:

```text
Blocked by needs_rebase
Checkpoint patch dry-run failed against current source.
Next safe action: regenerate checkpoint from current source.
Apply: blocked until dry-run passes.
Confidence: deterministic.
```

This strip is not a replacement for evidence. It is an operator summary with
links into the timeline and evidence rail.

### Operator Timeline

The center pane should show typed runtime rows derived from events and state,
not raw JSONL by default. Rows should be virtualized or paged for large runs.

Initial row types:

- `safe_wave`: scheduling or safe-wave selection;
- `task_packet`: task assignment or packet creation;
- `provider_attempt`: provider invocation, model, adapter, and process status;
- `worker_result`: normalized worker output and artifact summary;
- `verification_result`: command status, failures, and evidence refs;
- `checkpoint`: manifest, patch, digest, and dry-run status;
- `review_finding`: code review or policy finding;
- `recovery_decision`: retry, resume, rebase, regenerate, or human escalation;
- `apply_readiness`: apply gate result and blocker reasons;
- `artifact_health`: missing, stale, oversized, or invalid artifacts;
- `provider_readiness`: adapter readiness, stderr summary, cost, or noise.

Each row should include:

- timestamp or sequence index;
- actor or subsystem;
- row type;
- short title;
- outcome;
- evidence refs;
- impacted task id when relevant;
- severity;
- row-specific metadata.

Clicking a row should update the right rail to the row evidence while keeping
the run-level decision visible.

### Decision And Evidence Rail

The right rail is the main product differentiator. It should make the current
decision auditable without forcing the operator to read raw logs.

Sections:

1. Operator Decision
   - status summary;
   - primary blocker;
   - secondary blockers;
   - allowed actions;
   - blocked actions;
   - confidence;
   - unknown reasons.

2. Evidence Packet
   - state refs;
   - event refs;
   - artifact refs;
   - verification refs;
   - checkpoint refs;
   - missing evidence;
   - redaction or truncation notes.

3. AI Repair Handoff
   - goal;
   - current blocker;
   - constraints;
   - allowed runtime actions;
   - blocked runtime actions;
   - bounded evidence refs;
   - raw fallback refs;
   - prompt-ready summary.

4. Raw Evidence
   - run state JSON;
   - event JSONL slices;
   - artifact previews;
   - patch/checkpoint refs;
   - command output refs.

The rail should never imply that AI has authority to apply or recover. It
should say what evidence and constraints an AI assistant may use to draft a
repair plan.

## Operator Decision Projection

Add a shared projection named `waygent.operator_decision.v1`. The projection
should be pure and rebuildable from existing state, events, and artifact refs.

Suggested TypeScript shape:

```ts
export type OperatorDecisionConfidence =
  | "deterministic"
  | "partial"
  | "unknown";

export type OperatorRunStatus =
  | "running"
  | "recovering"
  | "needs_input"
  | "needs_approval"
  | "blocked"
  | "ready_to_apply"
  | "done"
  | "failed";

export interface OperatorDecisionProjection {
  schema: "waygent.operator_decision.v1";
  run_id: string;
  generated_at: string;
  status_summary: OperatorStatusSummary;
  primary_blocker: OperatorBlocker | null;
  secondary_blockers: OperatorBlocker[];
  allowed_actions: OperatorAllowedAction[];
  blocked_actions: OperatorBlockedAction[];
  evidence_packet: OperatorEvidencePacket;
  ai_handoff: OperatorAiHandoff;
  confidence: OperatorDecisionConfidence;
  unknown_reasons: string[];
  source_projection_refs: OperatorSourceProjectionRefs;
}
```

The contract should live in `packages/contracts` if that package already owns
shared public shapes for Waygent surfaces. The pure projector should live in
`packages/lens-projectors`, then be consumed by API, Console, and CLI.

### Status Summary

`status_summary` should include:

- display status;
- canonical runtime status when available;
- active task counts;
- completed task counts;
- blocked task counts;
- latest phase;
- terminal outcome when present;
- apply readiness status;
- short human-readable summary.

The display status is a product classification. Runtime state remains the
source of truth for execution status.

### Blockers

Blockers should be structured:

```ts
export interface OperatorBlocker {
  code: string;
  title: string;
  summary: string;
  severity: "info" | "warning" | "blocking" | "critical";
  task_id?: string;
  evidence_refs: string[];
  missing_refs: string[];
  recommended_action_ids: string[];
}
```

Known v1 blocker codes:

- `state_missing`;
- `state_invalid`;
- `runtime_active`;
- `needs_user_input`;
- `needs_approval`;
- `verification_failed`;
- `checkpoint_missing`;
- `checkpoint_digest_mismatch`;
- `checkpoint_dry_run_failed`;
- `needs_rebase`;
- `apply_blocked`;
- `provider_not_ready`;
- `artifact_missing`;
- `artifact_stale`;
- `evidence_incomplete`;
- `unknown_failure`.

### Action Model

Actions are guidance, not execution. The UI can render an action button or
copyable command, but Waygent runtime policy must still approve the operation
when the command runs.

Suggested action ids:

- `inspect_run`;
- `explain_run`;
- `open_raw_evidence`;
- `open_ai_repair_handoff`;
- `request_user_input`;
- `approve_recovery`;
- `resume_run`;
- `regenerate_checkpoint`;
- `rebase_checkpoint`;
- `rerun_verification`;
- `review_patch`;
- `apply_run`.

Allowed actions should include:

- action id;
- label;
- reason;
- required evidence refs;
- command or API affordance when safe;
- whether user approval is required;
- whether runtime revalidation is required.

Blocked actions should include:

- action id;
- reason;
- blocking evidence refs;
- what would unblock it.

`apply_run` can only be shown as allowed when the existing apply readiness
projection is `ready`. Even then, the UI must treat the runtime apply command
as the authority and revalidate at execution time.

### Blocker Priority

When several blockers exist, choose one `primary_blocker` with a deterministic
priority order:

1. invalid, missing, or unsupported run state;
2. unsafe patch, digest mismatch, or apply safety blocker;
3. active runtime execution where mutation is not allowed;
4. required user input or approval;
5. failed verification;
6. checkpoint dry-run failure or source-basis conflict;
7. missing checkpoint or missing artifact;
8. incomplete evidence;
9. provider readiness or provider noise;
10. cost or latency warning.

All other blockers remain visible as `secondary_blockers`. This keeps the
operator answer simple without hiding the fuller situation.

### Evidence Packet

The evidence packet is the source of product trust. It should be bounded,
structured, and safe to show.

Fields:

- `state_refs`: paths or ids for runtime state;
- `event_refs`: event ids, sequence ranges, or JSONL refs;
- `artifact_refs`: patch, manifest, output, and provider artifact refs;
- `verification_refs`: command outputs and statuses;
- `checkpoint_refs`: manifest, patch, digest, and dry-run evidence;
- `projection_refs`: source projection names and versions;
- `missing_refs`: evidence expected but not found;
- `redaction_notes`: bounded notes about omitted secret-like or oversized
  content.

The packet should not embed full transcripts by default. It should provide refs
and short summaries that are enough for Console, API, CLI, and an AI repair
assistant to locate the right evidence.

### AI Repair Handoff

The AI handoff is a product object, not an authority object. It should be
generated only after deterministic policy classification.

Fields:

- `purpose`: for example `draft_repair_plan`, `summarize_blocker`, or
  `compare_recovery_options`;
- `prompt_summary`;
- `run_id`;
- `current_status`;
- `primary_blocker`;
- `secondary_blockers`;
- `allowed_action_ids`;
- `blocked_action_ids`;
- `constraints`;
- `evidence_refs`;
- `missing_evidence`;
- `raw_fallback_refs`;
- `safety_notes`.

The handoff should explicitly state:

```text
Do not apply patches, mutate source, resume execution, or override Waygent
runtime policy. Draft a repair plan or explanation using only the attached
evidence refs and constraints.
```

This answers the design concern from brainstorming: there are too many
situations for hand-written logic to produce every repair, but deterministic
logic is still valuable because it fixes authority, evidence, and safety
boundaries before AI reasons over the case.

## Data Flow

```text
filesystem state/events/artifacts
  -> existing Lens projections
     -> trust
     -> failure barriers
     -> apply readiness
     -> execution explanation
     -> operational maturity
     -> dogfood evidence
     -> runtime cost
     -> provider readiness
  -> operator decision projector
  -> API run detail
  -> Console Workbench
  -> CLI inspect/explain
```

Component boundaries:

- `packages/contracts`: shared `waygent.operator_decision.v1` shape if this
  matches current contract ownership.
- `packages/lens-projectors`: pure projector that composes existing
  projections and runtime state.
- `apps/api`: include `operator_decision` in run detail and optionally expose a
  focused endpoint if needed later.
- `apps/console`: render the Run Board, Outcome Strip, Operator Timeline, and
  Decision/Evidence Rail from the projection.
- `apps/cli`: surface the same primary blocker, allowed actions, blocked
  actions, and AI handoff summary in `inspect` or `explain`.
- Waygent runtime packages: remain authority for state transitions, resume,
  recovery, verification, and apply.

The console may transform the projection into UI model fields, but it should
not independently classify run safety.

## Console UX Detail

### First View

The first viewport should show:

- run board with urgent runs visible;
- selected run outcome strip;
- first timeline rows;
- decision rail above the fold.

The product should not open on an empty hero, marketing copy, or a large
decorative card. This is an operational tool, so density and scanability matter
more than visual drama.

### Layout

Recommended desktop layout:

- left: 280-340 px run board;
- center: flexible timeline with stable row height and search/filter;
- right: 360-440 px decision rail.

Recommended narrow layout:

- top segmented control for Runs, Timeline, Decision, Raw;
- sticky outcome strip above the active segment;
- action buttons remain visible, but raw evidence is one tap away.

### Timeline Controls

Timeline filters:

- all;
- blockers;
- verification;
- checkpoint;
- provider;
- apply;
- recovery;
- raw.

Search should match row title, task id, blocker code, artifact ref, event type,
and command name.

### Rail Controls

The rail should support:

- copy AI handoff;
- copy command;
- open raw evidence;
- jump to timeline row;
- open artifact ref;
- collapse low-severity secondary blockers.

Buttons should be derived from `allowed_actions` and `blocked_actions`.
Disabled actions should explain the blocker, not silently disappear.

## API And CLI Behavior

API run detail should include:

```json
{
  "operator_decision": {
    "schema": "waygent.operator_decision.v1",
    "run_id": "run_...",
    "status_summary": {},
    "primary_blocker": {},
    "secondary_blockers": [],
    "allowed_actions": [],
    "blocked_actions": [],
    "evidence_packet": {},
    "ai_handoff": {},
    "confidence": "deterministic",
    "unknown_reasons": [],
    "source_projection_refs": {}
  }
}
```

CLI `inspect` should show the same compressed answer:

```text
Operator decision: blocked
Primary blocker: needs_rebase
Apply: blocked
Next safe action: regenerate_checkpoint
Evidence: checkpoint dry-run ref, failed file list, run_state.v2 ref
AI handoff: available
```

CLI `explain` can include a longer narrative, but it should not invent a
different blocker or action set from the operator decision projection.

## Error Handling

### Projection Failure

If the operator decision projector fails to read or compose source projections:

- return `confidence: "unknown"`;
- set `primary_blocker.code` to `evidence_incomplete` or `state_invalid`;
- block apply and recovery guidance actions;
- expose raw state and event refs when available;
- include the projector error category without leaking secrets.

### Missing Evidence

If expected evidence is absent:

- include the missing ref in `evidence_packet.missing_refs`;
- keep the known evidence visible;
- lower confidence to `partial` or `unknown`;
- block actions that require the missing evidence;
- make the AI handoff say that the evidence is incomplete.

### Conflicting Signals

If state says one thing and events suggest another:

- prefer `waygent.run_state.v2` when present and valid;
- list event-derived disagreement as a secondary blocker or warning;
- include both source refs;
- avoid marking apply ready unless apply readiness agrees.

### Large Runs

Large runs should not make the Workbench unusable:

- timeline rows should be virtualized or paged;
- raw JSONL should load slices;
- search should work over indexed row summaries first;
- the decision rail should remain bounded.

### AI Handoff Failure

If handoff generation fails:

- keep deterministic operator decision visible;
- show `open_ai_repair_handoff` as blocked with a reason;
- allow `inspect_run`, `explain_run`, and raw evidence actions when safe.

### Apply Safety

The operator decision projection must never be the sole authority for apply.
Apply is allowed only when:

- existing apply readiness says ready;
- runtime apply command revalidates current state;
- source checkout and patch basis still pass runtime checks.

## Testing Strategy

### Projector Unit Tests

Add fixture-driven tests for:

- ready-to-apply run;
- verification failure;
- checkpoint dry-run conflict;
- missing checkpoint;
- missing state;
- invalid state;
- active running state;
- provider-not-ready warning;
- missing evidence with partial confidence;
- conflicting state and event signals.

Each fixture should assert:

- primary blocker;
- secondary blockers;
- allowed actions;
- blocked actions;
- confidence;
- required evidence refs;
- apply action eligibility.

### API Tests

API tests should assert that run detail includes `operator_decision` and that
the API does not recompute a different classification from the projector.

### CLI Tests

CLI tests should assert that `inspect` or `explain` reports the same primary
blocker, apply status, and next safe action as the projection.

### Console Tests

Console model/render tests should verify:

- urgent runs sort ahead of completed runs;
- sticky outcome strip receives projection values;
- disabled apply action shows the blocking reason;
- AI handoff panel renders incomplete-evidence warnings;
- raw evidence fallback remains reachable.

### Browser QA

After implementation, verify the local console in a browser at desktop and
mobile widths:

- first viewport shows run board, outcome, timeline, and decision rail;
- no text overlaps;
- long blocker names wrap cleanly;
- disabled actions remain readable;
- raw fallback opens without losing the run context.

## Acceptance Criteria

The v1 Workbench is accepted when:

1. A blocked run can be opened and the first viewport shows status, primary
   blocker, next safe action, apply readiness, and confidence.
2. The same primary blocker and action set are available through API and CLI.
3. Every allowed or blocked action includes evidence refs or missing-evidence
   reasons.
4. Apply is never shown as allowed unless existing apply readiness is ready.
5. The AI handoff packet can be copied or retrieved and contains bounded
   evidence refs, constraints, and blocked actions.
6. A projection failure degrades to an unknown or incomplete state instead of
   silently inventing readiness.
7. Raw JSONL/state/artifact fallback remains available.
8. Projector, API, CLI, and console tests cover the representative fixtures.
9. Browser QA confirms the Workbench reads as a cohesive product surface.

## Implementation Slices

This section is not the implementation plan. It defines the intended product
slice boundaries for the next planning step.

### Slice 1: Operator Decision Contract And Projector

Add `waygent.operator_decision.v1` types and pure projection logic. Keep the
first version conservative: known blockers, action permissions, evidence
packet, AI handoff, and confidence.

### Slice 2: API And CLI Parity

Expose the projection through run detail and make CLI `inspect` or `explain`
print the same decision summary.

### Slice 3: Console Workbench Composition

Refactor the console detail view around Run Board, Outcome Strip, Operator
Timeline, and Decision/Evidence Rail. Reuse existing projections as supporting
sections instead of leaving them as disconnected panels.

### Slice 4: Fixture And Browser Verification

Add blocked/ready/unknown fixtures and verify the Workbench in browser. Keep
visual polish practical and operator-focused.

## Source References

Reviewed source categories and representative projects:

- AgentPulse: <https://github.com/jstuart0/agentpulse>
- Cogpit: <https://github.com/gentritbiba/cogpit>
- Claude Deck: <https://github.com/adrirubio/claude-deck>
- OpenUsage: <https://github.com/janekbaraniewski/openusage>
- Langfuse: <https://github.com/langfuse/langfuse>
- Phoenix: <https://github.com/Arize-ai/phoenix>
- OpenHands: <https://github.com/All-Hands-AI/OpenHands>
- opencode: <https://github.com/sst/opencode>
- AgentOps: <https://github.com/AgentOps-AI/agentops>
- Helicone: <https://github.com/Helicone/helicone>

The visual companion mockup created during brainstorming is local and
non-canonical:

```text
.superpowers/brainstorm/79423-1779419635/content/lens-workbench-product-v1.html
```

The committed source of truth for product direction is this design document.

## Spec Review Checklist

- No legacy Python AgentLens routing is introduced.
- No KWS CPE or KWS CME active routing is introduced.
- Waygent remains runtime and apply authority.
- Lens remains a projection and inspection layer.
- AI repair handoff is bounded and non-mutating.
- Console, API, and CLI share one operator decision projection.
- Unknown and incomplete evidence states are explicit.
- Tests cover safety and parity, not only rendering.
