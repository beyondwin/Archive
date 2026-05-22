# Waygent Operator Workbench v2, Intake Recovery, and Fixture-Lab Design

Date: 2026-05-23
Status: Approved in brainstorming, pending written-spec review

## Goal

Waygent should turn approved design and implementation documents into running
work without stopping on minor document-shape problems. When the user gives
Waygent a design/spec and a plan, the product intent is clear: implement the
work. Heading style, missing YAML, prose file claims, basename paths, or
slightly informal verification commands should not stop the run before work
starts.

This design combines three related improvements:

1. Operator Workbench v2: make the operator surface answer what is blocked,
   what is safe, what evidence proves it, and what command should run next.
2. Intake Recovery: add a lenient, evidence-recorded repair layer before
   deterministic preflight so recoverable plan/spec shape issues do not stop a
   run.
3. Fixture-Lab Regression Harness: capture bad-but-recoverable and truly
   unsafe cases as durable fixtures that test the full path from raw input to
   operator decision.

The product standard is:

```text
Given a design document and an implementation plan, Waygent starts the best safe
execution path automatically, records why it made each intake decision, and asks
the user only when the ambiguity is high-risk.
```

## Current Context

Recent Waygent work added runtime safeguards around plan preflight, spec
manifests, cost ledgers, runtime hooks, provider parsing, run id generation,
orphan detection, decisions, watch, budget policy, and apply evidence. The
runtime is now much stronger than the first operator experience around it.

The remaining gap is not one more isolated parser fix. The failure pattern is
broader:

- a user gives a reasonable design or implementation document;
- Waygent expects a stricter task shape than the document uses;
- parsing or preparation fails before useful work starts;
- the operator has to debug document format instead of reviewing execution.

The approved direction is to treat these as intake recovery problems, not as
reasons to abandon the run. Waygent must preserve quality and safety while
removing avoidable stops.

Existing boundaries stay in force:

- Waygent is the active user-facing orchestrator.
- Lens is the TypeScript projection and inspection layer inside Waygent.
- `waygent.run_state.v2` remains the runtime source of truth.
- `agentlens.event.v3` remains the event envelope.
- Active event families remain `platform.*`, `runway.*`, `kernel.*`, and
  `lens.*`.
- The legacy Python AgentLens tree and the old KWS CPE/CME routing model are
  not reintroduced.

## Design Principles

1. Start safe work instead of failing on document shape. Minor parse and
   preflight shape errors should become recoverable intake events.
2. Preserve quality with evidence. Every automatic repair must leave a
   structured report, a normalized artifact, and source references.
3. Prefer cheap deterministic repair first. Use AI repair only when heuristics
   cannot produce a confident executable shape.
4. Ask only for high-risk ambiguity. User questions are reserved for real
   product, safety, ownership, destructive, security, or multi-candidate
   ambiguity.
5. One operator read model. API, Console, and CLI should surface the same
   primary blocker, allowed action, blocked action, evidence packet, and next
   command.
6. Fixture everything that once blocked progress. The regression harness should
   keep bad-but-recoverable plan/spec examples and unsafe examples from
   regressing back into silent failure or unsafe execution.
7. Efficiency must not lower quality. Parallelize safe independent work, keep
   shared-core or overlapping claims serial, and keep verification evidence
   mandatory for apply readiness.

## Non-Goals

- Do not make Lens mutate source files, resume runs, or apply checkpoints.
- Do not let AI override apply readiness, checkout safety, or destructive
  command policy.
- Do not require live provider calls for default fixture tests.
- Do not infer broad write scope from vague prose when file ownership is truly
  ambiguous.
- Do not silently drop tasks that could not be normalized.
- Do not create `waygent.run_state.v3` for this slice. This slice is additive
  to `waygent.run_state.v2`.

## Architecture

The integrated architecture is:

```text
raw plan/spec documents
  -> strict parser attempt
  -> lenient intake recovery
  -> normalized executable plan artifact
  -> deterministic preflight
  -> run_state.v2
  -> operator decision projection
  -> API / Console / CLI
```

Fixture-Lab tests the full path:

```text
fixture input
  -> provider/result normalizer
  -> run_state.v2 mutation
  -> lens operator projection
  -> CLI/API/Console expectation
```

The key architectural change is that parse failure and preparation failure are
no longer terminal by default. They become intake findings. Waygent tries to
repair them into a normalized executable plan, records the repair evidence, and
then runs the normal deterministic safety gates.

## Components

### Intake Recovery

Intake Recovery runs before plan preflight creates the run state.

Inputs:

- raw plan markdown;
- optional raw spec/design markdown;
- resolved file paths and basename candidates;
- current workspace root;
- parser diagnostics from strict parsing;
- configured provider/execution profile.

Outputs:

