# Waygent Full-Plan Intake Hardening

- **Date**: 2026-05-24
- **Type**: Brainstorming-approved design spec
- **Status**: Approved design, pending implementation plan
- **Scope**: Waygent Superpowers plan extraction, verification command
  classification, intake recovery evidence, and full-plan regression fixtures

## 1. Goal

Waygent should recover and execute real Superpowers implementation plans whose
intent is clear, not only reduced plan fixtures. The immediate target is the
FixThis source-matching runtime trust fixture plan from 2026-05-24. That plan
contains explicit file claims and safe verification commands, but current
intake still blocks because Markdown prose and example code fences are
misclassified as unsafe verification commands.

The product behavior should be:

```text
Given a full Superpowers plan with task headings, file claims, implementation
examples, verification fences, git checkpoint notes, optional environment
checks, and final cleanup steps, Waygent extracts only real shell verification
commands into verify, preserves implementation instructions separately, records
diagnostic evidence, and asks the user only for genuinely unsafe or ambiguous
execution.
```

## 2. Current Evidence

The prior Android intake trust work fixed the first-order issue: Kotlin paths,
Gradle commands, declared package scripts, shared verification policy, provider
capability attestation, and adjacent contract warnings are now represented in
the codebase.

Focused tests currently pass:

```bash
bun test packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/intakeRepairPlanner.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/orchestrator/tests/executionDependencyBarrier.test.ts \
  packages/provider-adapters/tests/capabilityProbe.test.ts \
  tests/integration/waygent-android-intake-trust.test.ts
```

Result observed during brainstorming: 43 passing tests.

However, replaying the full FixThis plan through
`recoverWaygentPlanInput(...)` still returns:

```json
{
  "status": "decision_required",
  "can_start": false,
  "task_count": 0,
  "question": "The plan contains a destructive command candidate. Confirm the intended safe replacement before execution."
}
```

The extracted command candidates include lines such as:

- `- [ ] **Step 2: Run tests to verify failure**`
- `Run:`
- `Expected: PASS.`
- `Create RuntimeTrustFixtureRunner.kt:`
- `Update usage():`

Those are not commands. They appear because
`packages/orchestrator/src/planAdapters/planClaimExtraction.ts` uses a broad
fenced-block regular expression that can treat non-shell examples and fence
closers as shell command content.

The reduced integration fixture in
`tests/integration/waygent-android-intake-trust.test.ts` proves Gradle/Kotlin
support, but it does not include the full-plan shape that failed: JavaScript,
JSON, Kotlin, and prose examples mixed with bash verification blocks.

## 3. Goals and Non-Goals

### Goals

- Extract shell verification commands only from explicit shell fences:
  `bash`, `sh`, `shell`, and `zsh`.
- Never send checklist lines, headings, expected-result prose, or non-shell
  example code to the verification classifier.
- Preserve non-shell fenced examples as implementation context, not verify
  commands.
- Add command roles so diagnostic and optional-environment commands do not
  become unsafe blockers.
- Keep unknown commands blocking by default.
- Add a full-plan regression fixture based on the FixThis runtime trust plan.
- Include `extract_report_ref` in operator-facing intake artifact references.
- Keep all behavior additive to `waygent.run_state.v2` and
  `agentlens.event.v3`.

### Non-Goals

- Do not auto-edit the source plan.
- Do not make arbitrary unlabeled fences executable.
- Do not weaken destructive command or workspace-escape blocking.
- Do not add live provider or live Android device requirements to default
  tests.
- Do not redesign Console UI beyond exposing already-written artifact refs.
- Do not replace native `yaml waygent-task` plans or change their contract.

## 4. Architecture

This slice keeps the existing shared intake pipeline and strengthens its
frontier:

```text
raw Superpowers plan
  -> fence-aware plan scanner
  -> extracted task model
  -> command role classification
  -> normalizer and deterministic recovery
  -> preflight with shared policy
  -> operator decision projection with complete intake artifacts
```

The existing modules remain the right ownership boundaries:

- `planClaimExtraction.ts` owns task section extraction, file claims, prose
  paths, fenced blocks, and command candidates.
- `verificationPolicy.ts` owns command safety and role classification.
- `planNormalizer.ts` owns executable `waygent-task` materialization.
- `intakeRecovery.ts` owns deterministic repair and recovery reports.
- `intakeRepairPlanner.ts` owns task-level merged intake status.
- `operatorDecision.ts` owns operator-facing evidence refs.

