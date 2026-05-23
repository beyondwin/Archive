# Waygent Hardening Roadmap

- **Date**: 2026-05-23
- **Type**: Program decomposition (not a single implementation design)
- **Status**: Approved (β decomposition)
- **Next artifact**: SP-1 brainstorming → spec → plan

## Why This Document

The session that landed the intake-recovery plan
(`2026-05-23-waygent-operator-workbench-intake-recovery-fixture-lab.md`)
ran seven multi-agent cycles before completing. Six of those cycles
were spent discovering Waygent failure modes that this document
catalogs, not implementing the planned product feature. The cumulative
cost was opus reasoning over re-dispatched task_1 through task_5
multiple times.

The point of this roadmap is not to relitigate that session. It is to
treat the failure modes as durable evidence and decompose the fix into
sub-projects sized for individual spec → plan → implementation cycles.

## Failure Modes Observed

| # | Theme | What broke | First-hit fix in session |
|---|---|---|---|
| A | Verify env isolation | `inherit_node_modules` makes worker worktree's `@waygent/*` invisible to integration tests; main's source is resolved instead. Cross-package work cannot be validly verified in isolation. | Manual cherry-pick (commit `dac3511`). Root not fixed. |
| B | apply / resume granularity | `waygent apply` is all-or-nothing. `waygent resume` is dry-run only at CLI. One blocked task forces a full re-run or chat-patch cherry-pick. | Operator cherry-picked task_1-4 checkpoints (commits `d80f27d` → `04a9ead`). Root not fixed. |
| C | Cross-path policy enforcement | A design statement that should bind multiple code paths (e.g., "recovered tasks emit risk=high") was implemented in one path (`deterministicRepair`) and silently violated in another (`planNormalizer.normalizeSuperpowersPlan`). | Three doc commits (`6203b52`, `c104107`) pinning the policy after each violation surfaced. |
| D | Host detection | `waygent run` hardcoded `provider=codex` regardless of host. Claude Code invocations routed opus models through the codex adapter and crashed on `--reasoning`. | CLI patch with `detectHost()` (commit `a69a95d`). |
| E | Telemetry oversensitivity / noise | `dangerous_output_command` hook regex matched JSON envelope prose. `lens.model_attestation_mismatch` fires every task on alias-only differences (`opus` vs `claude-opus-4-7`). Signal lost in noise. | Hook scoping fix (commit `cdaf0ad`). Alias normalization still backlog. |
| F | Coordinator-worker contract weakness | Plan code-block literals (`risk: "medium" as const`) had no documented prescriptive-vs-illustrative semantics. Workers silently chose between interpretations. Stale legacy tests were preserved by worker convention even when they contradicted the new design. | Operator chat-patched stale tests (commit `fabd86b`). Root not fixed. |

## Program Success Criteria

User priority ordering: **b > d > c > a**.

| Axis | Concrete measure |
|---|---|
| **b — design integrity** | The intake-recovery plan, re-authored under SP-1 conventions and rerun, completes in ≤2 multi-agent cycles (vs the observed 7). Zero silent worker drift events; any ambiguity is surfaced through `design_ambiguity_flagged` or `stale_test_candidates`. |
| **d — platform robustness** | Worker worktree's cross-package modifications are accurately reflected in verification, including integration tests. Host detection and provider routing are documented across Claude Code, Codex CLI, Codex app, and CI environments. |
| **c — operator separation** | A second operator can drive a Waygent multi-agent plan to apply-ready completion using only `waygent diagnose`, the documented `error_code` taxonomy, and the recovery playbook. No chat assistance from this codebase's primary developer required. |
| **a — operating cost** | Total multi-agent run cost (opus token usage) for a typical 6-task plan drops by ≥60% from the observed baseline. |

## Decomposition

Four sub-projects, each its own spec → plan → implementation cycle.

### SP-1: Design-Driven Implementation Contract

**Purpose** Eliminate the silent worker-drift failure mode by making
design statements precise, propagating them to every code path they
bind, and requiring workers to surface every ambiguity they resolve.

**In scope**

- Schema extensions:
  - design.md gains a *Cross-Path Invariants* section: policy statement
    + enumerated code paths it binds + symptom when violated.
  - plan task gains a *Compatibility Constraints* section: existing
    tests / behaviors that this task must not break, each tagged with
    the design sentence that justifies the constraint.
  - plan code blocks carry a `prescriptive: true|false` metadata flag.
    Prescriptive blocks must be copied verbatim; illustrative blocks
    may be adapted but must satisfy the invariant the design states.
