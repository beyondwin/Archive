# D001 — CPE local_fallback Adaptation for CME Guardrails

**Date**: 2026-07-07
**Status**: Decided

## Context

CPE (kws-codex-plan-executor) has a `local_fallback` dispatch mode meaning "do NOT
delegate — the MAIN agent implements this task directly with its full accumulated
context." This mode was produced by CPE's `preflight_dispatch.py` when:

- Subagents were turned off (`--requested-subagents=off`)
- The spawn-agent tool was unavailable
- The adaptive value gate judged the task too small/narrow to justify delegation
  (docs-only, small-scope, low parallel value)
- A risk marker required operator review but the main agent could handle it in context

CME's core guardrail is: **the orchestrator never writes code.** Every implementation
is done by a subagent dispatched to an isolated worktree. There is no
"main-agent-implements" path in CME.

When porting `preflight_dispatch.py` → `gate.preflight()` for CME v3.0 T11, we must
decide how to map each `local_fallback` trigger into CME's dispatch vocabulary:

- `"delegate_parallel"` — task dispatches to a subagent in its own parallel sub-worktree
- `"delegate_serial"` — task dispatches to a subagent run sequentially (same wave)
- `"block"` — task is not dispatched; orchestrator escalates to user

## Options considered

**Option A — Map all local_fallback triggers to delegate_serial (mechanical port)**

Every case where CPE said "do it locally" becomes "do it serially as a subagent."

- **Pros**: simple, preserves execution flow.
- **Cons**: conflates contention reasons (task is safe to delegate but must be
  serialized) with trust/risk reasons (task is NOT safe for unattended delegation
  at all). The core protection of local_fallback — "use the main agent's full
  accumulated context on ambiguous/risky work" — is lost silently, with no signal
  to the human.

**Option B — Map by WHY the trigger fired (this decision)**

Split into three categories based on the reason behind the local_fallback:

1. **Contention triggers** → `delegate_serial`
2. **Trust/risk triggers** → `block` → escalate_to_user
3. **Safety gates** → `block`

**Option C — Block all local_fallback triggers**

Treat every trigger as a block. Conservative but over-blocks; docs-only tasks,
small-scope tasks, and resource-key serializations are all safe to delegate.

## Analysis

CPE's local_fallback served two distinct purposes that Option A (mechanical mapping)
collapses:

**Purpose 1 — Contention / scheduling:** the task is safe to delegate, but must run
serially to avoid conflicts. Examples: two tasks claiming the same file within a
parallel wave, tasks sharing a `resource_key`, `serial: true` annotation. The main
agent had no particular advantage here — local_fallback was just "don't parallelize."
CME's equivalent is `delegate_serial`: still a subagent, still isolated, just not
concurrent with other tasks in the wave.

**Purpose 2 — Trust / risk / ambiguity:** the task requires the orchestrator's full
accumulated context that no isolated subagent has. Examples: task is ambiguous (`risk
markers`, operator review required), spec fallback was used but not reviewed, task is
genuinely too risky for unattended delegation. CPE relied on the main agent to handle
this in-context. CME has no such path. The conservative floor is `block → escalate`.

Silently mapping Purpose 2 triggers to `delegate_serial` launders a trust-gate into a
scheduling-gate. The human never learns that a risky task bypassed the operator-review
requirement — the subagent simply runs without the context it needed.

Option B preserves the protection:
- Contention triggers get `delegate_serial` — the faithful scheduling substitute.
- Trust/risk triggers get `block` — the honest signal that CME has no full-context path.
- Safety gates (write-scope overflow, packet red, file-claim collision) get `block` —
  unchanged from CPE, since CPE also blocked these.

## Decision

**Chosen: Option B — split by WHY the trigger fired.**

The three-way split is:

| Trigger category | CPE action | CME action | Rationale |
|---|---|---|---|
| File overlap in wave | local_fallback | delegate_serial | Serialization, not risk |
| Shared resource_key | local_fallback | delegate_serial | Serialization, not risk |
| serial: true annotation | local_fallback | delegate_serial | Explicit serialization |
| risk_markers on packet | local_fallback | block → escalate_to_user | No full-context fallback |
| spec_fallback not reviewed | local_fallback | block → escalate_to_user | No full-context fallback |
| Parallel file-claim collision | block | block | Safety gate — unchanged |
| Write scope too broad | block | block | Safety gate — unchanged |
| Packet context budget red | block | block | Safety gate — unchanged |

