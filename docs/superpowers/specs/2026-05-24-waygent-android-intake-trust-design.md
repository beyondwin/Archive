# Waygent Android Intake Trust

Goal: make Waygent safely execute Android/Kotlin Superpowers plans that
already contain explicit file claims and Gradle verification commands, while
reducing drift between intake normalization, recovery, preflight, provider
attestation, and safe-wave scheduling.

This design is grounded in the FixThis source-matching trust program dogfood
run from 2026-05-24. That run blocked before provider dispatch even though the
plan contained explicit Kotlin file claims and `./gradlew` verification
commands. The failure exposed a broader Waygent issue: `planNormalizer`,
`intakeRecovery`, and `planPreflight` each maintain their own partial command
and path rules, so they can disagree about the same plan.

## 1. Goals and Non-Goals

### 1.1 Goals

- Normalize Superpowers plans that use Android/Kotlin files and Gradle
  verification commands, including `.kt`, `.kts`, `.gradle`,
  `.gradle.kts`, `.mjs`, `./gradlew`, `gradle`, `node --test`, and declared
  package scripts.
- Make safe verification classification a shared policy used by normalization,
  deterministic recovery, and preflight.
- Preserve partial strict-normalizer results during deterministic recovery
  instead of replacing them with weaker prose-only recovery output.
- Emit task-level intake evidence that explains what was extracted, what was
  trusted, what was blocked, and why.
- Add conservative safe-wave barriers for Gradle/module verification overlap.
- Add provider capability attestation so Waygent records requested versus
  actually applied model/reasoning flags for Codex and Claude adapters.
- Add an adjacent contract audit for trust-sensitive plans so nearby docs or
  compatibility contracts are surfaced as review candidates.

### 1.2 Non-Goals

- Auto-editing user plans to add missing claims. Waygent can generate a
  normalized execution artifact, but it must not silently mutate the source
  plan.
- Treating arbitrary shell commands as safe because they appear in a fenced
  block.
- Adding live provider smoke tests to the default test suite. Live provider
  tests remain opt-in because they depend on local CLI state and cost policy.
- Replacing the existing `waygent-task` native plan format.
- Changing persisted Lens event schema names or existing run artifact
  contracts in a breaking way.

## 2. Current Failure

The FixThis plan had explicit task file claims such as
`fixthis-mcp/src/main/kotlin/.../FeedbackQueueFormatter.kt` and verification
commands such as:

```bash
./gradlew :fixthis-mcp:test --tests "*FeedbackQueueFormatterTest" --tests "*CopyPromptEditSurfaceRendererTest" --no-daemon
```

Waygent still produced `platform.intake_decision_required` and did not create
provider attempts or worktrees. The strict normalizer accepted the task shape
but rejected Gradle commands as unsafe. Deterministic recovery then used a
different, narrower path regex and command allowlist, so it reported false
blockers such as "no recoverable file claim" for Kotlin tasks.

Root causes:

- `planNormalizer.ts` has a safe command list that omits Gradle.
- `intakeRecovery.ts` has a separate safe command list and a narrow
  inline-path regex that omits Kotlin and Gradle extensions.
- `planPreflight.ts` has another safe command list, so a command accepted by
  normalization can still fail preflight.
- Strict normalization and deterministic recovery do not share an intermediate
  extraction model.
- Provider option attestation can overstate requested options when the local
  CLI does not support them.
- The executor can miss adjacent contract docs when a plan touches handoff
  trust wording or persisted output semantics.

## 3. Architecture

Waygent intake becomes a single policy-backed pipeline instead of three
parallel parsers with overlapping rules.

```
runWaygent
  -> resolve plan/spec/workspace
  -> buildProjectCommandCatalog
  -> extractPlanClaims
  -> classifyVerificationCommands
  -> normalizeSuperpowersPlan
  -> mergeIntakeRepair
  -> runPlanPreflight
  -> buildExecutionDependencyBarriers
  -> probeProviderCapabilities
  -> dispatch provider workers
```

### 3.1 `verificationPolicy`

New shared module in `packages/orchestrator/src/planAdapters/`:

```ts
export interface VerificationPolicyInput {
  command: string;
  workspace: string;
  catalog: ProjectScriptCatalog;
}

export interface VerificationClassification {
  command: string;
  status: "safe" | "unsafe" | "ignored";
  reason:
    | "gradle_wrapper"
    | "gradle"
    | "node_test"
    | "package_script"
    | "known_runner"
    | "git_diff_check"
    | "destructive"
    | "workspace_escape"
    | "unknown";
  segments: VerificationCommandSegment[];
}
```

Responsibilities:

- Split `&&` command chains and require every segment to be safe.
- Allow initial `cd <workspace-subdir>` when it stays inside the workspace.
- Allow `./gradlew ...`, `gradle ...`, `node --test ...`, known JS/Bun/Cargo
  test commands, declared package scripts, and `git diff --check`.
- Reject destructive commands, workspace escapes, unsafe shell redirection, and
  unknown commands.
- Return structured reasons rather than only boolean safe/unsafe.

`planNormalizer`, `intakeRecovery`, and `planPreflight` must call this module.
They must not carry separate `SAFE_COMMAND_STARTS` arrays after this change.