- `artifacts/intake/normalized-plan.md`;
- `artifacts/intake/recovery-report.json`;
- structured intake events;
- either an executable normalized plan or a blocking intake decision.

The recovery report should include:

- original plan/spec refs;
- parser failures and preparation failures;
- repair actions attempted;
- confidence per recovered task;
- source line or section refs when available;
- inferred file claims and their evidence;
- inferred verification commands and their evidence;
- unresolved ambiguities;
- whether execution may proceed automatically.

### Deterministic Repair

The cheap repair tier handles common document drift:

- `## Task N:`, `### Task N:`, `Task N`, `작업 N`, and phase-like headings;
- task bodies written as prose instead of YAML;
- basename `--plan` and `--spec` when exactly one approved candidate exists;
- file claims expressed as bullets, paths, or "modify/read/create" prose;
- verification commands inside fenced shell blocks or command bullets;
- missing YAML frontmatter when enough body structure exists.

Deterministic repair may proceed only when it can produce a traceable
normalized plan with no dangerous ambiguity.

### Recovered Task Risk Classification

Tasks emitted by deterministic repair from non-YAML or prose-shaped input
MUST normalize to `risk: "high"`, regardless of the severity of recovered
findings. The strict YAML `waygent-task` block is the only contract under
which a task author declares a lower risk; recovered tasks have not been
authored under that contract and therefore carry the most conservative
classification until a human upgrades them in source.

This is independent of intake finding severity. Finding severity decides
whether the run can start at all (recoverable vs decision_required); risk
classification decides how cautiously the runtime schedules and gates the
recovered task once it does start. Bounded AI repair is bound by the same
rule: AI-repaired tasks emit `risk: "high"` until reviewed.

