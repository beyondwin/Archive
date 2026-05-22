# Waygent Fixture-Lab Defect Remediation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate the 11 reproducible defects (D-01..D-11) observed during the
2026-05-22 fixture-lab comparison run (`trustworthy_fixture_lab_wg_20260522_200031`),
where waygent dispatched $3.06 of valid claude work and discarded it as
`malformed_result` while costing 3/5 tasks of the plan to complete. The plan
restores worker output trust (parser robustness + auto-retry), restores
plan-body propagation to the Implementer, replaces the brittle
SAFE_COMMAND_STARTS allowlist with a project-aware adapter pattern, hardens the
CLI defaults, fixes the cost-ledger telemetry regression, expands the worker
sandbox `exec` allowlist, and moves run state out of macOS volatile `/var/folders`.

**Architecture:** Keep `waygent.run_state.v2` and `agentlens.event.v3` as the
source of truth. Changes are additive to the existing modules:

- `packages/provider-adapters/src/processAdapters.ts` — worker output parser
  hardening, envelope-level usage extraction, fenced-JSON `json` label
  preference, multi-candidate JSON descent.
- `packages/orchestrator/src/recoveryExecutor.ts` (new) — failure-class →
  recovery-action policy matrix with per-attempt strict-prompt injection.
- `packages/orchestrator/src/planParser.ts` — accept block-list `dependencies`,
  attach pre-yaml prose into `instructions[]`.
- `packages/orchestrator/src/planNormalizer.ts` — replace prefix allowlist with
  `ProjectScriptCatalog` adapter; add risk inference heuristics; emit
  `runway.verification_quality_warning` for trivial verify commands.
- `packages/context-packer/src/taskPacket.ts` — propagate full plan section
  body into `plan_excerpt`; surface `allowed_exec_commands` for self-verify.
- `apps/cli/src/index.ts` — `--run` auto-generation, `--main-model` /
  `--subagent-model` exposed in `--help`, `--profile` preset, default state
  root moved to `~/Library/Application Support/waygent/runs/` (macOS) /
  `$XDG_DATA_HOME/waygent/runs/` (Linux).
- `packages/orchestrator/src/costLedger.ts` — pass-through unchanged; the bug
  is upstream in the provider adapter not populating `usage` metadata.