- Worker output extensions:
  - `worker_result.evidence.design_ambiguity_flagged`: list of
    `{ascription, options_considered, chosen, evidence_for_choice,
    design_gap_suggested_text}` entries.
  - `worker_result.evidence.stale_test_candidates`: list of
    `{test_path, test_name, contradiction, recommended_action}`.
- Verification stage:
  - Test-failure summaries reference the design invariant violated, not
    only the stderr excerpt.
  - New deterministic stage: "design enumerated paths X exist and
    enforce policy P" before worker dispatch.

**Out of scope**

- SP-2: verify environment infrastructure.
- SP-3: host / telemetry / error_code.
- SP-4: apply / resume mechanics.

**Deliverables**

- design.md + plan.md schema documents.
- Worker prompt template addendum that teaches workers to populate the
  new envelope fields.
- `runway.worker_result.v2` schema (additive).
- Cross-path invariant detector module.
- Migration guide for existing plans.

**Success criteria**

- (Reproduction) Re-author the intake-recovery plan under the new
  conventions; re-run on a synthetic clean main. Run completes in ≤2
  multi-agent cycles.
- (Defense) Future ambiguity is reported via
  `design_ambiguity_flagged`, never silent.
- (Cost) Multi-agent run cost for that plan drops ≥70% vs the original
  session.

### SP-2: Verify Env Worktree-Awareness

**Purpose** Make verification accurately reflect worker worktree
changes, including integration tests that import `@waygent/*` packages.

**In scope**

- New verification strategy `isolated_workspace_resolve`:
  - Per-worktree resolution of `@waygent/*` workspace packages to the
    worktree's `packages/*`, not main's.
  - Implemented via either per-worktree `bun install` or selective
    symlink rewrite — strategy chosen empirically in SP-2's design.
- Strategy selection rule:
  - Integration tests in verify command set → `isolated_workspace_resolve`.
  - Unit-test-only verify → `inherit_node_modules` fast path retained.
- Surface isolation failures:
  - `runway.verification_environment` payload carries
    `{strategy, resolved_paths, isolated_packages, isolation_status}`.
  - `isolation_unavailable` is an explicit blocker, not a silent
    fall-through.
- Integration test author guidance (docs page).

**Out of scope** SP-1 contract, SP-3 hygiene, SP-4 apply.

**Deliverables**

- `packages/kernel-client` + `apps/cli` strategy dispatch.
- Verify env schema expansion.
- docs/operations/verification.md addition.

**Success criteria**

- (Reproduction) The task_5 fixture-lab test, replayed in a worker
  worktree that was branched before task_3's integration landed on main,
  reflects only the worktree's code. Whatever the worker wrote is what
  verify sees.
- (No regression) Unit-test-only verify time unchanged.
- (Operator surface) Isolation failures appear as `isolation_unavailable`
  in `runway.verification_environment`, not as wrong-resolution test
  failures.

### SP-3: Operator Hygiene

**Purpose** Clean the operator-facing surface so signal is not buried
in noise and so the system behaves identically across invocation
contexts.

**In scope**

- Model alias normalization. Canonical alias table; mismatch events
  fire only when normalized identifiers differ.
- Host detection extensibility: documented `WAYGENT_HOST` override,
  CI env signals (GITHUB_ACTIONS, CI=true), `waygent diagnose`
  subcommand.
- Error taxonomy + `error_code`: classified CLI errors emitted as JSON
  with `error_code` field. One-line action hint per code.
- Telemetry noise triage: every `lens.*` event audited for
  "always-fires-never-actionable" patterns; suppressed / debug-only /
  promoted to actionable.
- Hook library audit (light): purpose, evidence input, false-positive
  risks documented per hook; missing unit tests added.

**Out of scope** SP-1 contract, SP-2 verify env, SP-4 apply.

**Deliverables**

- Alias normalization module integrated into attestation event
  emission.
- `waygent diagnose` command.
- Error taxonomy doc + emission integration.
- Hook library README + audit notes.
- Triage results (the catalogue of suppressed / promoted events).

**Success criteria**

- (Noise floor) `model_attestation_mismatch` no longer fires on
  alias-only differences.
- (Debuggability) `waygent diagnose` output identifies a host or
  provider misconfiguration in under 30 seconds without reading code.
- (Operator clarity) Every CLI error carries `error_code` and an action
  hint.

### SP-4: Apply / Resume Granularity

**Purpose** When a run partially succeeds, give the operator targeted
recovery — apply the verified subset, retry only the failed task with
optional new context — instead of all-or-nothing.