**Contention triggers — actual detection path (as of T11).** There are two distinct
mechanisms, and only one is wired today:

- *Cross-task file-claim collision within a parallel group* is detected via
  `state["parallel_file_claims"]` — this IS produced/consumed and is live.
- *Same-wave serialization* (file overlap / shared resource_key / `serial: true`) is
  meant to flow through `state["serialization_reason"]`. **This is NOT wired today.**
  `gate.partition_waves()` returns a bare `list[list[str]]` with no wave metadata, and
  no orchestrator step writes `serialization_reason` into per-task state. The explicit
  `serialization_reason`-driven branch in `preflight()` is therefore **dead code — a
  T15 seam** awaiting an orchestrator producer that annotates the `execution_plan`
  (per phase-0-setup.md Step 6, `"serialization_reason": "resource_key=<key>"`) and
  threads it into state.

  Until T15 wires that producer, same-wave contention tasks safely fall through to
  `preflight()`'s **DEFAULT `delegate_serial`** — the conservative floor. This is
  correct: a contention task that cannot be proven parallel-safe is serialized, which
  is exactly the intended behavior. The dead branch is an optimization/observability
  hook (it stamps a specific `serialized_by_<reason>` on the decision), not a
  correctness requirement.

  **Accepted `serialization_reason` vocabulary** (when T15 wires it): the bare category
  (`"file_contention"`, `"resource_key"`, `"serial_flag"`) OR the documented keyed form
  `"resource_key=<slug>"` (e.g. `"resource_key=db-port-5432"`, phase-0-setup.md Step 6).
  `preflight()` normalizes by taking the substring before the first `=` so a future
  producer emitting the keyed form does not silently miss the branch.

**Trust/risk triggers** are detected from packet fields: `packet["risk_markers"]`
(non-empty list) or `packet["spec"]["fallback_used"] == True` with
`packet["spec"]["mapping"]["operator_reviewed"] != True`.

**Safety gates** fire before the contention/trust split and always produce `block`.

The `preflight()` return dict includes a `"would_have"` key documenting what the
decision would have been without the blocking gate, for observability.

## Consequences

**What this enables:**
- Contention serialization is preserved and correct — file-overlap and resource_key
  tasks are serialized without false-positive escalation.
- Risk gates produce visible `block` decisions that the orchestrator surfaces to the
  human operator, preserving the trust protection CPE's local_fallback provided.
- The three-way split is encoded in `gate.preflight()` with explicit comments linking
  back to this ADR.

**What it blocks:**
- There is NO full-context fallback in CME. A `block` decision on a trust trigger means
  the task cannot proceed without human input. This is a deliberate, accepted loss.
  The alternative (silently delegating a risky/ambiguous task to an isolated subagent
  with no accumulated context) is worse than blocking.

**What it commits:**
- `gate.preflight()` must remain the single source of dispatch decisions. Orchestrators
  MUST NOT bypass preflight for any task.
- New `local_fallback` trigger types added in future CPE versions must be explicitly
  categorized (contention vs trust/risk vs safety) and mapped here before porting.

## What is LOST

CPE's `local_fallback` offered a graceful degradation: the main agent, with its full
accumulated conversation context, would implement the risky/ambiguous task. That
in-context implementation was genuinely better for ambiguous tasks than a fresh
isolated subagent would be.

CME has no equivalent. The floor for trust/risk triggers is `block → escalate_to_user`.
The human must either clarify the ambiguity, add operator_reviewed markers, or accept
the risk explicitly before the task can be dispatched. This is more disruptive than
CPE's silent local fallback, but it is honest about the capability gap.

## Open questions

- **T15**: `delegate_parallel` currently has no consumer in the sequential T9 cycle.
  The parallel sub-worktree launch path (SKILL.md Phase 1 Parallel Sub-Flow) will be
  wired in T15. Until then, `preflight()` can return `delegate_parallel` but no
  parallel launcher acts on it (seam comment in `gate.py`).
- Future: should small-scope / docs-only tasks (CPE's adaptive value gate) be routed
  to a "light subagent" mode rather than full `delegate_serial`? Deferred to post-T15
  when parallel dispatch is available and we can measure overhead.