No new package boundary. No schema bump — all additions are
backward-compatible fields on existing v1/v2 contracts.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/contracts`,
`@waygent/orchestrator`, `@waygent/provider-adapters`,
`@waygent/context-packer`, `@waygent/runway-control`, `apps/cli`. Provider
adapters: claude (`-p --output-format json`), codex. Existing JSONL event
journal at `<run_root>/events.jsonl`, artifact tree under
`<run_root>/artifacts/`.

**Source-Audit Evidence (2026-05-22, re-verified post-design):**

- Run dir: `/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/`
  — confirmed present at audit time (file listing shows
  `events.jsonl` 60 993 B, `state.json` 74 849 B, full `artifacts/` tree).
  Copy fixture bytes into `tests/fixtures/` before macOS rotates
  `/var/folders/.../T/` (the D-05 motivation).
- task_3 stdout artifact: `attempt_task_3_fixture_preparation_and_gradle_injection_1.stdout.txt`
  — **7 884 bytes confirmed via `wc -c`**. Claude returned a
  `{"type":"result","result":"<narrative + \`\`\`json fenced worker_result\`\`\`>",`
  `"usage":{...},"total_cost_usd":3.0589...}` envelope.
  `parseWorkerOutput` (`packages/provider-adapters/src/processAdapters.ts:234–251`)
  rejected it as `missing worker result JSON` →
  `failure_class: "malformed_result"`. The fenced regex
  `/```(?:json)?\s*([\s\S]*?)```/` at line 289 is non-global
  (`.match`, not `.matchAll`) and matched the FIRST triple-backtick
  block in `result` (not always the json-labeled one). Confirmed by
  re-reading the source at audit time.
- task_3 task_packet artifact: `plan_excerpt:
  "Implement Fixture Preparation And Gradle Injection"` (title only — body
  discarded). `allowed_exec_commands` field not present in current
  `buildTaskPacket` output (`packages/context-packer/src/taskPacket.ts:28–46`).
- `metadataFromParsed` (`processAdapters.ts:310–317`) takes only
  `(provider, parsed)` — the original envelope is dropped after
  `unwrapProviderEnvelope` returns just the unwrapped value. Top-level
  `usage`/`modelUsage` are unreachable from this signature; this is the
  D-08 root cause.
- `unwrapProviderEnvelope` (`processAdapters.ts:256–274`) **already**
  searches `value.result`, `value.message`, `value.text`, and
  `value.item.text` — the spec's S2.3 only adds (a) returning the
  envelope alongside the unwrapped result and (b) a depth-≤3 string-leaf
  fallback. Existing path enumeration is preserved.
- `WaygentTaskPacket.context_budget.max_chars` defaults to
  **60 000** chars (`taskPacket.ts:27`, sourced from
  `BuildTaskPacketInput.max_chars`). Earlier drafts mis-quoted as
  12 000; corrected in spec §S4.5.
- `SAFE_COMMAND_STARTS` allowlist confirmed at
  `packages/orchestrator/src/planNormalizer.ts:38–55` (16 entries).
- `FailureClass` union has 29 entries
  (`packages/contracts/src/types.ts:30–59`); matrix in spec §S3.2 lists
  all 29.
- `runWaygent` internal callers: ~27 across 7 test files
  (`diffScope`, `orchestratorRunV2`, `decisions`, `orchestratorApplyE2E`,
  `orchestratorParallel`, `orchestratorRun`, `runCommands`) plus
  `planChain.ts`. The signature stays optional-`run_id?`; only the
  default value changes.
- Comparison analysis: `docs/2026-05-22-waygent-vs-cme-fixture-lab-analysis.md`
  contains 11 defects D-01..D-11 with code references and reproduction commands.

---

## Executable Waygent Task

```yaml waygent-task
id: task_fixture_lab_defect_remediation
title: Remediate fixture-lab 11 defects (D-01..D-11)
dependencies: []
file_claims:
  - path: apps/cli/src/**
    mode: owned
  - path: apps/cli/tests/**
    mode: owned
  - path: packages/provider-adapters/src/**
    mode: owned
  - path: packages/provider-adapters/tests/**
    mode: owned
  - path: packages/orchestrator/src/**
    mode: owned
  - path: packages/orchestrator/tests/**
    mode: owned
  - path: packages/context-packer/src/**
    mode: owned
  - path: packages/context-packer/tests/**
    mode: owned
  - path: packages/contracts/src/**
    mode: owned
  - path: docs/operations/**
    mode: owned
  - path: docs/contracts/**
    mode: owned
risk: high
verify:
  - bun test packages/provider-adapters/tests packages/orchestrator/tests packages/context-packer/tests apps/cli/tests
  - bun run waygent:scenarios
  - bun run check
  - git diff --check
instructions:
  - Read docs/superpowers/plans/2026-05-22-waygent-fixture-lab-defect-remediation.md Task 1 through Task 7.
  - Use docs/superpowers/specs/2026-05-22-waygent-fixture-lab-defect-remediation-design.md as the source-audited design spec.
  - Use the actual failed-run artifacts at /var/folders/01/.../waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/ as regression fixtures (copy stdout text into tests/fixtures/ rather than depending on volatile tmp paths).
  - Preserve agentlens.event.v3 envelope; do not bump waygent.run_state.v2.
  - Keep changes backward-compatible (additive optional fields only).
```

---

## Source Design

- `docs/superpowers/specs/2026-05-22-waygent-fixture-lab-defect-remediation-design.md`

---

## Task 1: Worker output parser hardening + auto-retry policy (P0 — D-09, D-10)

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts`
- Create: `packages/orchestrator/src/recoveryExecutor.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts` (wire retries)
- Create: `packages/provider-adapters/tests/fixtures/claude_task_3_real.stdout.txt`
  (copy from the failed run artifact)
- Create: `packages/provider-adapters/tests/parseWorkerOutput.test.ts`
- Create: `packages/orchestrator/tests/recoveryExecutor.test.ts`

**Goal:** Stop dropping $3+ of claude work because the parser matched the wrong
code fence. Make `malformed_result` survivable via one strict-prompt retry.

### Step 1.1 — Write failing parser regression test first

- [ ] Copy the literal bytes of
  `/var/folders/.../waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/artifacts/provider/attempt_task_3_*.stdout.txt`
  into
  `packages/provider-adapters/tests/fixtures/claude_task_3_narrative_then_json.stdout.txt`.
- [ ] Write `tests/parseWorkerOutput.test.ts`:
  ```ts
  test("claude narrative wrapping fenced json worker_result is extracted", async () => {
    const fixture = readFileSync(".../claude_task_3_narrative_then_json.stdout.txt", "utf8");
    const result = normalizeProcessOutput("claude", "task_3_...", "cand_1", {
      exitCode: 0, stdout: fixture, stderr: "", timedOut: false,
      startedAt: "...", completedAt: "..."
    });
    expect(result.worker.status).toBe("completed");
    expect(result.worker.failure_class).toBeUndefined();
    expect(result.worker.changed_files).toContain("scripts/source-matching-fixtures.mjs");
  });
  ```
- [ ] Run `bun test packages/provider-adapters/tests/parseWorkerOutput.test.ts` —
  test MUST fail with the current parser ("missing worker result JSON").

### Step 1.2 — Harden `parseJsonText` to prefer `json`-labeled fences and try all candidates

- [ ] In `processAdapters.ts`, replace the body of `parseJsonText` so that it:
  1. Tries direct `JSON.parse(trimmed)` first.
  2. Collects ALL fenced blocks via global regex
     `/```(\w+)?\s*([\s\S]*?)```/g`.
  3. Tries fenced blocks in priority order: `json` label first, then
     unlabeled, then any other language (e.g., `yaml`/`bash`).
  4. For each fenced block, calls `tryParseJson` and validates with
     `isWorkerResultCandidate`. Returns the first match.
  5. Final fallback: scans for ALL balanced `{...}` spans (greedy + nested
     brace counting), tries each, returns the first that satisfies
     `isWorkerResultCandidate`.
- [ ] Loosen `isWorkerResultCandidate` to require `status` AND
  (`changed_files` OR `summary`) at the top level (so envelope rejection still
  works, but a legitimate worker_result is never rejected for missing one
  optional field).

### Step 1.3 — Make `unwrapProviderEnvelope` recursive (additive on top of existing paths)

- [ ] Source audit (`processAdapters.ts:256–274`) confirms `result`,
  `message`, `text`, and `item.text` are **already searched** in that
  order. Do NOT replace this enumeration — extend it.
- [ ] Add a depth-≤3 string-leaf fallback: after the four direct paths
  miss, walk the envelope tree to collect string-typed leaves at depth
  ≤ 3 and call `parseJsonText` on each. First worker-result-shaped match
  wins. Bounded depth keeps the scan O(envelope-size) and avoids cycles.
- [ ] Change the return type from `unknown` to
  `{ unwrapped: unknown; envelope: unknown | null }` and update the
  single caller in `parseWorkerOutput` (one-line destructure shim).
  This preserves the original envelope so Task 5 can extract top-level
  `usage`/`modelUsage` from it.

### Step 1.4 — Add `recoveryExecutor` with failure-class policy matrix

- [ ] Create `recoveryExecutor.ts` exporting `nextRecoveryAction(failure_class,
  attempt_count): "retry_with_strict_prompt" | "retry_with_evidence" |
  "request_decision" | "halt"`.
- [ ] Policy matrix (constants, not config):
  ```ts
  const POLICY: Record<FailureClass, { action: string; max_attempts: number }> = {
    malformed_result: { action: "retry_with_strict_prompt", max_attempts: 2 },
    verification_failed: { action: "retry_with_evidence", max_attempts: 3 },
    timeout: { action: "request_decision", max_attempts: 1 },
    adapter_crashed: { action: "retry_with_strict_prompt", max_attempts: 1 },
    permission_denied: { action: "request_decision", max_attempts: 1 },
    // ... see spec § R1
  };
  ```
- [ ] On `retry_with_strict_prompt`, inject a system-prompt suffix:
  ```
  PRIOR ATTEMPT FAILED: failure_class=<class>; summary=<truncated summary>.
  Respond with ONLY the runway.worker_result.v1 JSON object as a single
  fenced ```json block. No narrative before or after the fence.
  ```

### Step 1.5 — Wire retries into taskExecutor

- [ ] In `taskExecutor.ts`, when `worker.status === "failed"` or
  `worker.failure_class` is set, call `nextRecoveryAction`. If
  `retry_with_*`, re-dispatch with the prior_failure context appended to the
  task_packet (new optional field `task_packet.previous_failures[]`).
- [ ] Emit `agentlens.event.v3` of `event_type: "runway.recovery_attempt"`
  with `payload: { failure_class, recovery_action, attempt_number,
  max_attempts }` for each retry.

### Step 1.6 — Verify

- [ ] `bun test packages/provider-adapters/tests/parseWorkerOutput.test.ts`
  passes.
- [ ] `bun test packages/orchestrator/tests/recoveryExecutor.test.ts` covers
  each failure_class entry in the policy matrix.
- [ ] Replay scenario: `bun run waygent:scenarios` adds a new scenario
  `claude_narrative_wrapped_worker_result` that round-trips the fixture and
  asserts task COMPLETE.

---

## Task 2: Propagate plan body into task_packet `plan_excerpt` and `instructions` (P0 — D-06)

**Files:**
- Modify: `packages/orchestrator/src/planParser.ts`
- Modify: `packages/orchestrator/src/planNormalizer.ts` (use existing
  `extractInstructionLines`)
- Modify: `packages/context-packer/src/taskPacket.ts`
- Create: `packages/orchestrator/tests/planParser.bodyPropagation.test.ts`
- Create: `packages/context-packer/tests/taskPacket.planExcerpt.test.ts`

**Goal:** Stop sending the Implementer just the task title. Pass the full
section body so step-by-step instructions reach the worker.

### Step 2.1 — Failing test for plan-body capture

- [ ] In `planParser.bodyPropagation.test.ts`, fixture a plan with a yaml
  waygent-task block preceded by 80 lines of `### Task 3: ...` prose with
  three `Step N:` subsections. Assert that the parsed
  `ParsedWaygentTask.instructions` contains all `Step N:` lines.
- [ ] Should currently fail (parser only reads inside the yaml fence).

### Step 2.2 — Capture pre-yaml prose during native-mode parse

- [ ] In `planParser.ts` `parseWaygentPlan`, before iterating yaml blocks,
  record the markdown offset of each block's opening fence.
- [ ] For each yaml block, slice the prose text from the most recent
  `### Task N:` (or `## Task N:`) heading up to the yaml fence opening. If
  the yaml block's `instructions:` field is absent or empty, replace it with
  the captured prose (after passing through `extractInstructionLines` from
  planNormalizer for git-command stripping). Cap at 160 lines (existing
  limit).
- [ ] Add new optional CLI flag `--inherit-plan-prose <on|off>` (default
  `on`) in `apps/cli/src/index.ts`; thread to `runWaygent` options.

### Step 2.3 — Expand `task_packet.plan_excerpt` to include section body

- [ ] In `taskPacket.ts`, change `plan_excerpt` builder to concatenate
  `task.title + "\n\n" + task.instructions.join("\n")`.
- [ ] Cap the result at `min(maxChars * 0.4, 12_000)` chars (the actual
  `BuildTaskPacketInput.max_chars` default is **60 000**, not 12 000 as
  the spec's earlier draft stated — see `taskPacket.ts:27`). The
  `min(..., 12_000)` hard cap preserves the original design intent of
  leaving ample headroom for `spec_excerpt`, `decisions`, and
  `previous_failures` even when callers use a generous `max_chars`.
- [ ] On truncation, append ` [truncated]` and set
  `task_packet.plan_body_truncated: true`. On full inclusion, set
  `plan_body_truncated: false`.
- [ ] `plan_body_truncated` is additive, optional, and lives next to
  the existing `context_budget` object — no schema bump.

### Step 2.4 — Verify

- [ ] `bun test packages/orchestrator/tests/planParser.bodyPropagation.test.ts`
  passes.
- [ ] `bun test packages/context-packer/tests/taskPacket.planExcerpt.test.ts`
  passes.
- [ ] Re-replay scenario in `bun run waygent:scenarios` — at least one
  scenario must include the prose-rich plan and assert that
  `task_packet.plan_excerpt` length > task.title length + 50.

---

## Task 3: Plan adapter pattern with project script catalog and risk inference (P0 — D-01, D-07)

**Files:**
- Create: `packages/orchestrator/src/planAdapters/index.ts`
- Create: `packages/orchestrator/src/planAdapters/projectScriptCatalog.ts`
- Create: `packages/orchestrator/src/planAdapters/riskInference.ts`
- Modify: `packages/orchestrator/src/planNormalizer.ts` (delegate to catalog
  + inference; preserve `normalizeWaygentPlanInput` entry signature)
- Modify: `apps/cli/src/index.ts` (`--plan-adapter`, `--unsafe-verification`,
  `--reject-trivial-verify` flags)
- Create: `packages/orchestrator/tests/projectScriptCatalog.test.ts`
- Create: `packages/orchestrator/tests/riskInference.test.ts`
- Create: `packages/orchestrator/tests/planNormalizer.fixtureLab.test.ts`

**Goal:** Accept the fixture-lab plan (and any FixThis/superpowers plan with
`npm run <domain-script>` verify) without forcing the user to hand-author a
trivial `printf` workaround. Detect and warn on trivial verify when adopted.

### Step 3.1 — Failing tests for fixture-lab plan acceptance

- [ ] `planNormalizer.fixtureLab.test.ts`: feed the literal fixture-lab plan
  bytes (copy
  `/Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md`
  into `tests/fixtures/fixture_lab_plan.md`) plus a fake `package.json`
  with `"scripts": { "source-matching:fixtures:test": "node --test ..." }`.
  Assert normalization SUCCESS (no throw) and that the 5 normalized tasks
  inherit verify commands from the plan body.
- [ ] Should currently throw `cannot normalize superpowers implementation
  plan ... missing safe verification commands`.

### Step 3.2 — `ProjectScriptCatalog` adapter

- [ ] In `projectScriptCatalog.ts`, export
  `buildProjectScriptCatalog(workspace: string): ProjectScriptCatalog` that:
  1. Reads `<workspace>/package.json` `scripts.*` → catalog all `npm run
     <name>` / `pnpm run <name>` / `bun run <name>` / `yarn <name>` commands.
  2. Reads `<workspace>/Makefile` if present → catalog `make <target>`.
  3. Reads `<workspace>/pyproject.toml` `[tool.poetry.scripts]` and
     `[project.scripts]` → catalog matching script names.
  4. Returns `{ commands: Set<string>, sources: Record<string, "npm" | "make"
     | ...> }`.
- [ ] Replace `SAFE_COMMAND_STARTS` lookup in `planNormalizer.ts`
  `isSafeVerificationCommand` with: hard-coded prefix list (kept for build
  tools that don't appear in package.json: `bun test`, `cargo test`,
  `git diff --check`, etc.) UNION catalog membership.
- [ ] Add CLI flag `--unsafe-verification` that bypasses the allowlist
  entirely (for lab-only use; emit `runway.unsafe_verification_enabled`
  warning event).

### Step 3.3 — Risk inference heuristics

- [ ] In `riskInference.ts`, export `inferRiskLevel(section: { title: string;
  body: string; file_claims: FileClaim[] }): RiskLevel`. Algorithm:
  - `high` if body matches keywords (case-insensitive):
    `/\b(schema migration|database migration|public API|breaking change|production)\b/`.
  - `high` if file_claims.length > 10 OR any claim path matches
    `/\b(migration|schema|public-api|production)\b/`.
  - `medium` if file_claims contain shared/cross-package paths (more than
    one top-level dir).
  - `low` otherwise.
- [ ] Use this in `planNormalizer.ts` instead of the current hard-coded
  `risk: "high"`. Persist the chosen risk + reason as
  `normalized_plan.diagnostics[]` entries.

### Step 3.4 — Trivial-verify guard

- [ ] In `planNormalizer.ts`, after extracting verify commands, scan each
  command. If a task's ENTIRE verify list consists of trivial commands
  (`printf`, `true`, `:`, `echo`), or if any single command does not
  reference any file in the task's `file_claims`, emit
  `runway.verification_quality_warning` event with `{ task_id, verify, why
  }`.
- [ ] Add CLI flag `--reject-trivial-verify` (default off). When set, the
  warning becomes a normalizer error and halts the run before dispatch.

### Step 3.5 — Verify

- [ ] `bun test packages/orchestrator/tests/projectScriptCatalog.test.ts` —
  covers package.json/Makefile/pyproject parsing and merge order.
- [ ] `bun test packages/orchestrator/tests/riskInference.test.ts` — 6+
  table-driven cases.
- [ ] `bun test packages/orchestrator/tests/planNormalizer.fixtureLab.test.ts`
  passes (normalization SUCCESS).

---

## Task 4: CLI surface fixes (P0/P1 — D-02, D-03, D-04)

**Files:**
- Modify: `apps/cli/src/index.ts`
- Modify: `packages/orchestrator/src/orchestrator.ts` (auto run_id derivation)
- Modify: `packages/orchestrator/src/planParser.ts` (block-list dependencies)
- Create: `apps/cli/tests/runIdAutoGen.test.ts`
- Create: `apps/cli/tests/profilePreset.test.ts`
- Create: `packages/orchestrator/tests/planParser.deps.test.ts`

**Goal:** Eliminate "run_id_already_exists" footgun, eliminate
inline-list-only dependencies footgun, document the model flags that already
exist but are hidden, and add the `--profile` preset to reduce default Opus
cost.

### Step 4.1 — `--run` auto-generation (D-03)

- [ ] In `apps/cli/src/index.ts` `runCli`, when `parsed.flags.run` is
  unset and command is `run`/`run-chain`/`demo`, derive an auto run_id:
  `<plan_basename_slug>_<YYYYMMDD_HHMMSS>` where slug strips date prefixes,
  punctuation, and extension. Use ISO-like timestamp without separators.
- [ ] In `orchestrator.ts` `runWaygent`, KEEP `options.run_id?` as
  OPTIONAL in the signature (do not break the ~25+ existing internal
  callers in `packages/orchestrator/tests/` and
  `packages/orchestrator/src/planChain.ts` — audit-confirmed: 24 calls
  across 7 test files + 1 in planChain + 1 internal demo wrapper).
  REPLACE the literal `?? "run_demo"` fallback at
  `packages/orchestrator/src/orchestrator.ts:75` with a call to the
  same `deriveAutoRunId(planPath, Date.now())` helper used by the CLI.
  The "run_demo" magic constant disappears entirely; tests that
  currently pass `run_id: "run_demo"` continue to work because they
  pass an explicit value.
- [ ] Export `deriveAutoRunId` from a new shared module
  `packages/orchestrator/src/runIdDerivation.ts` so the CLI and the
  orchestrator share one implementation (avoid drift).
- [ ] **Collision retry lives only in the CLI**, not in `runWaygent`.
  `hasExistingRunEvidence` (`orchestrator.ts:471–478`) throws
  `run_id_already_exists` synchronously during `runWaygent` setup; the
  orchestrator does not retry internally to keep its post-resolve
  contract clean. The CLI wraps `runWaygent` in a 9-retry loop that
  appends `_2`, `_3`, ... to the derived id on collision (spec §S7.1
  shows the snippet).
- [ ] `apps/cli/tests/runIdAutoGen.test.ts`: (a) two consecutive `runCli`
  calls with no `--run` produce distinct run_ids (timestamp differs by
  ≥ 1s OR test uses a fake clock injected via test-only param);
  (b) injected `hasExistingRunEvidence → true` for the first attempt
  triggers `_2` suffix retry and succeeds.
- [ ] `packages/orchestrator/tests/runIdDerivation.test.ts`: covers the
  slug derivation (date-prefix strip, punctuation→underscore,
  case-fold), timestamp formatting, and uniqueness across rapid
  successive calls (Date.now() collision: append a 4-digit counter at
  the *derivation* layer to defeat sub-second collisions before they
  reach the file system).

### Step 4.2 — Block-list `dependencies` (D-02)

- [ ] In `planParser.ts`, change the `dependencies` field handling: detect
  `dependencies:` followed by inline list OR by subsequent `  - <item>`
  lines (use the same `readStringList` already used for `verify`).
- [ ] `planParser.deps.test.ts` — fixtures for both inline `dependencies:
  [task_1, task_2]` AND block form
  ```yaml
  dependencies:
    - task_1
    - task_2
  ```
  Both must parse identically.

### Step 4.3 — Expose `--main-model` / `--subagent-model` in `--help` (D-04)

- [ ] In `apps/cli/src/index.ts` `commandUsage.run`, change to:
  ```
  waygent run --plan <waygent-task.md> [--spec <design.md>] [--provider codex|claude|fake] [--execution-mode multi-agent|single-agent] [--plan-preflight off|deterministic|full] [--main-model <name>] [--subagent-model <name>] [--main-reasoning low|medium|high|xhigh] [--subagent-reasoning low|medium|high|xhigh] [--profile cost-saver|balanced|max-quality] [--run <id>] [--budget-cap <usd>] [--budget-action warn|pause|off]
  ```

### Step 4.4 — `--profile` preset (D-04)

- [ ] Add `--profile cost-saver|balanced|max-quality` flag. When set, it
  overrides the provider-default profile but is itself overridden by
  explicit `--main-model` / `--subagent-model` (flags
  `apps/cli/src/index.ts:81–84` already parse those values; only the
  help text is missing — see Step 4.3).
- [ ] Presets for `provider=claude`:
  - `cost-saver`: main=sonnet(medium), sub=haiku(low)
  - `balanced` (new default profile applied **when** `--provider claude`
    is selected): main=opus(high), sub=sonnet(medium)
  - `max-quality`: main=opus(high), sub=opus(high)
- [ ] Change `resolveCliProfile` (`apps/cli/src/index.ts:72–86`) so that
  for `--provider claude` the default becomes the `balanced` preset
  (was: implicit `main=opus, sub=opus` via downstream defaults). The
  `defaultProvider` for `waygent run` remains `codex`
  (`apps/cli/src/index.ts:73`); this Step does NOT change which
  provider is selected when `--provider` is omitted. The change is
  scoped strictly to the model/reasoning shape chosen *after* a
  provider is fixed.
- [ ] `apps/cli/tests/profilePreset.test.ts` — 3 cases per preset;
  explicit `--main-model`/`--subagent-model` beats preset;
  `--provider codex` without `--profile` stays at the current codex
  defaults (no behavior change for codex users).

### Step 4.5 — Echo planned models and budget at dispatch start

- [ ] Before the first task dispatch, emit
  `runway.dispatch_plan_echoed` event with `{ profile, plan_count, budget,
  expected_cost_estimate }`. (Estimate is informational: assume average
  `output_tokens=20000` per task at provider-default rate.)
- [ ] Stderr echo single line (matches kws-CME parser pattern):
  `[waygent] Parsed: <N> task(s), main=<model>(<reasoning>),
  sub=<model>(<reasoning>), budget=<usd or off>.`

### Step 4.6 — Verify

- [ ] `bun test apps/cli/tests/runIdAutoGen.test.ts` passes.
- [ ] `bun test apps/cli/tests/profilePreset.test.ts` passes.
- [ ] `bun test packages/orchestrator/tests/planParser.deps.test.ts` passes.
- [ ] `bun run check` — `waygent help run` output includes all flags above.

---

## Task 5: Cost ledger telemetry — extract envelope-level usage (P1 — D-08)

**Files:**
- Modify: `packages/provider-adapters/src/processAdapters.ts`
  (`metadataFromParsed`, `usageFromEvidence`, `usageSourceFromEvidence`)
- Modify: `packages/provider-adapters/src/types.ts` (extend
  `ProviderRunMetadata` if needed — additive)
- Create: `packages/provider-adapters/tests/usageExtraction.test.ts`
- Modify: `apps/cli/src/index.ts` `costRun` (warn-on-zero output)

**Goal:** The cost ledger is structurally correct; the regression is upstream
in `usageFromEvidence` which reads `evidence.usage` while claude `--output-format
json` puts usage at the TOP of the envelope. Fix the extraction; `costLedger.ts`
needs no change.

### Step 5.1 — Failing test for envelope-level usage

- [ ] `tests/usageExtraction.test.ts`: feed the literal claude task_3 stdout
  fixture (already added in Task 1). Assert that the returned
  `ProviderAdapterRunResult.metadata.usage` is
  `{input_tokens: 46, output_tokens: 29302, cached_read_tokens: 2758848,
  cached_write_tokens: 80976}` and `usage_source: "provider_json"`.
- [ ] Should currently fail (returns null / unknown).

### Step 5.2 — Extract from envelope, not just nested evidence

- [ ] In `processAdapters.ts` `normalizeProcessOutput`, after `parseWorkerOutput`,
  ALSO parse the outer envelope. If outer envelope has top-level `usage` key
  (claude shape: `usage.input_tokens`, `usage.output_tokens`,
  `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`),
  use that, mapping:
  - `evidence.usage.input_tokens` ← `envelope.usage.input_tokens`
  - `evidence.usage.output_tokens` ← `envelope.usage.output_tokens`
  - `evidence.usage.cached_read_tokens` ← `envelope.usage.cache_read_input_tokens`
  - `evidence.usage.cached_write_tokens` ← `envelope.usage.cache_creation_input_tokens`
- [ ] If the worker_result's own `evidence.usage` ALSO exists, prefer
  envelope (provider-attested) over worker self-report; record
  `usage_source: "provider_json"`.
- [ ] If neither present, `usage_source: "missing_in_provider_output"` (was
  `"unknown"` — disambiguates from never-attempted).

### Step 5.3 — Extract model attestation from envelope too

- [ ] Claude envelope has `modelUsage` map keyed by model name (e.g.,
  `"claude-opus-4-7": {...}`). If present, populate
  `actual_model: { model: <first key>, reasoning: null, source:
  "provider_json" }` when worker self-report is missing.

### Step 5.4 — Warn-on-zero output in `waygent cost`

- [ ] In `apps/cli/src/index.ts` `costRun` (delegating to
  `packages/orchestrator/src/runCommands.ts costRun`): if
  `ledger.totals.input_tokens + output_tokens === 0` AND
  `ledger.totals.dispatches > 0`, prepend stderr line:
  `WARN: cost ledger has 0 token usage across <N> dispatches. Provider
  adapter may not be parsing usage block. Check
  artifacts/provider/*.stdout.txt for top-level "usage" key.`
- [ ] Add CLI flag `--require-cost-data` to `waygent run`. When set and any
  dispatch finishes with `usage_source ∈ {"missing_in_provider_output",
  "unknown"}`, fail-fast after dispatch with `cost_data_missing` error.

### Step 5.5 — Verify

- [ ] `bun test packages/provider-adapters/tests/usageExtraction.test.ts` —
  3+ fixtures (claude json, claude stream-json [if any], codex equivalent).
- [ ] `bun run waygent:scenarios` — assert no scenario regresses to
  `usage_source: "unknown"`.

---

## Task 6: Worker sandbox `allowed_exec_commands` from project catalog (P1 — D-11)

**Files:**
- Modify: `packages/context-packer/src/taskPacket.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts` (thread
  `allowed_exec_commands` through dispatch)
- Modify: `packages/provider-adapters/src/processAdapters.ts`
  (`buildProviderPrompt` — surface the allowlist to claude)
- Create: `packages/context-packer/tests/taskPacket.execAllowlist.test.ts`
- Modify: `packages/orchestrator/src/planAdapters/index.ts` (re-export
  `ProjectScriptCatalog` from Task 3)

**Goal:** Stop blocking `node --test scripts/*` so workers can run their own
verify before reporting completion. Sandbox stays read/write-protected;
exec-policy expands narrowly to project-known commands.

### Step 6.1 — Failing test: allowlist must include catalog commands

- [ ] `taskPacket.execAllowlist.test.ts`: build a task_packet for a workspace
  with `"scripts": {"test:lab": "node --test scripts/*"}`. Assert
  `task_packet.allowed_exec_commands` is non-null and includes
  `"npm run test:lab"` and `"node --test scripts/*"` (verify command).

### Step 6.2 — Populate `allowed_exec_commands`

- [ ] In `taskPacket.ts`, when constructing the packet, call
  `buildProjectScriptCatalog(workspace)` (from Task 3). Set
  `allowed_exec_commands` to the union of:
  - All catalog commands (e.g., `npm run *`, `make *`).
  - All `task.verification_commands` (the verify list already in the packet).
  - Read-only utilities: `ls`, `cat`, `head`, `tail`, `grep`, `git status`,
    `git diff`, `git log --oneline -n 20`, `node -e "..."`, `node --test
    ...`.
- [ ] Schema-additive: `allowed_exec_commands: string[] | null` (already
  exists per artifact; widen to typed list).

### Step 6.3 — Surface allowlist in provider prompt

- [ ] In `processAdapters.ts` `buildProviderPrompt`, add a line:
  `"You may invoke these commands during self-verification:
  <allowed_exec_commands joined by '; '>. Other commands will be denied."`
- [ ] Worker now self-verifies BEFORE returning `status: completed`, which
  reduces the verify-theater problem (Task 3 Step 3.4).

### Step 6.4 — Emit denial WARN event

- [ ] In `processAdapters.ts`, after parsing claude stdout, if
  `permission_denials[]` is non-empty (envelope-level field), emit
  `runway.worker_permission_denied` event per denial with `{ task_id,
  attempted_command, suggested_allowlist_entry }`.
- [ ] Suggested allowlist entry: extract first token of the denied command;
  suggest adding it to project `package.json scripts` or to
  `--unsafe-verification` for one-off use.

### Step 6.5 — Verify

- [ ] `bun test packages/context-packer/tests/taskPacket.execAllowlist.test.ts`
  passes.
- [ ] Replay the task_3 scenario from Task 1's fixture (with the fix
  applied): worker should now successfully run `node --test` and return
  `status: completed` on first attempt, no permission_denials emitted.

---

## Task 7: Persistent state root (P1 — D-05)

**Files:**
- Modify: `apps/cli/src/index.ts` (`defaultRunRoot` consumer)
- Modify: `packages/orchestrator/src/orchestrator.ts` (`defaultRunRoot`
  export)
- Modify: `packages/orchestrator/src/orphanRuns.ts` (recognize both old and
  new roots during transition)
- Create: `docs/operations/state-root-migration.md`
- Create: `packages/orchestrator/tests/defaultRunRoot.test.ts`

**Goal:** Move waygent run state off macOS volatile `/var/folders/.../T/` so
forensic analysis of failed runs survives reboot or tmp cleanup.

### Step 7.1 — Failing test for new default location

- [ ] `defaultRunRoot.test.ts`: on darwin, expect path matching
  `~/Library/Application Support/waygent/runs`. On linux, expect
  `$XDG_DATA_HOME/waygent/runs` or `~/.local/share/waygent/runs`. On other
  OSes, fallback to `os.tmpdir()/waygent-runs` with a stderr WARN.

### Step 7.2 — Update `defaultRunRoot`

- [ ] In `orchestrator.ts`, change `defaultRunRoot()` from `join(tmpdir(),
  "waygent-runs")` to:
  ```ts
  export function defaultRunRoot(): string {
    if (process.platform === "darwin") {
      return join(homedir(), "Library", "Application Support", "waygent", "runs");
    }
    if (process.platform === "linux") {
      const xdg = process.env.XDG_DATA_HOME;
      return xdg ? join(xdg, "waygent", "runs")
                 : join(homedir(), ".local", "share", "waygent", "runs");
    }
    process.stderr.write("WARN: unsupported platform; using tmpdir for waygent runs (volatile)\n");
    return join(tmpdir(), "waygent-runs");
  }
  ```
- [ ] Auto-create the directory on first use (use `mkdirSync(root,
  {recursive: true})`).

### Step 7.3 — Backward-compat orphan detection

- [ ] In `orphanRuns.ts`, when `--root` is not specified, scan BOTH the
  new default root AND the old `tmpdir()/waygent-runs/` location. List
  any old-location runs in the orphans report with a `migration_suggested:
  true` flag.

### Step 7.4 — Migration docs

- [ ] `docs/operations/state-root-migration.md` documents:
  - The location change rationale (volatility risk).
  - How to copy old runs: `cp -r "$TMPDIR/waygent-runs/." "<new default>/"`.
  - Backward compat: `--root <path>` still honored for both `waygent run`
    and `waygent orphans`.

### Step 7.5 — Verify

- [ ] `bun test packages/orchestrator/tests/defaultRunRoot.test.ts` passes.
- [ ] `waygent orphans --root <old_tmp_path>` correctly lists old-root runs.
- [ ] `waygent run --plan <plan>` writes under the new path on macOS.

---

## Cross-cutting verification (after Task 7)

Run from `/Users/kws/source/private/Archive`:

```bash
bun test packages/provider-adapters/tests packages/orchestrator/tests packages/context-packer/tests apps/cli/tests
bun run waygent:scenarios
bun run check
git diff --check
```

End-to-end replay (the original failed run, now expected to succeed):

```bash
waygent run \
  --plan /Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md \
  --spec /Users/kws/source/android/FixThis/docs/superpowers/specs/2026-05-20-trustworthy-source-matching-local-fixture-lab-design.md \
  --provider claude \
  --profile balanced \
  --execution-mode multi-agent \
  --plan-preflight deterministic
# (no --run needed — auto-generated; no yaml waygent-task adapter needed;
#  no printf verify needed; no $3 lost on malformed_result.)
```

Expected outcome: 5/5 tasks COMPLETE, real `node --test` runs in worker
sandbox, `waygent cost --last` shows non-zero token usage with
`usage_source: "provider_json"`, total ≤ ~$0.50 with `balanced` preset.

---

## Non-goals (out of scope for this plan)

- **Method audit framework** (kws-CME `validate_method_audit.py` parity) —
  deferred; spec-§S5 mentions but doesn't implement.
- **Polite-stop antipattern guard** for reviewer skip — deferred; tracked
  separately in `2026-05-22-waygent-runtime-improvements-implementation.md`.
- **Sub-agent per-call cost split** — deferred (D-04 step 4.5 echoes
  aggregate cost; per-sub-agent split needs `ProviderRole`-aware ledger
  bucketing already partially built in `costLedger.by_role`).
- **Multi-plan chain validation** — separate experiment.
- **Plan adapter externalization** (`plan-adapters/superpowers.ts` as a
  npm package) — Task 3 keeps adapter pattern internal; external boundary
  deferred.

## Risk register

| Risk | Mitigation |
|------|------------|
| Task 1 regex change accidentally accepts an empty fenced block | `isWorkerResultCandidate` strict check on `status` field required |
| Task 2 plan prose injection overflows token budget | `extractInstructionLines` cap (160 lines) preserved; new `plan_body_truncated` flag |
| Task 3 `ProjectScriptCatalog` false-positives on hostile `package.json` | The catalog only EXPANDS the allowlist; it doesn't relax `forbidden_write_globs`. Path-write protection remains. |
| Task 4 `--profile balanced` default changes existing CI cost expectations | Documented in `docs/operations/state-root-migration.md` (rename to `cli-defaults-changes.md` if cleaner); release notes call this out. |
| Task 5 envelope schema variance between claude versions | Tests cover `--output-format json` (current). `stream-json` parsing requires separate fixture; document as known limitation. |
| Task 7 macOS default `~/Library/Application Support/waygent/runs` requires sandbox entitlement on signed binaries | waygent CLI is unsigned bun-exec; non-issue today. Document for future signing. |