**In scope**

- Partial apply:
  - `waygent apply --run <id> --up-to <task_id>`
  - `waygent apply --run <id> --only-verified`
  - Emit `apply_partial.applied_set` and `apply_partial.skipped_set`
    with per-task reasons.
- Per-task retry:
  - `waygent retry --run <id> --task <task_id> [--with-context <file>]`.
  - Worker input: prior `worker_result` + verification failure +
    operator context.
  - New attempt versioned (`attempt_n+1`); checkpoints regenerate;
    prior attempts retained as evidence.
- Resume actually resumes:
  - CLI's hardcoded `dry_run: true` removed; opt-in `--dry-run`.
- Operator context contract:
  - Context flows through the same hook gates as worker output.
  - Audit trail event `runway.operator_context_injected`.
- Apply readiness explanation: per-task readiness list instead of
  single `missing_apply_ready_evidence`.

**Out of scope** SP-1 contract, SP-2 verify, SP-3 hygiene.

**Deliverables**

- CLI subcommands and flags.
- Orchestrator per-task retry path.
- Apply state machine: partial apply support.
- Expanded payloads / new event types.
- Recovery playbook in docs/operations/waygent.md.

**Success criteria**

- (Recovery cost) The task_5 failure could have been recovered with
  `apply --up-to task_4` + `retry --task task_5 --with-context <hint>`.
  No full re-run, no chat-patch cherry-pick.
- (Audit trail) Every partial apply or retry emits durable events
  attributable to the operator.
- (Safe defaults) `waygent apply --run <id>` default behavior
  unchanged. Partial apply is explicit opt-in.

## Sequencing and Dependencies

```
SP-1  ──┬──→  SP-2  ──┐
        ├──→  SP-3    ├──→  SP-4
        └─────────────┘
```

- **SP-1 first.** Every later SP's own spec and plan is authored under
  the new contract, exercising SP-1 as its first regression case.
- **SP-2 before SP-4.** Per-task retry is only trustworthy when verify
  accurately isolates the worktree under test.
- **SP-3 before SP-4.** Per-task retry's operator context audit and
  partial-apply blocker enumeration rely on the `error_code` taxonomy
  and telemetry classification from SP-3.

After SP-1 lands, SP-2 and SP-3 are domain-independent and could run
in parallel if multiple operators are working. For single-operator
execution, the serial order keeps coordination overhead minimal.

## Out of Program

Items intentionally outside this roadmap, to keep scope bounded:

- New Waygent product features beyond fixing these failure modes.
- Additional provider integrations beyond Codex and Claude.
- Cross-host behavioral parity work beyond what host detection already
  covers.
- Workspace tooling rewrites (e.g., replacing bun) unless SP-2 finds it
  unavoidable.

## Risks and Mitigations

- **SP-1 ballooning into a full schema rewrite.** First SP-1 self-review
  must enforce a minimum-viable contract. Existing design / plan
  documents remain valid; new sections are additive.
- **SP-4 retry path touches scheduler, checkpoints, and audit
  simultaneously.** Per-task retry is exposed only as a new opt-in
  command (`waygent retry`). The current `waygent apply --run` behavior
  is unchanged so existing operator habits and automation continue to
  work.
- **SP-2 strategy change breaks unit-test fast path.** Default to
  `inherit_node_modules` for unit-test-only verify. Switch to
  `isolated_workspace_resolve` only when integration tests are part of
  the verify command set.

## Open Questions (Resolve Per-SP)

- **SP-1**: Is *Cross-Path Invariants* enforcement deterministic (a
  static check tool the worker must satisfy) or advisory (worker
  acknowledges, operator audits)? Both are possible; cost differs.
- **SP-1**: Schema versioning — accumulate optional new sections, or
  hard-cut to a new version?
- **SP-2**: Per-worktree `bun install` (10-30s overhead per worktree)
  vs selective symlink rewrite (faster but harder to keep in sync with
  workspace dep changes). Empirical decision.
- **SP-3**: `waygent diagnose` scope. Minimal
  (host / provider / model defaults / env signals) or full (also
  includes pending operator decisions, last failed run summary)?
- **SP-4**: Should `waygent retry` expose attempt-vs-attempt diffing
  (`attempt_1` vs `attempt_2`) directly, or defer to `waygent inspect`?

## Next Action

Start SP-1 brainstorming. This roadmap is the program's parent
artifact; each sub-project gets its own
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`,
`docs/superpowers/plans/YYYY-MM-DD-<topic>.md`, and multi-agent run.