### 3.2 `planClaimExtraction`

New shared module in `packages/orchestrator/src/planAdapters/`:

```ts
export interface ExtractedPlanTask {
  number: number;
  title: string;
  body: string;
  explicit_file_claims: FileClaim[];
  prose_file_claims: FileClaim[];
  fenced_commands: string[];
}
```

Responsibilities:

- Extract Superpowers `##/### Task N:` sections while masking fenced code
  examples.
- Extract explicit `**Files:**` claims with `Create`, `Modify`, `Read`, and
  `Append` modes.
- Extract prose paths as lower-confidence recovery evidence.
- Support common source and build extensions used by Waygent target repos:
  `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.json`, `.md`, `.mdx`, `.toml`,
  `.yaml`, `.yml`, `.rs`, `.py`, `.sh`, `.css`, `.html`, `.kt`, `.kts`,
  `.gradle`, `.gradle.kts`, `.java`, `.xml`.
- Prefer explicit claims over prose claims for the same path.

### 3.3 `intakeRepairPlanner`

New merge layer that receives strict normalization diagnostics and extracted
task evidence. It produces task-level statuses:

```ts
export type IntakeTaskStatus =
  | "normalized"
  | "recovered"
  | "blocked"
  | "warning";
```

Rules:

- If strict normalization succeeded for a task, deterministic recovery must
  not replace it with weaker prose recovery.
- If strict normalization failed because a command is unsafe, the blocker is
  `unsafe_verification_command`, not `missing_file_claim`.
- If explicit file claims exist but fallback extraction misses them, record
  `extractor_policy_gap` instead of a user-actionable missing-claim blocker.
- If any task remains blocked, the whole run stays intake-blocked by default,
  but the partial normalized artifact is still written for inspection.

### 3.4 `executionDependencyBarrier`

New orchestration helper that inserts conservative wave barriers before
provider dispatch. It analyzes task file claims and verification commands.

Rules:

- Tasks with overlapping owned file claims cannot run in the same wave.
- Gradle module verification such as `:fixthis-mcp:test` is treated as reading
  that module and its compile-time dependencies when they can be inferred.
- Whole-build or broad test commands are treated as integration barriers and
  placed after module-local edits when possible.
- If module dependency inference is uncertain, reduce parallelism for the
  affected tasks and emit a warning event rather than pretending the wave is
  independent.

### 3.5 `providerCapabilityProbe`

New provider-adapter support that records actual local CLI capability before
launching workers.

For Codex, probe `codex exec --help` or the adapter's configured binary help
surface. If `--reasoning` is unsupported, Waygent omits that flag rather than
failing a valid run. The artifact must distinguish requested values from
applied values:

```json
{
  "provider": "codex",
  "requested_reasoning": "high",
  "applied_reasoning": null,
  "reason": "unsupported_by_cli"
}
```

Provider binary absence or unusable help output remains a provider startup
failure.

### 3.6 Adjacent Contract Audit

New advisory audit in intake. It scans plan/spec terms and file claims for
trust-sensitive surfaces:

- persisted output schema and MCP JSON field names
- handoff markdown and compact prompt wording
- source matching confidence, risk, target reliability, source candidates
- feedback console contracts

When triggered, it emits `adjacent_contract_candidate` findings for likely
docs or contract files. It does not automatically add file claims.

## 4. Data Flow and Artifacts

### 4.1 Flow

1. `runWaygent` resolves plan, spec, workspace, and project command catalog.
2. `extractPlanClaims` creates a task-by-task raw extraction model.
3. `classifyVerificationCommands` annotates every fenced command.
4. `normalizeSuperpowersPlan` builds native `waygent-task` blocks from
   explicit claims and safe verification commands.
5. `mergeIntakeRepair` combines strict output and recovery output.
6. `runPlanPreflight` validates the same normalized model using the shared
   policy.
7. `executionDependencyBarrier` adjusts the task graph before safe-wave
   execution.
8. `providerCapabilityProbe` records actual provider support.
9. Workers dispatch only after intake, preflight, barrier, and provider
   attestation succeed or produce non-blocking warnings.

### 4.2 Artifacts

Additive artifacts:

- `artifacts/intake/extract-report.json`
  - extracted sections
  - explicit and prose claims
  - fenced commands
  - verification classifications
  - extraction source references
- `artifacts/intake/normalized-plan.md`
  - native `waygent-task` blocks for runnable tasks
  - blocked task summary when not all tasks are runnable
- `artifacts/intake/recovery-report.json`
  - existing report plus `strict_task_status`, `fallback_task_status`,
    `merged_task_status`, and `blocked_tasks`
- `artifacts/platform/provider-capabilities.json`
  - provider binary, version/help status when available, requested/applied
    model and reasoning fields, unsupported flag reasons

Additive events:

- `platform.intake_extract_completed`
- `platform.intake_repair_merged`
- `platform.provider_capability_attested`
- `runway.wave_barrier_inserted`

## 5. Error Handling and Escalation

### 5.1 Intake errors

