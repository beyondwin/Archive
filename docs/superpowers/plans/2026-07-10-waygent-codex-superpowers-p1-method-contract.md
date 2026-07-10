# Waygent Codex Superpowers P1 Method Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compile approved Superpowers documents into immutable execution contracts and require artifact-backed method evidence instead of worker self-report.

**Architecture:** P1 builds on `P0_ACCEPTED`. It snapshots exact skills, compiles a full immutable RunManifest, produces bounded task/Lead packets, evaluates public method evidence, and dispatches independent review. P1 can use fake/provider fixtures, but production merge-ready remains blocked until P2 supplies validated App Server explicit skill events and feature-branch integration.

**Tech Stack:** Bun, TypeScript, `bun:test`, Markdown plan/spec parsers, SHA-256 skill snapshots, existing Waygent contracts and Lens artifacts.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- `packages/orchestrator/tests/p0Acceptance.test.ts` must pass before P1 work.
- Required skills are exact names/paths/hashes; prompt imitation is not evidence.
- Snapshot the full referenced skill tree, not only `SKILL.md`.
- Production plans require explicit `spec_refs`; full-spec heuristic fallback blocks.
- The full RunManifest supersedes the P0 integrity manifest through immutable lineage.
- Worker-authored `evidence.method_audit` remains advisory and never passes a gate alone.
- Independent reviewers run in separate attempts and inspect the exact sealed diff hash.
- P1 must not introduce App Server protocol logic, model routing, parallel writers, or source-checkout apply; those are P2.
- No push or protected-branch merge.
- Every helper, fixture, and local constant shown in a test snippet is defined in that named test file and returns the exact contract fields asserted by the task; do not rely on undeclared global test state.

## File Structure

- `packages/orchestrator/src/skillRegistry.ts`, `skillSnapshot.ts`: resolve and snapshot exact Superpowers inputs.
- `packages/orchestrator/src/runManifest.ts`, `manifestCompiler.ts`: immutable document/task/policy contract.
- `packages/context-packer/src/decisionPacket.ts`: bounded Lead input separate from operator recovery packet.
- `packages/orchestrator/src/methodProfiles.ts`, `methodEvidence.ts`: method selection and artifact-backed evaluation.
- `packages/orchestrator/src/reviewRunner.ts`: real asynchronous review dispatch.

## Task Ownership And Risk

| Task | Owner boundary | Risk | Dependency |
| --- | --- | --- | --- |
| 1 | production record types and schemas | high | P0 acceptance |
| 2 | skill discovery, hashing and snapshots | high | Task 1 |
| 3 | manifest compilation, approval basis and lineage | high | Task 2 |
| 4 | bounded task and Lead packet construction | medium | Task 3 |
| 5 | method profile and artifact gate | high | Task 4 |
| 6 | independent reviewer dispatch and review evidence | high | Task 5 |
| 7 | CLI, skill contract and deterministic P1 acceptance | high | Task 6 |

Tasks are sequential across the shared manifest/evidence contracts. Each commit
stages only the exact paths in its task `Files` block; broad directory staging
is forbidden.

---

### Task 1: Define Production Manifest, Skill, Packet And Method Contracts

**Files:**

- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/src/index.ts`
- Create: `packages/contracts/tests/runManifest.test.ts`
- Create: `packages/contracts/tests/methodEvidence.test.ts`
- Create: `packages/contracts/tests/productionPackets.test.ts`

**Interfaces:**

- Produces: `ProductionWorkerRole`, `TaskClass`, `SkillPin`, `SkillRegistrySnapshot`, `CodexRuntimeAttestation`, `RunManifestV1`, `MethodEvidenceReport`, `WaygentTaskPacketV2`, `LeadDecisionPacket`.
- Consumes: P0 `CommandObservation`, immutable artifact references and integrity manifest lineage.

- [ ] **Step 1: Write contract RED tests**

```ts
test("run manifest forbids push and protected merge", () => {
  const manifest = fixtureRunManifest();
  expect(validateContract("waygent.run_manifest.v1", manifest).policies)
    .toMatchObject({ merge_forbidden: true, remote_push_forbidden: true });
});