## 5. Fence-Aware Extraction

Replace regex-only fenced command extraction with a small line scanner.

The scanner should:

1. Detect a fence opener only when not currently inside a fence.
2. Detect a fence closer only when currently inside a fence.
3. Preserve the language label and source line range.
4. Treat only `bash`, `sh`, `shell`, and `zsh` blocks as command candidates.
5. Treat `javascript`, `js`, `json`, `kotlin`, `kt`, `java`, `ts`, `tsx`,
   `text`, and unlabeled fences as example blocks.
6. Never parse content after a closing fence as part of the just-closed block.

`ExtractedPlanTask` should grow additive fields:

```ts
interface ExtractedPlanTask {
  fenced_commands: string[];
  fenced_examples?: ExtractedFenceBlock[];
  command_candidates?: ExtractedCommandCandidate[];
}
```

`fenced_commands` remains for compatibility and contains only shell command
lines. New structured fields are for evidence and tests.

`ExtractedCommandCandidate` should carry enough evidence to explain why a line
was or was not executable:

```ts
interface ExtractedCommandCandidate {
  command: string;
  source: "shell_fence" | "prose_hint" | "diagnostic_hint";
  language: string | null;
  line_start: number;
  line_end: number;
}
```

The default implementation should only create candidates from shell fences.
Future prose command recovery can use `prose_hint`, but this slice should not
infer commands from prose.

## 6. Command Role Policy

The current classifier returns `safe`, `unsafe`, or `ignored`. That should stay
available for compatibility, but the internal model should carry a role:

```ts
type VerificationCommandRole =
  | "verification"
  | "implementation_only"
  | "diagnostic_readonly"
  | "optional_environment"
  | "unsafe"
  | "unknown";
```

Mapping rules:

- `verification`: existing safe commands such as declared package scripts,
  `./gradlew ...`, `gradle ...`, `node --test ...`, `git diff --check`,
  known test/check runners.
- `implementation_only`: `git add`, `git commit`, `git merge`, install
  commands, formatters in write mode, code generators, and `graphify update .`.
- `diagnostic_readonly`: `git status --short`, `git status --short --branch`,
  `git log --oneline`, `git diff --stat`, and similar read-only inspection.
- `optional_environment`: `command -v adb || true`, `adb devices` when used as
  an environment probe, and explicitly optional runtime checks.
- `unsafe`: destructive commands, workspace escapes, unsafe redirection,
  unknown shell features, and command chains that mix verification with
  mutating implementation-only segments.
- `unknown`: not executable by policy and not allowlisted. Unknown commands
  remain blocking when they appear as shell command candidates.

Compatibility:

- Public `status` can still be computed from role:
  - `verification` -> `safe`
  - `implementation_only`, `diagnostic_readonly`, `optional_environment` ->
    `ignored`
  - `unsafe`, `unknown` -> `unsafe`
- Recovery reports should use role-specific finding codes where helpful:
  - `implementation_command_not_verification`
  - `diagnostic_command_ignored`
  - `optional_environment_command_ignored`
  - `unsafe_verification_command`

## 7. Normalization and Recovery Behavior

`normalizeWaygentPlanInput(...)` and `recoverWaygentPlanInput(...)` should
share the fence-aware extraction model.

Rules:

- Only `verification` role commands become task `verify` entries.
- `implementation_only` commands remain in task instructions and repair
  evidence, but never in `verify`.
- `diagnostic_readonly` commands remain in evidence and may be shown in final
  operator guidance, but do not satisfy verification requirements.
- `optional_environment` commands remain in evidence and do not block default
  execution. Strict runtime checks can still be requested by a real verify
  command such as a declared package script with `--strict`.
- A source-mutating task still needs at least one `verification` command unless
  it is read-only or explicitly docs-only and covered by existing policy.
- Any `unsafe` command candidate blocks the affected task.
- Non-shell example code never contributes an unsafe command candidate.

The full FixThis plan contains git checkpoint commands. These must be preserved
as instructions or ignored implementation evidence, not treated as
verification and not treated as destructive by themselves.

## 8. Operator Evidence

`runWaygent(...)` already writes `artifacts/intake/extract-report.json`.
Operator projections should expose that artifact with the same priority as the
normalized plan and recovery report.