- Missing explicit file claims remain blocking for source mutations.
- Explicit file claims that are present but missed by fallback extraction are
  reported as `extractor_policy_gap`.
- Unsafe verification commands block the affected task and identify the exact
  command segment.
- Destructive command candidates remain blocking.
- Partial normalized plans are written whenever at least one task can be
  normalized.

### 5.2 Verification policy errors

- `./gradlew` and `gradle` commands are safe only when every command segment
  is safe.
- `cd` is safe only as the first segment and only inside the workspace.
- Package scripts are safe only when declared in the workspace catalog.
- Absolute paths, workspace escapes, destructive git commands, and unknown
  shell features are unsafe.

### 5.3 Wave barrier errors

- Unclear Gradle module dependency inference does not block the run by itself.
  It inserts a conservative barrier and emits a warning.
- Owned claim conflicts remain blocking.
- Broad verification commands become integration-like barriers.

### 5.4 Provider capability errors

- Unsupported optional flags are omitted and attested.
- Missing provider binary or failed provider startup remains blocking.

### 5.5 Adjacent contract audit errors

- Adjacent contract findings are warnings by default.
- They become blocking only if a plan explicitly declares a required contract
  doc update and then omits that file claim.

## 6. Testing Strategy

### 6.1 Unit tests

- `verificationPolicy.test.ts`
  - classifies `./gradlew :fixthis-mcp:test ...`, `gradle test`,
    `node --test scripts/foo.mjs`, declared `npm run` scripts, undeclared
    package scripts, safe `cd`, workspace-escaping `cd`, and destructive
    chains.
- `planClaimExtraction.test.ts`
  - extracts `.kt`, `.kts`, `.gradle`, `.gradle.kts`, `.mjs`, `.md`, and
    existing JS/TS/docs extensions from Superpowers `**Files:**` blocks.
  - verifies explicit claims override prose claims.
- `planNormalizer.test.ts`
  - normalizes a reduced FixThis source-matching trust plan containing Kotlin
    claims and Gradle verification commands.
- `intakeRecovery.test.ts`
  - preserves strict-normalized task evidence when fallback recovery runs.
  - reports `extractor_policy_gap` instead of false missing-claim blockers.
- `planPreflight.test.ts`
  - confirms commands accepted by the normalizer are accepted by preflight.
- `providerCapabilityProbe.test.ts`
  - records requested/applied reasoning differences when a Codex CLI does not
    support `--reasoning`.
- `executionDependencyBarrier.test.ts`
  - inserts barriers for overlapping Gradle module verification and broad test
    commands.

### 6.2 Integration tests

- Add a fake-provider fixture based on the FixThis source-matching trust plan.
- Assert the fixture reaches provider-dispatch planning rather than
  `platform.intake_decision_required`.
- Assert `extract-report.json` and `recovery-report.json` explain Kotlin file
  claims and Gradle verification commands.
- Keep live Codex smoke testing opt-in.

### 6.3 Verification commands

Minimum implementation verification:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/provider-adapters/tests/providerCapabilityProbe.test.ts \
  packages/orchestrator/tests/executionDependencyBarrier.test.ts
bun run typecheck
bun run waygent:fixture-lab
git diff --check
```

If the FixThis checkout is available locally, run an additional fake-provider
dogfood check against the reduced source-matching trust fixture.

## 7. Completion Criteria

- The reduced FixThis source-matching trust fixture no longer blocks at intake
  due to missing `.kt` file claims or unsafe `./gradlew` verification.
- `planNormalizer`, `intakeRecovery`, and `planPreflight` use the same
  verification policy and path extraction support.
- `recovery-report.json` can show task-level normalized, recovered, and
  blocked statuses without discarding strict-normalizer evidence.
- Provider capability artifacts distinguish requested and applied options.
- Safe-wave barrier events explain when Gradle/module uncertainty reduced
  parallelism.
- Adjacent contract audit surfaces relevant contract docs as advisory findings
  for trust-sensitive plans.

## 8. Rollout Plan

Implementation note: the shared command parser lives in
`packages/orchestrator/src/planAdapters/commandLines.ts`, the shared
verification policy in
`packages/orchestrator/src/planAdapters/verificationPolicy.ts`, and the
Superpowers extractor in
`packages/orchestrator/src/planAdapters/planClaimExtraction.ts`.

1. Add shared extraction and verification policy modules behind existing
   behavior-preserving tests.
2. Refactor `planNormalizer`, `intakeRecovery`, and `planPreflight` to consume
   the shared modules.
3. Add task-level merge reporting and partial normalized artifacts.
4. Add provider capability probe and attestation artifact.
5. Add execution dependency barriers for Gradle/module scopes.
6. Add adjacent contract audit warnings.
7. Add the reduced FixThis fixture and run the full verification set.

## 9. Open Design Constraints

- Prefer warnings over blockers when Waygent is adding advisory context rather
  than enforcing a safety boundary.
- Keep native `waygent-task` plans unchanged unless they contain unsafe
  verification commands.
- Do not auto-claim adjacent docs. The audit should surface candidates, not
  change worker ownership silently.
- Keep all changes inside active Waygent packages and docs. Do not revive
  legacy AgentRunway or Python paths.