test("task packet v2 pins skills, model and sandbox", () => {
  const packet = validateContract("waygent.task_packet.v2", fixtureTaskPacket());
  expect(packet.required_skills[0]?.content_sha256).toHaveLength(64);
  expect(packet.manifest_hash).toHaveLength(64);
  expect(packet.result_schema).toBeTruthy();
});

test("standing autonomy is content-addressed and cannot delegate merge", () => {
  const manifest = fixtureRunManifest({ approval: "standing" });
  expect(manifest.approval_basis.policy_sha256).toHaveLength(64);
  expect(manifest.approval_basis.scope).toEqual(["local_feature_branch"]);
  expect(manifest.approval_basis.user_only_actions).toEqual(["protected_merge"]);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/contracts/tests/runManifest.test.ts \
  packages/contracts/tests/methodEvidence.test.ts \
  packages/contracts/tests/productionPackets.test.ts
```

Expected: unknown schemas and missing exported types.

- [ ] **Step 3: Add exact contract shapes**

```ts
export type ProductionWorkerRole =
  | "scout" | "implementer" | "spec_reviewer" | "quality_reviewer"
  | "verifier" | "repairer" | "integrator" | "lead";

export type TaskClass =
  | "mechanical_extraction" | "semantic_exploration" | "feature"
  | "bug_repair" | "docs_config" | "shared_api" | "state_concurrency"
  | "security" | "migration" | "verification" | "review"
  | "integration" | "completion_audit" | "plan_repair";

export interface SkillPin {
  name: string;
  version: string | null;
  source_path: string;
  snapshot_path: string;
  content_sha256: string;
  files: Array<{ path: string; sha256: string; byte_length: number }>;
}

export interface SkillInjectionEvidence {
  skill_name: string;
  skill_path: string;
  skill_sha256: string;
  provider_event_ref: string;
}

export interface ModelRoute {
  policy: "waygent.codex_model_policy.v1";
  task_class: TaskClass;
  role: ProductionWorkerRole;
  model: "gpt-5.6-terra" | "gpt-5.6-sol" | "gpt-5.5" | "gpt-5.4";
  reasoning: "high" | "xhigh" | "max";
  fallback: boolean;
  rationale_code: string;
}

export interface ApprovalBasis {
  kind: "user_approved" | "standing_autonomy_policy";
  policy_ref: string;
  policy_sha256: string;
  scope: Array<"local_analysis" | "local_test" | "local_feature_branch">;
  approved_document_hashes: string[];
  user_only_actions: ["protected_merge"];
}

export interface CodexRuntimeAttestation {
  schema: "waygent.codex_runtime_attestation.v1";
  executable_sha256: string;
  version: string;
  transport: "app_server" | "exec";
  protocol_compatibility_id: string;
  protocol_schema_sha256: string;
  model_list_sha256: string;
  observed_at: string;
}
```

Register strict schemas for the four new records while preserving current v1
packet/recovery readers.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/contracts/tests/runManifest.test.ts \
  packages/contracts/tests/methodEvidence.test.ts \
  packages/contracts/tests/productionPackets.test.ts
git add -- packages/contracts/src/types.ts packages/contracts/src/schemas.ts \
  packages/contracts/src/index.ts packages/contracts/tests/runManifest.test.ts \
  packages/contracts/tests/methodEvidence.test.ts packages/contracts/tests/productionPackets.test.ts
git commit -m "feat(contracts): define Superpowers production records"
```

### Task 2: Build The Skill Registry And Immutable Snapshots

**Files:**

- Create: `packages/orchestrator/src/skillRegistry.ts`
- Create: `packages/orchestrator/src/skillSnapshot.ts`
- Modify: `packages/orchestrator/src/index.ts`
- Create: `packages/orchestrator/tests/skillRegistry.test.ts`
- Create: `packages/orchestrator/tests/fixtures/skills/valid-skill/SKILL.md`
- Create: `packages/orchestrator/tests/fixtures/skills/valid-skill/references/rules.md`
- Create: `packages/orchestrator/tests/fixtures/skills/disabled-skill/SKILL.md`

**Interfaces:**

- Produces: `hashSkillTree`, `resolveSkillRegistry`, `verifyDiscoveredSkills`.
- Guarantees: reference files are included, snapshot paths are private/immutable, hash mismatch blocks.

- [ ] **Step 1: Write Skill Registry RED tests**

```ts
test("snapshot hashes SKILL and referenced files", () => {
  const registry = resolveSkillRegistry({
    required_names: ["valid-skill"],
    roots: [fixtureRoot],
    snapshot_root: privateSnapshotRoot
  });
  expect(registry.skills[0]?.files.map((item) => item.path)).toEqual([
    "SKILL.md",
    "references/rules.md"
  ]);
});

test("discovery mismatch fails before dispatch", () => {
  expect(verifyDiscoveredSkills({ registry, discovered: mismatchedDiscovery }))
    .toMatchObject({ status: "blocked", reason: "skill_hash_mismatch" });
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/skillRegistry.test.ts
```

Expected: missing modules and no snapshot validation.

- [ ] **Step 3: Implement deterministic tree hashing**

Resolve relative references from the selected `SKILL.md`, reject traversal and
symlink escape, sort normalized relative paths, hash path/NUL/bytes entries, and
copy with exclusive private writes. Produce:

```ts
export function resolveSkillRegistry(input: {
  required_names: string[];
  roots: string[];
  snapshot_root: string;
}): SkillRegistrySnapshot;
```

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/skillRegistry.test.ts
git add -- packages/orchestrator/src/skillRegistry.ts packages/orchestrator/src/skillSnapshot.ts \
  packages/orchestrator/src/index.ts packages/orchestrator/tests/skillRegistry.test.ts \
  packages/orchestrator/tests/fixtures/skills/valid-skill/SKILL.md \
  packages/orchestrator/tests/fixtures/skills/valid-skill/references/rules.md \
  packages/orchestrator/tests/fixtures/skills/disabled-skill/SKILL.md
git commit -m "feat(waygent): snapshot exact Superpowers skills"
```

### Task 3: Compile And Seal The Full RunManifest

**Files:**

- Create: `packages/orchestrator/src/runManifest.ts`
- Create: `packages/orchestrator/src/manifestCompiler.ts`
- Modify: `packages/orchestrator/src/planPreflight.ts`
- Modify: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/planNormalizer.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Create: `packages/orchestrator/tests/runManifest.test.ts`
- Modify: `packages/orchestrator/tests/planPreflight.test.ts`
- Create: `packages/orchestrator/tests/p1Acceptance.test.ts`

**Interfaces:**

- Produces: `compileRunManifest`, `writeImmutableRunManifest`, `readRunManifest`, `assertManifestUnchanged`.
- Requires: explicit task class, spec refs, skill pins, base commit, sandbox and policy values.

- [ ] **Step 1: Write RED tests for immutability and spec refs**

```ts
test("ambiguous production plan blocks instead of embedding full spec", () => {
  expect(() => compileRunManifest(inputWithoutSpecRefs()))
    .toThrow("explicit_spec_refs_required");
});

test("different manifest bytes cannot replace an existing run", () => {
  writeImmutableRunManifest(runRoot, manifestA);
  expect(() => writeImmutableRunManifest(runRoot, manifestB))
    .toThrow("manifest_immutable");
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/runManifest.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts
```

Expected: no full manifest exists; production normalizer permits heuristic full-spec fallback.

- [ ] **Step 3: Implement compile/seal/lineage**

```ts
export interface CompileRunManifestInput {
  workspace: string;
  base_commit: string;
  source_branch: string;
  plan_path: string;
  spec_path: string;
  approval_basis: ApprovalBasis;
  tasks: ParsedWaygentTask[];
  skills: SkillRegistrySnapshot;
  model_routes: ModelRoute[];
  runtime_attestation: CodexRuntimeAttestation;
  integrity_manifest_hash: string;
}
```

Canonicalize and hash all semantic fields. Write with exclusive creation. An
identical hash resumes; a semantic change creates revision+1 with `supersedes`
and a new run identity. P1 tests use pinned route/runtime fixtures; production
compilation blocks until its caller supplies resolved routes and runtime
attestation before hashing. P2 wires live resolution into this pre-seal input.
No route or attestation is ever post-filled into an existing manifest.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/runManifest.test.ts \
  packages/orchestrator/tests/planPreflight.test.ts \
  packages/orchestrator/tests/p1Acceptance.test.ts
git add -- packages/orchestrator/src/runManifest.ts packages/orchestrator/src/manifestCompiler.ts \
  packages/orchestrator/src/planPreflight.ts packages/orchestrator/src/planParser.ts \
  packages/orchestrator/src/planNormalizer.ts packages/orchestrator/src/orchestrator.ts \
  packages/orchestrator/tests/runManifest.test.ts packages/orchestrator/tests/planPreflight.test.ts \
  packages/orchestrator/tests/p1Acceptance.test.ts
git commit -m "feat(waygent): compile immutable run manifests"
```

### Task 4: Produce Bounded Task And Lead Decision Packets

**Files:**

- Modify: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/context-packer/src/taskContext.ts`
- Modify: `packages/context-packer/src/repoMap.ts`
- Create: `packages/context-packer/src/decisionPacket.ts`
- Modify: `packages/context-packer/src/index.ts`
- Create: `packages/context-packer/tests/taskPacket.v2.test.ts`
- Create: `packages/context-packer/tests/decisionPacket.test.ts`

**Interfaces:**

- Produces: `buildTaskPacketV2`, `buildLeadDecisionPacket`.
- Separates: Lead semantic packet from existing `runway.decision_packet.v1` operator/recovery packet.

- [ ] **Step 1: Write bounded-context RED tests**

```ts
test("task packet contains only mapped spec sections", () => {
  const packet = buildTaskPacketV2(fixtureInput());
  expect(packet.spec_excerpts.map((item) => item.ref)).toEqual(["spec#journal"]);
  expect(JSON.stringify(packet).length).toBeLessThanOrEqual(packet.context_budget.max_chars);
});

test("Lead packet references logs instead of embedding them", () => {
  const packet = buildLeadDecisionPacket(largeFailureInput());
  expect(JSON.stringify(packet)).not.toContain(largeRawStderr);
  expect(packet.failure_fingerprints).toHaveLength(1);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/context-packer/tests/taskPacket.v2.test.ts \
  packages/context-packer/tests/decisionPacket.test.ts
```

Expected: v2/Lead builders absent; `shallowSymbols` yields no useful symbols; current dispatch does not use selected task context.

- [ ] **Step 3: Implement exact packet builders**

Include manifest hash, task class, skill pins, role, declared sandbox, model-route
slot, write scope, repo map, result schema, acceptance commands and artifact
refs. Hash the final packet. Reject over-budget packets after deterministic
shrink actions rather than silently dropping required fields.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/context-packer/tests
git add -- packages/context-packer/src/taskPacket.ts packages/context-packer/src/taskContext.ts \
  packages/context-packer/src/repoMap.ts packages/context-packer/src/decisionPacket.ts \
  packages/context-packer/src/index.ts packages/context-packer/tests/taskPacket.v2.test.ts \
  packages/context-packer/tests/decisionPacket.test.ts
git commit -m "feat(context): build bounded production task packets"
```

### Task 5: Replace Self-Reported Method Evidence

**Files:**

- Create: `packages/orchestrator/src/methodProfiles.ts`
- Create: `packages/orchestrator/src/methodEvidence.ts`
- Modify: `packages/orchestrator/src/evidencePolicy.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/orchestrator/src/completionAudit.ts`
- Modify: `packages/orchestrator/src/terminalInvariant.ts`
- Create: `packages/orchestrator/tests/methodProfiles.test.ts`
- Create: `packages/orchestrator/tests/methodEvidence.test.ts`
- Modify: `packages/orchestrator/tests/evidencePolicy.test.ts`

**Interfaces:**

- Produces: `requiredMethodProfile`, `evaluateMethodEvidence`.
- Requires: injection events, sealed diff, P0 observations, TDD/debug evidence, review and fresh verification.

- [ ] **Step 1: Invert the current trust test**

```ts
test("worker method_audit cannot satisfy production evidence", () => {
  const result = evaluateMethodEvidence(inputWithOnlyWorkerAudit());
  expect(result.status).toBe("blocked");
  expect(result.blockers).toContain("skill_injection_missing");
});

test("feature profile requires red and green of one command", () => {
  const profile = requiredMethodProfile(featureTask());
  expect(profile.required_skills).toEqual([
    "using-superpowers",
    "test-driven-development"
  ]);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/methodProfiles.test.ts \
  packages/orchestrator/tests/methodEvidence.test.ts \
  packages/orchestrator/tests/evidencePolicy.test.ts
```

Expected: new modules absent; current worker-authored audit passes.

- [ ] **Step 3: Implement profiles and evidence evaluator**

Map feature, bug, review, review correction, verification, plan repair and
self-improvement to the exact approved skill chains. Docs/config waiver requires
a manifest reason and replacement commands. Never inspect private reasoning;
consume only provider injection events and public artifacts.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/methodProfiles.test.ts \
  packages/orchestrator/tests/methodEvidence.test.ts \
  packages/orchestrator/tests/evidencePolicy.test.ts \
  packages/orchestrator/tests/completionAudit.test.ts \
  packages/orchestrator/tests/terminalInvariant.test.ts
git add -- packages/orchestrator/src/methodProfiles.ts packages/orchestrator/src/methodEvidence.ts \
  packages/orchestrator/src/evidencePolicy.ts packages/orchestrator/src/taskExecutor.ts \
  packages/orchestrator/src/completionAudit.ts packages/orchestrator/src/terminalInvariant.ts \
  packages/orchestrator/tests/methodProfiles.test.ts packages/orchestrator/tests/methodEvidence.test.ts \
  packages/orchestrator/tests/evidencePolicy.test.ts
git commit -m "feat(waygent): require artifact-backed method evidence"
```

### Task 6: Dispatch Real Independent Reviewers

**Files:**

- Modify: `packages/orchestrator/src/reviewRunner.ts`
- Modify: `packages/orchestrator/src/reviewPacket.ts`
- Modify: `packages/orchestrator/src/reviewEvidence.ts`
- Modify: `packages/orchestrator/src/reviewArtifacts.ts`
- Modify: `packages/orchestrator/src/runCommands.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `packages/orchestrator/tests/reviewRun.test.ts`
- Create: `packages/orchestrator/tests/fixtures/reviewer-approved.json`
- Create: `packages/orchestrator/tests/fixtures/reviewer-needs-fix.json`

**Interfaces:**

- Changes: `reviewRun` becomes async.
- Produces: separate immutable spec/quality reviewer attempts over the exact sealed diff.
- P1 fixture transport: fake normalized provider events; P2 later supplies App Server.

- [ ] **Step 1: Write RED tests against deterministic auto-approval**

```ts
test("checkpoint presence cannot approve review", async () => {
  const result = await reviewRun(runWithCheckpointAndNeedsFixFixture());
  expect(result.status).toBe("blocked");
  expect(result.review_refs).toHaveLength(2);
});

test("reviewer attempt and root differ from implementer", async () => {
  const result = await reviewRun(approvedFixture());
  expect(result.reviews[0]?.attempt_id).not.toBe(result.implementer_attempt_id);
  expect(result.reviews[0]?.reviewed_patch_sha256).toBe(result.sealed_patch_sha256);
});
```

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/reviewRun.test.ts
```

Expected: current synchronous review auto-approves any checkpoint-bearing task.

- [ ] **Step 3: Implement async provider-backed review**

Create one read-only attempt for `spec_reviewer` and one for
`quality_reviewer`. Packet contains only spec refs, task contract, sealed diff
and evidence refs. Require structured review output and exact patch hash. Apply
findings to state only through a sealed transition.

- [ ] **Step 4: Run GREEN and commit**

```bash
bun test packages/orchestrator/tests/reviewRun.test.ts \
  packages/orchestrator/tests/reviewEvidence.test.ts \
  apps/cli/tests/cli.test.ts
git add -- packages/orchestrator/src/reviewRunner.ts packages/orchestrator/src/reviewPacket.ts \
  packages/orchestrator/src/reviewEvidence.ts packages/orchestrator/src/reviewArtifacts.ts \
  packages/orchestrator/src/runCommands.ts packages/orchestrator/src/orchestrator.ts \
  apps/cli/src/index.ts packages/orchestrator/tests/reviewRun.test.ts \
  packages/orchestrator/tests/fixtures/reviewer-approved.json \
  packages/orchestrator/tests/fixtures/reviewer-needs-fix.json
git commit -m "feat(waygent): run independent task reviewers"
```

### Task 7: Wire P1 Preflight, CLI And Skill Contract

**Files:**

- Modify: `packages/orchestrator/src/orchestrator.ts`
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/profilePreset.test.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `package.json`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/README.md`
- Modify: `skills/waygent/references/commands.md`
- Modify: `skills/waygent/references/modes.md`
- Modify: `skills/waygent/references/nl-lexicon.md`
- Modify: `skills/waygent/evals/check_skill_contract.py`
- Modify: `docs/operations/waygent.md`

**Interfaces:**

- Consumes: `P0_ACCEPTED` and all P1 contracts.
- Produces: `P1_ACCEPTED`; production mode remains `transport_pending` until P2.

- [ ] **Step 1: Add acceptance RED assertions**

Add cases proving production mode blocks when P0 is absent, a skill hash drifts,
spec refs are ambiguous, method evidence is missing, or review was generated by
the old deterministic artifact path. Assert a complete fake fixture returns
`P1_ACCEPTED` and `merge_ready=false` with reason `codex_worker_plane_pending`.

- [ ] **Step 2: Run RED**

```bash
bun test packages/orchestrator/tests/p1Acceptance.test.ts \
  apps/cli/tests/profilePreset.test.ts apps/cli/tests/cli.test.ts
```

Expected: acceptance wiring and updated skill contract are absent.

- [ ] **Step 3: Wire compile-before-dispatch and docs**

At `waygent run` production preflight: require P0, resolve/snapshot skills,
compile/write manifest, build packets, then dispatch. Expose the P1 blockers in
inspect/explain. Document that exec/fake fixtures cannot produce production
merge-ready until P2.

Add the stable root verification script:

```json
"waygent:skill-evals": "bash skills/waygent/evals/run.sh",
"waygent:native-tests": "cargo test --manifest-path native/kernel/Cargo.toml --workspace",
"waygent:console-check": "cd apps/console && bun test src && bun run build"
```

- [ ] **Step 4: Run the P1 gate and commit**

```bash
bun test packages/contracts/tests packages/context-packer/tests \
  packages/orchestrator/tests apps/cli/tests
bun run typecheck
bun run waygent:skill-evals
git diff --check
git add -- packages/orchestrator/src/orchestrator.ts apps/cli/src/index.ts \
  apps/cli/tests/profilePreset.test.ts apps/cli/tests/cli.test.ts package.json \
  skills/waygent/SKILL.md skills/waygent/README.md skills/waygent/references/commands.md \
  skills/waygent/references/modes.md skills/waygent/references/nl-lexicon.md \
  skills/waygent/evals/check_skill_contract.py docs/operations/waygent.md
git commit -m "test(waygent): close Superpowers method contract phase"
```

Expected: all exit 0 and acceptance reports `P1_ACCEPTED` without claiming
production merge readiness.

## Execution Order

- Sequential: Tasks 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Kill Switches

```text
WAYGENT_METHOD_POLICY=legacy|superpowers-v1
WAYGENT_PRODUCTION_MANIFEST=off|enforce
WAYGENT_DISABLE_INDEPENDENT_REVIEW=1
```

- `legacy` remains non-production and cannot mark merge-ready.
- Disabling independent review blocks the quality gate; it never restores auto-approval.
- A manifest/skill drift freezes the run and requires a new manifest revision.

## Review

Use `code_review.md`. Block P1 for implicit skill discovery, full-spec fallback,
worker self-attestation, auto-approved review, mutable manifest, unbounded packets,
or any compatibility path that can claim production readiness before P2.