Update `intakeArtifactRefs(...)` so the returned refs include:

1. `normalized_plan_ref`
2. `recovery_report_ref`
3. `extract_report_ref`

This is intentionally not a Console redesign. API, CLI, and Console should
benefit through the existing shared operator decision projection.

## 9. Regression Fixture Strategy

Add a full-plan fixture that is close to the real FixThis plan but small enough
to keep test output readable. It must include:

- Multiple `### Task N:` sections.
- Explicit `**Files:**` blocks.
- Bash verification fences.
- JavaScript, JSON, and Kotlin example fences.
- `git add` and `git commit` checkpoint fences.
- `graphify update .`.
- Read-only diagnostics such as `git status --short --branch`.
- Optional runtime/environment commands.
- Runtime strict/default package scripts.

Required tests:

- `planClaimExtraction.test.ts`
  - extracts shell commands only from shell fences;
  - records non-shell fences as examples;
  - does not emit checklist or expected-result prose as command candidates.
- `verificationPolicy.test.ts`
  - classifies read-only diagnostics and optional environment probes as
    non-blocking roles;
  - keeps unknown shell commands unsafe.
- `intakeRecovery.test.ts`
  - recovers the full-plan fixture;
  - reports no prose/checklist `unsafe_verification_command`;
  - produces at least one verification command for every source-mutating task.
- `waygent-android-intake-trust.test.ts`
  - runs the full-plan fixture with the fake provider;
  - reaches `runway.plan_loaded`;
  - does not emit `platform.intake_decision_required`.
- `operatorDecision.test.ts`
  - includes `extract_report_ref` in intake artifact refs.

## 10. Error Handling

- Unterminated fences become extraction warnings and do not create executable
  command candidates.
- Unknown shell-fence commands remain blocking, because a human intentionally
  placed them in an executable-looking block.
- Non-shell fences that contain destructive-looking strings do not block by
  themselves. They are examples, not commands.
- A shell fence containing only implementation-only or diagnostic commands does
  not satisfy verification.
- A shell command chain containing both verification and implementation-only
  mutation remains unsafe.
- Optional environment commands never mask a missing required verification.

## 11. Completion Criteria

The implementation is complete when:

- The full FixThis-style fixture recovers deterministically.
- The full FixThis-style fake-provider run reaches `runway.plan_loaded`.
- No checklist, heading, `Run:`, or `Expected:` prose appears as an unsafe
  verification command.
- Non-shell code examples are preserved as evidence but excluded from verify.
- `git status --short --branch` and optional environment probes no longer
  trigger intake blockers.
- `extract_report_ref` appears in operator evidence refs.
- Existing Android intake trust, quality recovery, and plan preflight tests
  remain green.

Minimum verification:

```bash
bun test packages/orchestrator/tests/planClaimExtraction.test.ts \
  packages/orchestrator/tests/verificationPolicy.test.ts \
  packages/orchestrator/tests/intakeRecovery.test.ts \
  packages/orchestrator/tests/intakeRepairPlanner.test.ts \
  packages/orchestrator/tests/planNormalizer.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/lens-projectors/tests/operatorDecision.test.ts \
  tests/integration/waygent-android-intake-trust.test.ts
bun run typecheck
git diff --check
```

If the FixThis checkout is available locally, also run a direct recovery
smoke check against:

```text
/Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-24-source-matching-runtime-trust-fixtures.md
```

Expected: `recoverWaygentPlanInput(...)` returns `status: "recovered"`.

## 12. Rollout Plan

1. Add the full-plan fixture and failing tests first.
2. Replace fenced command regex extraction with a line scanner.
3. Add command roles while preserving existing `status` compatibility.
4. Route normalizer and recovery reports through the structured candidates.
5. Add operator evidence ref coverage for `extract_report_ref`.
6. Run focused tests, typecheck, and `git diff --check`.
7. Refresh Graphify after source/doc changes and avoid staging generated
   graph output.

## 13. Open Constraints

- Keep the default safety posture conservative: unknown shell commands block.
- Keep reduced fixtures, but do not treat them as sufficient coverage for real
  Superpowers plans.
- Do not require Android SDK, ADB, Codex, Claude, or live provider setup for
  the default regression suite.
- Keep all state and event changes additive.