Existing test surfaces that assert `risk: "high"` on recovered superpowers
prose plans (e.g. `apps/cli/tests/cli.test.ts` "run normalizes executable
superpowers implementation plans before dispatch") are load-bearing
documentation of this policy and must remain green.

### Bounded AI Repair

AI repair is used only when deterministic repair cannot confidently normalize
the document, but the user intent is still clear.

AI repair receives bounded context:

- raw task-like sections;
- nearby spec sections;
- detected paths;
- parser diagnostics;
- allowed file-claim modes;
- safe verification command rules.

AI repair must produce structured output, not free-form execution advice:

- normalized task id and title;
- task body;
- file claims with modes;
- dependencies;
- risk level;
- verification commands;
- confidence;
- reasons to ask the user, if any.

The AI repair output still goes through deterministic validation before any
run starts.

### Operator Decision Projection

`packages/lens-projectors` should remain the home for the operator decision
read model. The projection should compute:

- status summary;
- primary blocker;
- secondary blockers;
- allowed actions;
- blocked actions;
- evidence packet;
- next command;
- intake recovery summary;
- confidence and unknown reasons.

API, Console, and CLI must not each reinvent this logic. They should consume
the projection and present it in their own format.

### Fixture-Lab

Fixture-Lab becomes the regression harness for both runtime and intake defects.
Fixtures should live under a dedicated test fixture tree such as
`tests/fixtures/waygent-lab/`.

Each fixture should declare:

- raw input documents or provider artifacts;
- expected normalizer output;
- expected runtime state mutation;
- expected recovery/apply status;
- expected operator decision;
- whether user input is required.

The harness should keep provider-output failures and plan/spec intake failures
in the same lab because both ultimately affect the operator's ability to start,
recover, or apply a run.

## Data Flow

### Happy Path

1. User runs `waygent run --plan <plan> --spec <spec>`.
2. Strict parser succeeds.
3. Plan preflight passes.
4. Waygent creates `waygent.run_state.v2`.
5. Tasks execute according to safe-wave scheduling.
6. Lens computes operator decision from state, events, and artifacts.
7. CLI/API/Console show the same next safe action.

### Recoverable Intake Path

1. User runs `waygent run --plan <plan> --spec <spec>`.
2. Strict parser reports shape errors.
3. Waygent emits `platform.intake_recovery_started`.
4. Deterministic repair attempts normalization.
5. If needed, bounded AI repair attempts normalization.
6. Waygent writes normalized plan and recovery report artifacts.
7. Waygent emits `platform.intake_recovery_completed`.
8. Deterministic preflight validates the normalized plan.
9. If safe, execution starts without asking the user.

### High-Risk Intake Path

1. Strict parsing or repair finds a high-risk ambiguity.
2. Waygent writes the recovery report.
3. Waygent emits `platform.intake_decision_required`.
4. Operator decision shows the blocker and a short user question.
5. No unsafe task starts until the decision is resolved.

## Error Handling

Recoverable intake findings include:

- `task_heading_unrecognized`;
- `task_body_not_yaml`;
- `missing_frontmatter`;
- `single_spec_candidate_by_basename`;
- `file_claims_in_prose`;
- `verification_command_in_prose`;
- `verification_command_unclassified_but_safe`;
- `plan_section_body_sparse_but_spec_section_available`.

High-risk blockers include:

- multiple matching plan or spec candidates;
- destructive command candidates;
- conflicting `owned` claims for the same file without dependency ordering;
- path escape outside the workspace;
- missing verification for source-mutating tasks;
- external credentials, secrets, or account login required;
- scope expansion beyond the supplied plan/spec;
- apply-like mutation requested before verification evidence exists.

When only part of the plan is recoverable, Waygent may start safe independent
tasks only if their dependencies and file claims are complete. Dependent tasks
behind an unresolved intake blocker remain blocked.

## Efficient Execution Policy

The execution policy should preserve quality while avoiding unnecessary cost:

1. Use strict parsing first because it is cheapest and most reliable.
2. Use deterministic repair for common markdown and path-shape issues.
3. Use AI repair only for sections that need semantic reconstruction.
4. Validate AI repair through deterministic preflight.
5. Schedule independent, checkpoint-ready tasks in safe waves.
6. Keep shared-core, overlapping file claims, migration, schema, and apply
   paths serial unless the same implementation plan includes an explicit
   scheduler proof for safe separation.
7. Do not interrupt active provider processes for budget or intake decisions;
   evaluate those policies at safe parent-process boundaries.

Efficiency is not a reason to skip verification. Apply readiness continues to
require verified checkpoints, patch evidence, dry-run evidence, completion
audit, reconciliation, and a clean source checkout.

## Product Surface

### CLI

`waygent run` should show when intake recovery happened and where the artifacts
are. `waygent explain`, `waygent inspect`, and `waygent status` should surface
the same intake summary through the operator projection.

Recommended command behavior:

- recoverable intake issue: run continues and returns artifact refs;
- high-risk intake issue: command exits with a decision-required status and
  the short reason;
- fixture run: can assert the normalized plan and operator decision without a
  live provider.

### API

API run detail should expose the operator decision projection including intake
recovery state. It should not recompute next actions separately from Lens.

### Console

Workbench v2 should make intake failures visible as operational blockers, not
as raw parser errors. The run board and detail view should show:

- primary blocker;
- next safe action;
- whether intake recovery repaired the plan;
- evidence refs for normalized plan and recovery report;
- user decision needed only when the ambiguity is high-risk.

## Testing

The first implementation plan should include focused tests in this order:

1. Intake parser diagnostics tests for strict failure classification.
2. Deterministic repair tests for headings, prose claims, single basename
   resolution, and command extraction.
3. Bounded AI repair contract tests using fake provider output, not live
   provider calls.
4. Plan preflight tests proving normalized plans still enforce file claims,
   dependencies, and verification commands.
5. Fixture-Lab end-to-end tests for bad-but-recoverable plan/spec examples.
6. Fixture-Lab unsafe tests proving destructive, ambiguous, or unverified
   cases ask the user instead of executing.
7. Operator projection tests proving CLI/API/Console see the same blocker,
   allowed action, blocked action, evidence refs, and next command.

Minimum fixture cases:

- `### Task` sections that strict parsing previously missed;
- prose-only file claims that can be mapped to one file and one mode;
- natural-language "run tests" verification with a clear local script match;
- basename spec path with exactly one candidate;
- malformed provider stdout containing a valid worker-result fence;
- provider usage present at envelope level;
- missing checkpoint;
- checkpoint dry-run conflict classified as `needs_rebase`;
- dirty source checkout;
- method evidence missing;
- multiple spec candidates requiring user decision;
- destructive command candidate requiring user decision;
- conflicting owned claims requiring user decision or serial dependency.

## Acceptance Criteria

- A recoverable plan/spec shape issue no longer stops `waygent run` before
  useful execution can start.
- Every automatic intake repair writes a normalized plan and recovery report.
- High-risk ambiguity asks the user instead of guessing.
- Operator Workbench, API, and CLI expose the same primary blocker and next
  action.
- Fixture-Lab contains both recoverable and unsafe intake examples.
- Fixture-Lab proves that automatic repair preserves task intent, file
  ownership, verification, and apply safety.
- The implementation keeps `waygent.run_state.v2` and `agentlens.event.v3`
  additive rather than introducing a schema reset.

## Verification Plan

Use the smallest command set that proves the implemented slice. Expected
defaults for the future implementation plan:

```bash
bun test packages/orchestrator/tests packages/context-packer/tests packages/provider-adapters/tests packages/lens-projectors/tests apps/cli/tests
bun run waygent:scenarios
bun run waygent:dogfood
bun run check
skills/waygent/evals/run.sh
git diff --check
```

After meaningful code or documentation structure changes, refresh Graphify with
`graphify update .` and include the generated graph output only when it is part
of the intended commit scope.
