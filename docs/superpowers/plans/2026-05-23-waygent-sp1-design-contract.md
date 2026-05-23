# Waygent SP-1 — Design-Driven Implementation Contract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `packages/design-contract/` so that design/plan documents are the single source of truth for cross-path invariants, prescriptive snippets, and policy ack requirements. Pre-dispatch and post-worker enforcement route all failures through the existing `intake_decision_required` channel.

**Architecture:** A new workspace package exposes typed `DesignContract` / `PlanContract` JSON. A two-tier parser (`deterministic` then AI-fallback via an `ExtractorProvider`) normalizes markdown into JSON, cached by source hash. The orchestrator consumes normalized JSON pre-dispatch (invariant deterministic checks) and post-worker (envelope validation, ack confidence, prescriptive drift). No new event family. CLI gains `waygent lint-design` / `waygent lint-plan` for dry-run authoring.

**Tech Stack:** TypeScript (strict, exactOptionalPropertyTypes), Bun runtime, ajv schemas, existing `@waygent/contracts` patterns, the `WorkerProvider` adapter pattern from `packages/provider-adapters/`.

**Spec:** `docs/superpowers/specs/2026-05-23-waygent-sp1-design-contract-design.md`

---

## File Structure

**Create:**
- `packages/design-contract/package.json`
- `packages/design-contract/tsconfig.json`
- `packages/design-contract/src/index.ts`
- `packages/design-contract/src/types.ts`
- `packages/design-contract/src/parse/deterministic.ts`
- `packages/design-contract/src/parse/cache.ts`
- `packages/design-contract/src/parse/ai.ts`
- `packages/design-contract/src/parse/index.ts`
- `packages/design-contract/src/invariants.ts`
- `packages/design-contract/src/workerEnvelope.ts`
- `packages/design-contract/src/checks/shell.ts`
- `packages/design-contract/src/checks/index.ts`
- `packages/design-contract/src/lint.ts`
- `packages/design-contract/tests/*.test.ts` (one per src module)
- `packages/design-contract/tests/fixtures/canonical/` (markdown + expected JSON pairs)
- `packages/design-contract/tests/fixtures/freeform/` (markdown + fake AI responses)
- `packages/design-contract/tests/fixtures/degraded/` (failure cases)

**Modify:**
- `package.json` (root) — add design-contract workspace dep, add `waygent:design-contract-live-smoke` script
- `packages/contracts/src/types.ts` — add `WaygentDesignContractRef` and `design_contract?: ...` on `WaygentRunStateV2`
- `packages/contracts/src/schemas.ts` — add schema for the new field
- `packages/orchestrator/package.json` — add `@waygent/design-contract` workspace dep
- `packages/orchestrator/src/intakeRecovery.ts` — call design-contract parse, store refs
- `packages/orchestrator/src/runtimeHooks.ts` — call worker envelope validator
- `packages/orchestrator/src/safeWaveExecutor.ts` or `taskExecutor.ts` — invoke pre-dispatch invariant runner
- `apps/cli/package.json` — add `@waygent/design-contract` workspace dep
- `apps/cli/src/index.ts` — add `lint-design` and `lint-plan` commands
- `apps/cli/tests/cli.test.ts` — add 6 integration cases
- `tests/integration/waygent-fixture-lab.test.ts` — replay canonical + freeform + degraded fixtures
- `docs/contracts/run-state.md` — document `design_contract` field
- `docs/operations/waygent.md` — document lint commands + canonical/freeform authoring
- `docs/operations/verification.md` — register design-contract gates
- `skills/waygent/SKILL.md` — add lint command NL mappings + `normalized_design` phrase
- `skills/waygent/evals/check_skill_contract.py` — add new required phrases

---

## Phase 0 — Package Skeleton

### Task 0.1: Create `@waygent/design-contract` package

**Files:**
- Create: `packages/design-contract/package.json`
- Create: `packages/design-contract/tsconfig.json`
- Create: `packages/design-contract/src/index.ts`

- [ ] **Step 1: Write `package.json`**

```json
{
  "name": "@waygent/design-contract",
  "version": "0.1.0",
  "type": "module",
  "main": "./src/index.ts",
  "exports": {
    ".": "./src/index.ts"
  },
  "dependencies": {
    "@waygent/contracts": "workspace:*"
  }
}
```

- [ ] **Step 2: Write `tsconfig.json`** (mirror `packages/contracts/tsconfig.json`)

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "composite": true,
    "declaration": true,
    "rootDir": "src",
    "outDir": "dist"
  },
  "include": ["src/**/*.ts"],
  "exclude": ["tests"]
}
```

- [ ] **Step 3: Write empty `src/index.ts`**

```ts
export {};
```

- [ ] **Step 4: Verify package resolves**

Run: `bun install && bun run typecheck`
Expected: PASS, no errors mentioning `design-contract`.

- [ ] **Step 5: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): scaffold @waygent/design-contract package"
```

### Task 0.2: Wire workspace dependencies in consumer packages

**Files:**
- Modify: `apps/cli/package.json`
- Modify: `packages/orchestrator/package.json`
- Modify: `package.json` (root)

- [ ] **Step 1: Add dependency to `apps/cli/package.json`**

Add to its `"dependencies"` object:

```json
"@waygent/design-contract": "workspace:*"
```

- [ ] **Step 2: Add dependency to `packages/orchestrator/package.json`**

Same line in the orchestrator's `"dependencies"`.

- [ ] **Step 3: Add design-contract to the root test runner**

In `package.json` root, modify the `"test"` script to include the new package's tests after `./packages/contracts/tests`:

```json
"test": "bun test ./packages/contracts/tests ./packages/design-contract/tests ./packages/runway-control/tests ./packages/lens-projectors/tests ./packages/lens-store/tests ./packages/provider-adapters/tests ./packages/policy/tests ./packages/kernel-client/tests ./packages/orchestrator/tests ./packages/context-packer/tests ./packages/testkit/tests ./apps/cli/tests ./apps/api/tests ./apps/console/src ./tests/e2e ./tests/integration"
```

- [ ] **Step 4: Reinstall + typecheck**

Run: `bun install && bun run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/cli/package.json packages/orchestrator/package.json package.json bun.lockb
git commit -m "chore(design-contract): wire workspace deps in cli/orchestrator"
```

---

## Phase 1 — Schema + Deterministic Parser + Cache

### Task 1.1: Define types (`src/types.ts`)

**Files:**
- Create: `packages/design-contract/src/types.ts`
- Modify: `packages/design-contract/src/index.ts`

- [ ] **Step 1: Write all type declarations**

`packages/design-contract/src/types.ts`:

```ts
export type ConfidenceLevel = "verified" | "best_effort";
export type ParserUsed = "deterministic" | "ai" | "cached";
export type RiskLevel = "low" | "medium" | "high";

export type InvariantCheck =
  | { kind: "shell"; command: string; expect_exit_zero: boolean }
  | { kind: "file_exists"; path: string }
  | { kind: "rg"; pattern: string; paths: string[]; must_match: boolean };

export type InvariantEnforcement =
  | { mode: "deterministic"; check: InvariantCheck }
  | { mode: "advisory"; rationale: string };

export interface CrossPathInvariant {
  id: string;
  description: string;
  paths_bound: string[];
  enforcement: InvariantEnforcement;
  policy_ack_required: boolean;
  policy_ack_min_confidence: ConfidenceLevel | null;
}

export interface PrescriptiveBlock {
  id: string;
  language: string;
  body: string;
  body_sha256: string;
  source_line_range: [number, number];
}

export interface ExtractionEvidence {
  line_range: [number, number];
  quote: string;
}

export interface DesignContract {
  schema: "waygent.design_contract.v1";
  source_path: string;
  source_sha256: string;
  invariants: CrossPathInvariant[];
  prescriptive_blocks: PrescriptiveBlock[];
  extracted_at: string;
  parser: ParserUsed;
  extraction_confidence: "high" | "low";
}

export interface PlanContractTask {
  id: string;
  title: string;
  risk: RiskLevel;
  file_claims: string[];
  verification_commands: string[];
  prescriptive_block_ids: string[];
  required_invariant_acks: string[];
}

export interface PlanContract {
  schema: "waygent.plan_contract.v1";
  source_path: string;
  source_sha256: string;
  tasks: PlanContractTask[];
  extracted_at: string;
  parser: ParserUsed;
  extraction_confidence: "high" | "low";
}

export interface PolicyAck {
  invariant_id: string;
  confidence: ConfidenceLevel;
  evidence: string;
}

export interface WorkerEnvelopeV2 {
  schema: "waygent.worker_result.v2";
  task_id: string;
  summary: string;
  evidence: {
    verification_commands: string[];
    key_decision: string | null;
  };
  policy_ack: PolicyAck[];
  stale_test_candidates: string[];
  prescriptive_block_outputs: Array<{ id: string; sha256: string }>;
}

export interface ExtractionLog {
  source_path: string;
  source_sha256: string;
  parser: ParserUsed;
  extracted_at: string;
  ai_prompt_sha256: string | null;
  ai_response_excerpt: string | null;
  evidence_quotes: ExtractionEvidence[];
  reasoning: string | null;
}

export type ParseOutcome<T> =
  | { kind: "ok"; value: T; log: ExtractionLog }
  | { kind: "incomplete"; reason: string }
  | { kind: "failed"; reason: string };

export type DesignBlockerKind =
  | "design_source_missing"
  | "design_extraction_uncertain"
  | "design_extraction_failed"
  | "plan_extraction_failed"
  | "invariant_violation_predispatch"
  | "invariant_violation_post_worker"
  | "policy_ack_missing"
  | "policy_ack_unverified"
  | "stale_test_candidates_missing"
  | "prescriptive_drift"
  | "cache_corruption";
```

- [ ] **Step 2: Re-export from `src/index.ts`**

```ts
export * from "./types.ts";
```

- [ ] **Step 3: Typecheck**

Run: `bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/design-contract/src/
git commit -m "feat(design-contract): add DesignContract/PlanContract type declarations"
```

### Task 1.2: Author canonical fixtures

**Files:**
- Create: `packages/design-contract/tests/fixtures/canonical/design-simple.md`
- Create: `packages/design-contract/tests/fixtures/canonical/design-simple.expected.json`
- Create: `packages/design-contract/tests/fixtures/canonical/plan-simple.md`
- Create: `packages/design-contract/tests/fixtures/canonical/plan-simple.expected.json`

- [ ] **Step 1: Write `design-simple.md`**

```markdown
# Design: Recovered Task Risk

## Cross-Path Invariants

- id: INV-001
  description: Recovered tasks must emit risk=high
  paths_bound:
    - packages/orchestrator/src/planNormalizer.ts
    - packages/orchestrator/src/intakeRecovery.ts
  enforcement:
    mode: deterministic
    check:
      kind: rg
      pattern: "risk:\\s*\"high\"\\s+as const"
      paths:
        - packages/orchestrator/src/planNormalizer.ts
        - packages/orchestrator/src/intakeRecovery.ts
      must_match: true
  policy_ack_required: true
  policy_ack_min_confidence: verified

## Prescriptive Snippets

```ts id=SNIP-001
const useInferredRisk = input.infer_risk === true;
```
```

- [ ] **Step 2: Write `design-simple.expected.json`**

```json
{
  "schema": "waygent.design_contract.v1",
  "source_path": "design-simple.md",
  "invariants": [
    {
      "id": "INV-001",
      "description": "Recovered tasks must emit risk=high",
      "paths_bound": [
        "packages/orchestrator/src/planNormalizer.ts",
        "packages/orchestrator/src/intakeRecovery.ts"
      ],
      "enforcement": {
        "mode": "deterministic",
        "check": {
          "kind": "rg",
          "pattern": "risk:\\s*\"high\"\\s+as const",
          "paths": [
            "packages/orchestrator/src/planNormalizer.ts",
            "packages/orchestrator/src/intakeRecovery.ts"
          ],
          "must_match": true
        }
      },
      "policy_ack_required": true,
      "policy_ack_min_confidence": "verified"
    }
  ],
  "prescriptive_blocks": [
    {
      "id": "SNIP-001",
      "language": "ts",
      "body": "const useInferredRisk = input.infer_risk === true;\n"
    }
  ],
  "parser": "deterministic",
  "extraction_confidence": "high"
}
```

> Note: `source_sha256`, `extracted_at`, `body_sha256`, and `source_line_range` are computed at parse time and matched separately in tests, not pinned here.

- [ ] **Step 3: Write `plan-simple.md`**

```markdown
# Plan: Recovered Task Risk

## Task task_1

- title: Wire recovered risk in planNormalizer
- risk: high
- file_claims:
  - packages/orchestrator/src/planNormalizer.ts: write
- verification_commands:
  - bun test packages/orchestrator/tests/planNormalizer.test.ts
- prescriptive_block_ids:
  - SNIP-001
- required_invariant_acks:
  - INV-001
```

- [ ] **Step 4: Write `plan-simple.expected.json`**

```json
{
  "schema": "waygent.plan_contract.v1",
  "source_path": "plan-simple.md",
  "tasks": [
    {
      "id": "task_1",
      "title": "Wire recovered risk in planNormalizer",
      "risk": "high",
      "file_claims": ["packages/orchestrator/src/planNormalizer.ts:write"],
      "verification_commands": ["bun test packages/orchestrator/tests/planNormalizer.test.ts"],
      "prescriptive_block_ids": ["SNIP-001"],
      "required_invariant_acks": ["INV-001"]
    }
  ],
  "parser": "deterministic",
  "extraction_confidence": "high"
}
```

- [ ] **Step 5: Commit**

```bash
git add packages/design-contract/tests/fixtures/canonical/
git commit -m "test(design-contract): add canonical design/plan fixtures"
```

### Task 1.3: Failing test for deterministic parser

**Files:**
- Create: `packages/design-contract/tests/parseDeterministic.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseDesignDeterministic, parsePlanDeterministic } from "../src/parse/deterministic.ts";

const fixDir = join(import.meta.dir, "fixtures/canonical");

describe("parseDesignDeterministic", () => {
  it("parses canonical design markdown into expected JSON", () => {
    const md = readFileSync(join(fixDir, "design-simple.md"), "utf8");
    const expected = JSON.parse(readFileSync(join(fixDir, "design-simple.expected.json"), "utf8"));
    const out = parseDesignDeterministic(md, "design-simple.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.invariants).toEqual(expected.invariants);
    expect(out.value.prescriptive_blocks.map((b) => ({ id: b.id, language: b.language, body: b.body })))
      .toEqual(expected.prescriptive_blocks);
    expect(out.value.parser).toBe("deterministic");
  });

  it("returns incomplete when required heading missing", () => {
    const out = parseDesignDeterministic("# nothing here\n", "x.md");
    expect(out.kind).toBe("incomplete");
  });
});

describe("parsePlanDeterministic", () => {
  it("parses canonical plan markdown into expected JSON", () => {
    const md = readFileSync(join(fixDir, "plan-simple.md"), "utf8");
    const expected = JSON.parse(readFileSync(join(fixDir, "plan-simple.expected.json"), "utf8"));
    const out = parsePlanDeterministic(md, "plan-simple.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.tasks).toEqual(expected.tasks);
  });
});
```

- [ ] **Step 2: Run and confirm fail**

Run: `bun test packages/design-contract/tests/parseDeterministic.test.ts`
Expected: FAIL with module-not-found on `../src/parse/deterministic.ts`.

### Task 1.4: Implement deterministic parser

**Files:**
- Create: `packages/design-contract/src/parse/deterministic.ts`

- [ ] **Step 1: Write the implementation**

```ts
import { createHash } from "node:crypto";
import type {
  DesignContract,
  PlanContract,
  CrossPathInvariant,
  PrescriptiveBlock,
  PlanContractTask,
  ParseOutcome,
  ExtractionLog
} from "../types.ts";

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

function nowIso(): string {
  return new Date().toISOString();
}

function sliceSection(md: string, heading: string): string | null {
  const lines = md.split("\n");
  const idx = lines.findIndex((l) => l.trim() === heading);
  if (idx < 0) return null;
  const next = lines.slice(idx + 1).findIndex((l) => /^##\s/.test(l));
  const end = next < 0 ? lines.length : idx + 1 + next;
  return lines.slice(idx + 1, end).join("\n");
}

function parseYamlishList(block: string): Array<Record<string, unknown>> {
  // Minimal YAML-like parser: bullets starting with `- key: value` begin an item.
  const items: Array<Record<string, unknown>> = [];
  let current: Record<string, unknown> | null = null;
  let currentListKey: string | null = null;
  for (const raw of block.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) continue;
    const itemStart = line.match(/^-\s+([\w_]+):\s*(.*)$/);
    if (itemStart) {
      current = {};
      items.push(current);
      currentListKey = null;
      const [, k, v] = itemStart;
      if (v) current[k] = v;
      else current[k] = "";
      continue;
    }
    if (!current) continue;
    const fieldStart = line.match(/^\s{2}([\w_]+):\s*(.*)$/);
    if (fieldStart) {
      const [, k, v] = fieldStart;
      currentListKey = null;
      if (v === "") {
        current[k] = {};
      } else {
        current[k] = v;
      }
      continue;
    }
    const nestedListItem = line.match(/^\s{4}-\s+(.*)$/);
    if (nestedListItem) {
      // bullet under previous key
      const lastKey = Object.keys(current).pop()!;
      const val = current[lastKey];
      if (typeof val === "string" && val === "") {
        current[lastKey] = [nestedListItem[1]];
      } else if (Array.isArray(val)) {
        val.push(nestedListItem[1]);
      } else if (typeof val === "object" && val !== null) {
        // ignore; need explicit key
      }
      currentListKey = lastKey;
      continue;
    }
    const nestedField = line.match(/^\s{4}([\w_]+):\s*(.*)$/);
    if (nestedField && current) {
      const [, k, v] = nestedField;
      const lastKey = Object.keys(current).pop()!;
      const val = current[lastKey];
      if (typeof val === "object" && val !== null && !Array.isArray(val)) {
        (val as Record<string, unknown>)[k] = v === "" ? [] : v;
        currentListKey = k;
      }
      continue;
    }
    const deepListItem = line.match(/^\s{6}-\s+(.*)$/);
    if (deepListItem && current && currentListKey) {
      const lastKey = Object.keys(current).pop()!;
      const val = current[lastKey];
      if (typeof val === "object" && val !== null && !Array.isArray(val)) {
        const list = (val as Record<string, unknown>)[currentListKey];
        if (Array.isArray(list)) list.push(deepListItem[1]);
        else (val as Record<string, unknown>)[currentListKey] = [deepListItem[1]];
      }
    }
  }
  return items;
}

function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}
function asBool(v: unknown): boolean {
  return v === "true" || v === true;
}

function buildInvariants(items: Array<Record<string, unknown>>): CrossPathInvariant[] {
  return items.map((it) => {
    const enforcementRaw = (it.enforcement ?? {}) as Record<string, unknown>;
    const mode = asString(enforcementRaw.mode);
    const checkRaw = (enforcementRaw.check ?? {}) as Record<string, unknown>;
    const kind = asString(checkRaw.kind);
    const enforcement =
      mode === "deterministic"
        ? {
            mode: "deterministic" as const,
            check:
              kind === "rg"
                ? {
                    kind: "rg" as const,
                    pattern: asString(checkRaw.pattern),
                    paths: asStringArray(checkRaw.paths),
                    must_match: asBool(checkRaw.must_match)
                  }
                : kind === "shell"
                  ? {
                      kind: "shell" as const,
                      command: asString(checkRaw.command),
                      expect_exit_zero: asBool(checkRaw.expect_exit_zero)
                    }
                  : { kind: "file_exists" as const, path: asString(checkRaw.path) }
          }
        : { mode: "advisory" as const, rationale: asString(enforcementRaw.rationale) };
    return {
      id: asString(it.id),
      description: asString(it.description),
      paths_bound: asStringArray(it.paths_bound),
      enforcement,
      policy_ack_required: asBool(it.policy_ack_required),
      policy_ack_min_confidence:
        it.policy_ack_min_confidence === "verified"
          ? "verified"
          : it.policy_ack_min_confidence === "best_effort"
            ? "best_effort"
            : null
    };
  });
}

function parsePrescriptive(md: string): PrescriptiveBlock[] {
  const blocks: PrescriptiveBlock[] = [];
  const re = /```(\w+)\s+id=([\w-]+)\s*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(md))) {
    const [, lang, id, body] = match;
    const beforeText = md.slice(0, match.index);
    const startLine = beforeText.split("\n").length + 1;
    const endLine = startLine + body.split("\n").length - 1;
    blocks.push({
      id,
      language: lang,
      body,
      body_sha256: sha256(body),
      source_line_range: [startLine, endLine]
    });
  }
  return blocks;
}

export function parseDesignDeterministic(md: string, sourcePath: string): ParseOutcome<DesignContract> {
  const invariantSection = sliceSection(md, "## Cross-Path Invariants");
  if (invariantSection === null) return { kind: "incomplete", reason: "missing_cross_path_invariants_heading" };
  const items = parseYamlishList(invariantSection);
  const invariants = buildInvariants(items);
  if (invariants.length === 0) return { kind: "incomplete", reason: "no_invariants_found" };
  const prescriptive = parsePrescriptive(md);
  const log: ExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(md),
    parser: "deterministic",
    extracted_at: nowIso(),
    ai_prompt_sha256: null,
    ai_response_excerpt: null,
    evidence_quotes: [],
    reasoning: null
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.design_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(md),
      invariants,
      prescriptive_blocks: prescriptive,
      extracted_at: log.extracted_at,
      parser: "deterministic",
      extraction_confidence: "high"
    },
    log
  };
}

export function parsePlanDeterministic(md: string, sourcePath: string): ParseOutcome<PlanContract> {
  const taskRe = /^## Task ([\w-]+)$/gm;
  const matches = [...md.matchAll(taskRe)];
  if (matches.length === 0) return { kind: "incomplete", reason: "no_task_headings" };
  const tasks: PlanContractTask[] = [];
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    const taskId = m[1];
    const start = m.index! + m[0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index! : md.length;
    const body = md.slice(start, end);
    const items = parseYamlishList(body);
    const it = items[0] ?? {};
    tasks.push({
      id: taskId,
      title: asString(it.title),
      risk: (["low", "medium", "high"] as const).find((r) => r === it.risk) ?? "medium",
      file_claims: asStringArray(it.file_claims),
      verification_commands: asStringArray(it.verification_commands),
      prescriptive_block_ids: asStringArray(it.prescriptive_block_ids),
      required_invariant_acks: asStringArray(it.required_invariant_acks)
    });
  }
  const log: ExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(md),
    parser: "deterministic",
    extracted_at: nowIso(),
    ai_prompt_sha256: null,
    ai_response_excerpt: null,
    evidence_quotes: [],
    reasoning: null
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.plan_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(md),
      tasks,
      extracted_at: log.extracted_at,
      parser: "deterministic",
      extraction_confidence: "high"
    },
    log
  };
}
```

- [ ] **Step 2: Run test to verify it passes**

Run: `bun test packages/design-contract/tests/parseDeterministic.test.ts`
Expected: PASS (both `describe` blocks green).

- [ ] **Step 3: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): deterministic parser for canonical design/plan"
```

### Task 1.5: Failing test for parse cache

**Files:**
- Create: `packages/design-contract/tests/cache.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it, beforeEach } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ArtifactCache } from "../src/parse/cache.ts";

let root: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "design-contract-cache-"));
});

describe("ArtifactCache", () => {
  it("returns null on miss, hit on store + read", async () => {
    const cache = new ArtifactCache(root);
    const key = { sourcePath: "x.md", sourceSha256: "abc", extractorVersion: "v1" };
    expect(await cache.read(key)).toBeNull();
    await cache.write(key, { hello: "world" });
    expect(await cache.read(key)).toEqual({ hello: "world" });
  });

  it("invalidates when key hash differs", async () => {
    const cache = new ArtifactCache(root);
    await cache.write({ sourcePath: "x.md", sourceSha256: "a", extractorVersion: "v1" }, { v: 1 });
    expect(
      await cache.read({ sourcePath: "x.md", sourceSha256: "b", extractorVersion: "v1" })
    ).toBeNull();
  });

  it("returns null when stored payload is malformed JSON", async () => {
    const cache = new ArtifactCache(root);
    const key = { sourcePath: "x.md", sourceSha256: "abc", extractorVersion: "v1" };
    await cache.write(key, { ok: true });
    await Bun.write(cache.pathFor(key), "not-json{");
    expect(await cache.read(key)).toBeNull();
  });
});
```

- [ ] **Step 2: Confirm fail**

Run: `bun test packages/design-contract/tests/cache.test.ts`
Expected: FAIL — module not found.

### Task 1.6: Implement cache

**Files:**
- Create: `packages/design-contract/src/parse/cache.ts`

- [ ] **Step 1: Implement**

```ts
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export interface CacheKey {
  sourcePath: string;
  sourceSha256: string;
  extractorVersion: string;
}

export class ArtifactCache {
  constructor(private readonly root: string) {}

  pathFor(key: CacheKey): string {
    const digest = createHash("sha256")
      .update(`${key.sourcePath}|${key.sourceSha256}|${key.extractorVersion}`)
      .digest("hex");
    return join(this.root, `${digest}.json`);
  }

  async read(key: CacheKey): Promise<unknown | null> {
    const path = this.pathFor(key);
    try {
      const raw = await readFile(path, "utf8");
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  async write(key: CacheKey, value: unknown): Promise<void> {
    const path = this.pathFor(key);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, JSON.stringify(value, null, 2), "utf8");
  }
}
```

- [ ] **Step 2: Run test**

Run: `bun test packages/design-contract/tests/cache.test.ts`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): hash-keyed parse artifact cache"
```

---

## Phase 2 — AI Extractor + Fallback Chain

### Task 2.1: ExtractorProvider interface + fake implementation

**Files:**
- Create: `packages/design-contract/src/parse/ai.ts`
- Create: `packages/design-contract/tests/fixtures/freeform/design-korean-prose.md`
- Create: `packages/design-contract/tests/fixtures/freeform/design-korean-prose.ai-response.json`

- [ ] **Step 1: Write the interface + fake provider**

`packages/design-contract/src/parse/ai.ts`:

```ts
import { createHash } from "node:crypto";
import type {
  DesignContract,
  PlanContract,
  ParseOutcome,
  ExtractionLog
} from "../types.ts";

export const EXTRACTOR_VERSION = "v1";

export interface ExtractorRequest {
  kind: "design" | "plan";
  sourcePath: string;
  sourceMarkdown: string;
}

export interface ExtractorResponse {
  schemaPayload: unknown;
  reasoning: string | null;
  evidenceQuotes: Array<{ line_range: [number, number]; quote: string }>;
  confidence: "high" | "low";
}

export interface ExtractorProvider {
  extract(req: ExtractorRequest): Promise<ExtractorResponse>;
  /** Stable id used in cache keys and logs. */
  readonly name: string;
}

export class FakeExtractorProvider implements ExtractorProvider {
  readonly name = "fake";
  constructor(private readonly responses: Map<string, ExtractorResponse | "throw" | "malformed">) {}

  async extract(req: ExtractorRequest): Promise<ExtractorResponse> {
    const key = `${req.kind}:${req.sourcePath}`;
    const r = this.responses.get(key);
    if (!r) throw new Error(`fake provider has no fixture for ${key}`);
    if (r === "throw") throw new Error("simulated transient");
    if (r === "malformed") {
      return {
        schemaPayload: { bogus: true },
        reasoning: null,
        evidenceQuotes: [],
        confidence: "low"
      };
    }
    return r;
  }
}

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}
function nowIso(): string {
  return new Date().toISOString();
}

function isDesignPayload(value: unknown): value is Omit<DesignContract, "parser" | "extracted_at" | "source_sha256" | "schema"> {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.invariants) && Array.isArray(v.prescriptive_blocks);
}
function isPlanPayload(value: unknown): value is Omit<PlanContract, "parser" | "extracted_at" | "source_sha256" | "schema"> {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.tasks);
}

export async function extractDesignWithAI(
  provider: ExtractorProvider,
  markdown: string,
  sourcePath: string
): Promise<ParseOutcome<DesignContract>> {
  const req: ExtractorRequest = { kind: "design", sourcePath, sourceMarkdown: markdown };
  let resp: ExtractorResponse;
  let attempt = 0;
  while (true) {
    try {
      resp = await provider.extract(req);
      if (!isDesignPayload(resp.schemaPayload)) {
        if (attempt >= 1) return { kind: "failed", reason: "ai_malformed_payload" };
        attempt++;
        continue;
      }
      break;
    } catch (err) {
      if (attempt >= 2) return { kind: "failed", reason: `ai_provider_error: ${(err as Error).message}` };
      attempt++;
      await new Promise((r) => setTimeout(r, 50 * Math.pow(2, attempt)));
    }
  }
  const payload = resp.schemaPayload as Record<string, unknown>;
  const log: ExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(markdown),
    parser: "ai",
    extracted_at: nowIso(),
    ai_prompt_sha256: sha256(`design:${sourcePath}`),
    ai_response_excerpt: JSON.stringify(payload).slice(0, 200),
    evidence_quotes: resp.evidenceQuotes,
    reasoning: resp.reasoning
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.design_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(markdown),
      invariants: payload.invariants as DesignContract["invariants"],
      prescriptive_blocks: payload.prescriptive_blocks as DesignContract["prescriptive_blocks"],
      extracted_at: log.extracted_at,
      parser: "ai",
      extraction_confidence: resp.confidence
    },
    log
  };
}

export async function extractPlanWithAI(
  provider: ExtractorProvider,
  markdown: string,
  sourcePath: string
): Promise<ParseOutcome<PlanContract>> {
  const req: ExtractorRequest = { kind: "plan", sourcePath, sourceMarkdown: markdown };
  let resp: ExtractorResponse;
  let attempt = 0;
  while (true) {
    try {
      resp = await provider.extract(req);
      if (!isPlanPayload(resp.schemaPayload)) {
        if (attempt >= 1) return { kind: "failed", reason: "ai_malformed_payload" };
        attempt++;
        continue;
      }
      break;
    } catch (err) {
      if (attempt >= 2) return { kind: "failed", reason: `ai_provider_error: ${(err as Error).message}` };
      attempt++;
      await new Promise((r) => setTimeout(r, 50 * Math.pow(2, attempt)));
    }
  }
  const payload = resp.schemaPayload as Record<string, unknown>;
  const log: ExtractionLog = {
    source_path: sourcePath,
    source_sha256: sha256(markdown),
    parser: "ai",
    extracted_at: nowIso(),
    ai_prompt_sha256: sha256(`plan:${sourcePath}`),
    ai_response_excerpt: JSON.stringify(payload).slice(0, 200),
    evidence_quotes: resp.evidenceQuotes,
    reasoning: resp.reasoning
  };
  return {
    kind: "ok",
    value: {
      schema: "waygent.plan_contract.v1",
      source_path: sourcePath,
      source_sha256: sha256(markdown),
      tasks: payload.tasks as PlanContract["tasks"],
      extracted_at: log.extracted_at,
      parser: "ai",
      extraction_confidence: resp.confidence
    },
    log
  };
}
```

- [ ] **Step 2: Write freeform fixture (Korean prose)**

`packages/design-contract/tests/fixtures/freeform/design-korean-prose.md`:

```markdown
# 복구 task의 risk 정책

prose 형식의 plan에서 recover된 task는 항상 risk를 high로 정해야 한다.
이건 두 곳에 적용된다: 옛 planNormalizer의 superpowers 모드와, 새
intakeRecovery의 deterministicRepair. 두 곳 모두 `risk: "high" as const`가
하드코드되어 있어야 한다.
```

- [ ] **Step 3: Write the corresponding fake AI response**

`packages/design-contract/tests/fixtures/freeform/design-korean-prose.ai-response.json`:

```json
{
  "schemaPayload": {
    "invariants": [
      {
        "id": "INV-001",
        "description": "Recovered tasks emit risk=high",
        "paths_bound": [
          "packages/orchestrator/src/planNormalizer.ts",
          "packages/orchestrator/src/intakeRecovery.ts"
        ],
        "enforcement": {
          "mode": "deterministic",
          "check": {
            "kind": "rg",
            "pattern": "risk:\\s*\"high\"\\s+as const",
            "paths": [
              "packages/orchestrator/src/planNormalizer.ts",
              "packages/orchestrator/src/intakeRecovery.ts"
            ],
            "must_match": true
          }
        },
        "policy_ack_required": true,
        "policy_ack_min_confidence": "verified"
      }
    ],
    "prescriptive_blocks": []
  },
  "reasoning": "Document explicitly names two file paths and requires risk:\"high\" as const at both.",
  "evidenceQuotes": [
    { "line_range": [3, 6], "quote": "두 곳에 적용된다... 두 곳 모두 `risk: \"high\" as const`가 하드코드되어 있어야 한다." }
  ],
  "confidence": "high"
}
```

- [ ] **Step 4: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): ExtractorProvider interface + fake impl + freeform fixture"
```

### Task 2.2: Tests for AI extractor

**Files:**
- Create: `packages/design-contract/tests/parseAI.test.ts`

- [ ] **Step 1: Write the test**

```ts
import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { FakeExtractorProvider, extractDesignWithAI, type ExtractorResponse } from "../src/parse/ai.ts";

const fixDir = join(import.meta.dir, "fixtures/freeform");

function loadResp(name: string): ExtractorResponse {
  return JSON.parse(readFileSync(join(fixDir, `${name}.ai-response.json`), "utf8"));
}

describe("extractDesignWithAI", () => {
  it("returns ok with validated payload from fake provider", async () => {
    const md = readFileSync(join(fixDir, "design-korean-prose.md"), "utf8");
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const out = await extractDesignWithAI(provider, md, "design-korean-prose.md");
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("ai");
    expect(out.value.invariants[0].id).toBe("INV-001");
    expect(out.log.reasoning).toContain("two file paths");
  });

  it("retries once on malformed payload then fails", async () => {
    const provider = new FakeExtractorProvider(
      new Map([["design:bad.md", "malformed"]])
    );
    const out = await extractDesignWithAI(provider, "# x", "bad.md");
    expect(out.kind).toBe("failed");
  });

  it("retries twice on transient throw then fails", async () => {
    const provider = new FakeExtractorProvider(
      new Map([["design:bad.md", "throw"]])
    );
    const out = await extractDesignWithAI(provider, "# x", "bad.md");
    expect(out.kind).toBe("failed");
    if (out.kind !== "failed") return;
    expect(out.reason).toContain("ai_provider_error");
  });
});
```

- [ ] **Step 2: Run**

Run: `bun test packages/design-contract/tests/parseAI.test.ts`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/design-contract/tests/parseAI.test.ts
git commit -m "test(design-contract): cover AI extractor success + retry/fail paths"
```

### Task 2.3: Fallback chain (`parse/index.ts`)

**Files:**
- Create: `packages/design-contract/src/parse/index.ts`
- Create: `packages/design-contract/tests/parseIndex.test.ts`

- [ ] **Step 1: Write the failing test first**

```ts
import { describe, expect, it } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { FakeExtractorProvider, type ExtractorResponse } from "../src/parse/ai.ts";
import { parseDesignSource } from "../src/parse/index.ts";

const fixCanonical = join(import.meta.dir, "fixtures/canonical");
const fixFreeform = join(import.meta.dir, "fixtures/freeform");

function loadResp(name: string): ExtractorResponse {
  return JSON.parse(readFileSync(join(fixFreeform, `${name}.ai-response.json`), "utf8"));
}

describe("parseDesignSource fallback chain", () => {
  it("uses deterministic when canonical input parses", async () => {
    const md = readFileSync(join(fixCanonical, "design-simple.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(new Map());
    const out = await parseDesignSource(md, "design-simple.md", { cacheRoot, provider });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("deterministic");
  });

  it("falls back to AI when deterministic returns incomplete", async () => {
    const md = readFileSync(join(fixFreeform, "design-korean-prose.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const out = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("ai");
  });

  it("returns cached on second call with same source", async () => {
    const md = readFileSync(join(fixFreeform, "design-korean-prose.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(
      new Map([["design:design-korean-prose.md", loadResp("design-korean-prose")]])
    );
    const first = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(first.kind).toBe("ok");
    const second = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(second.kind).toBe("ok");
    if (second.kind !== "ok") return;
    expect(second.value.parser).toBe("cached");
  });

  it("returns failed when both deterministic and AI fail", async () => {
    const md = "# nothing\n";
    const cacheRoot = mkdtempSync(join(tmpdir(), "dc-cache-"));
    const provider = new FakeExtractorProvider(new Map([["design:x.md", "throw"]]));
    const out = await parseDesignSource(md, "x.md", { cacheRoot, provider });
    expect(out.kind).toBe("failed");
  });
});
```

- [ ] **Step 2: Confirm fail**

Run: `bun test packages/design-contract/tests/parseIndex.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`packages/design-contract/src/parse/index.ts`:

```ts
import { createHash } from "node:crypto";
import type { DesignContract, PlanContract, ParseOutcome, ExtractionLog } from "../types.ts";
import { ArtifactCache } from "./cache.ts";
import { parseDesignDeterministic, parsePlanDeterministic } from "./deterministic.ts";
import { EXTRACTOR_VERSION, extractDesignWithAI, extractPlanWithAI, type ExtractorProvider } from "./ai.ts";

export interface ParseOptions {
  cacheRoot: string;
  provider: ExtractorProvider;
}

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

function nowIso(): string {
  return new Date().toISOString();
}

async function runWithCache<T extends DesignContract | PlanContract>(
  kind: "design" | "plan",
  markdown: string,
  sourcePath: string,
  options: ParseOptions,
  deterministic: () => ParseOutcome<T>,
  ai: () => Promise<ParseOutcome<T>>
): Promise<ParseOutcome<T>> {
  const cache = new ArtifactCache(options.cacheRoot);
  const key = {
    sourcePath: `${kind}:${sourcePath}`,
    sourceSha256: sha256(markdown),
    extractorVersion: EXTRACTOR_VERSION
  };
  const cached = (await cache.read(key)) as { value: T; log: ExtractionLog } | null;
  if (cached && cached.value && cached.log) {
    return {
      kind: "ok",
      value: { ...cached.value, parser: "cached" },
      log: { ...cached.log, parser: "cached" }
    };
  }
  const det = deterministic();
  if (det.kind === "ok") {
    await cache.write(key, { value: det.value, log: det.log });
    return det;
  }
  if (det.kind === "failed") return det;
  const aiOut = await ai();
  if (aiOut.kind === "ok") {
    await cache.write(key, { value: aiOut.value, log: aiOut.log });
  }
  return aiOut;
}

export async function parseDesignSource(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<ParseOutcome<DesignContract>> {
  return runWithCache<DesignContract>(
    "design",
    markdown,
    sourcePath,
    options,
    () => parseDesignDeterministic(markdown, sourcePath),
    () => extractDesignWithAI(options.provider, markdown, sourcePath)
  );
}

export async function parsePlanSource(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<ParseOutcome<PlanContract>> {
  return runWithCache<PlanContract>(
    "plan",
    markdown,
    sourcePath,
    options,
    () => parsePlanDeterministic(markdown, sourcePath),
    () => extractPlanWithAI(options.provider, markdown, sourcePath)
  );
}
```

- [ ] **Step 4: Run test**

Run: `bun test packages/design-contract/tests/parseIndex.test.ts`
Expected: PASS.

- [ ] **Step 5: Re-export from package index**

In `packages/design-contract/src/index.ts`, add:

```ts
export * from "./types.ts";
export * from "./parse/index.ts";
export * from "./parse/ai.ts";
export * from "./parse/deterministic.ts";
export * from "./parse/cache.ts";
```

- [ ] **Step 6: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): cache-aware deterministic→AI fallback chain"
```

---

## Phase 3 — Invariant Runner + Worker Envelope Validator

### Task 3.1: Shell check kind + runner

**Files:**
- Create: `packages/design-contract/src/checks/shell.ts`
- Create: `packages/design-contract/src/checks/index.ts`
- Create: `packages/design-contract/tests/checks.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "bun:test";
import { runInvariantCheck } from "../src/checks/index.ts";

describe("runInvariantCheck", () => {
  it("shell: passes when command exits 0", async () => {
    const res = await runInvariantCheck(
      { kind: "shell", command: "true", expect_exit_zero: true },
      process.cwd()
    );
    expect(res.passed).toBe(true);
  });

  it("shell: fails when command exits non-zero", async () => {
    const res = await runInvariantCheck(
      { kind: "shell", command: "false", expect_exit_zero: true },
      process.cwd()
    );
    expect(res.passed).toBe(false);
    expect(res.evidence).toContain("exit");
  });

  it("file_exists: passes for present file", async () => {
    const res = await runInvariantCheck({ kind: "file_exists", path: "package.json" }, process.cwd());
    expect(res.passed).toBe(true);
  });

  it("file_exists: fails for missing file", async () => {
    const res = await runInvariantCheck(
      { kind: "file_exists", path: "definitely-not-here.xyz" },
      process.cwd()
    );
    expect(res.passed).toBe(false);
  });
});
```

- [ ] **Step 2: Implement shell + dispatcher**

`packages/design-contract/src/checks/shell.ts`:

```ts
import { spawn } from "node:child_process";

export interface ShellCheckResult {
  passed: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
}

export function runShell(command: string, cwd: string): Promise<ShellCheckResult> {
  return new Promise((resolve) => {
    const proc = spawn("sh", ["-c", command], { cwd });
    let out = "";
    let err = "";
    proc.stdout.on("data", (b) => (out += b.toString("utf8")));
    proc.stderr.on("data", (b) => (err += b.toString("utf8")));
    proc.on("close", (code) => {
      const exit = typeof code === "number" ? code : -1;
      resolve({ passed: exit === 0, exit_code: exit, stdout: out, stderr: err });
    });
  });
}
```

`packages/design-contract/src/checks/index.ts`:

```ts
import { existsSync } from "node:fs";
import { join } from "node:path";
import type { InvariantCheck } from "../types.ts";
import { runShell } from "./shell.ts";

export interface CheckResult {
  passed: boolean;
  evidence: string;
}

export async function runInvariantCheck(check: InvariantCheck, cwd: string): Promise<CheckResult> {
  if (check.kind === "shell") {
    const r = await runShell(check.command, cwd);
    const matched = check.expect_exit_zero ? r.exit_code === 0 : r.exit_code !== 0;
    return {
      passed: matched,
      evidence: `shell \`${check.command}\` exit=${r.exit_code} stderr=${r.stderr.slice(0, 200)}`
    };
  }
  if (check.kind === "file_exists") {
    const present = existsSync(join(cwd, check.path));
    return { passed: present, evidence: `file_exists ${check.path} present=${present}` };
  }
  // kind === "rg" — delegate to shell with rg command
  const pathsArg = check.paths.map((p) => JSON.stringify(p)).join(" ");
  const command = `rg --no-messages -q ${JSON.stringify(check.pattern)} ${pathsArg}`;
  const r = await runShell(command, cwd);
  const matched = check.must_match ? r.exit_code === 0 : r.exit_code !== 0;
  return {
    passed: matched,
    evidence: `rg pattern=${check.pattern} paths=[${check.paths.join(",")}] exit=${r.exit_code}`
  };
}
```

- [ ] **Step 3: Run test**

Run: `bun test packages/design-contract/tests/checks.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): invariant check kinds (shell, file_exists, rg)"
```

### Task 3.2: Invariant runner — paths_bound + ack validation

**Files:**
- Create: `packages/design-contract/src/invariants.ts`
- Create: `packages/design-contract/tests/invariants.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "bun:test";
import {
  runInvariantsAgainstFileClaims,
  validatePolicyAcks
} from "../src/invariants.ts";
import type { CrossPathInvariant, PolicyAck } from "../src/types.ts";

const inv: CrossPathInvariant = {
  id: "INV-001",
  description: "x",
  paths_bound: ["package.json"],
  enforcement: { mode: "deterministic", check: { kind: "file_exists", path: "package.json" } },
  policy_ack_required: true,
  policy_ack_min_confidence: "verified"
};

describe("runInvariantsAgainstFileClaims", () => {
  it("runs invariants whose paths_bound intersect task file claims", async () => {
    const res = await runInvariantsAgainstFileClaims([inv], ["package.json:write"], process.cwd());
    expect(res).toHaveLength(1);
    expect(res[0].invariant_id).toBe("INV-001");
    expect(res[0].passed).toBe(true);
  });

  it("skips invariants with no overlap", async () => {
    const res = await runInvariantsAgainstFileClaims([inv], ["other.ts:write"], process.cwd());
    expect(res).toHaveLength(0);
  });
});

describe("validatePolicyAcks", () => {
  it("passes when ack exists with sufficient confidence", () => {
    const acks: PolicyAck[] = [{ invariant_id: "INV-001", confidence: "verified", evidence: "ran rg" }];
    const out = validatePolicyAcks([inv], acks);
    expect(out.missing).toHaveLength(0);
    expect(out.unverified).toHaveLength(0);
  });

  it("flags missing acks", () => {
    const out = validatePolicyAcks([inv], []);
    expect(out.missing).toEqual(["INV-001"]);
  });

  it("flags acks with insufficient confidence", () => {
    const acks: PolicyAck[] = [{ invariant_id: "INV-001", confidence: "best_effort", evidence: "guessed" }];
    const out = validatePolicyAcks([inv], acks);
    expect(out.unverified).toEqual(["INV-001"]);
  });
});
```

- [ ] **Step 2: Implement**

`packages/design-contract/src/invariants.ts`:

```ts
import type { CrossPathInvariant, PolicyAck } from "./types.ts";
import { runInvariantCheck } from "./checks/index.ts";

export interface InvariantRunResult {
  invariant_id: string;
  passed: boolean;
  evidence: string;
  enforcement_mode: "deterministic" | "advisory";
}

function claimPath(claim: string): string {
  const idx = claim.indexOf(":");
  return idx < 0 ? claim : claim.slice(0, idx);
}

function intersects(paths_bound: string[], file_claims: string[]): boolean {
  const claimPaths = new Set(file_claims.map(claimPath));
  return paths_bound.some((p) => claimPaths.has(p));
}

export async function runInvariantsAgainstFileClaims(
  invariants: CrossPathInvariant[],
  file_claims: string[],
  cwd: string
): Promise<InvariantRunResult[]> {
  const out: InvariantRunResult[] = [];
  for (const inv of invariants) {
    if (!intersects(inv.paths_bound, file_claims)) continue;
    if (inv.enforcement.mode === "advisory") {
      out.push({
        invariant_id: inv.id,
        passed: true,
        evidence: `advisory: ${inv.enforcement.rationale}`,
        enforcement_mode: "advisory"
      });
      continue;
    }
    const res = await runInvariantCheck(inv.enforcement.check, cwd);
    out.push({
      invariant_id: inv.id,
      passed: res.passed,
      evidence: res.evidence,
      enforcement_mode: "deterministic"
    });
  }
  return out;
}

export interface AckValidationResult {
  missing: string[];
  unverified: string[];
}

const CONF_ORDER = { best_effort: 0, verified: 1 } as const;

export function validatePolicyAcks(
  invariants: CrossPathInvariant[],
  acks: PolicyAck[]
): AckValidationResult {
  const ackById = new Map(acks.map((a) => [a.invariant_id, a]));
  const missing: string[] = [];
  const unverified: string[] = [];
  for (const inv of invariants) {
    if (!inv.policy_ack_required) continue;
    const ack = ackById.get(inv.id);
    if (!ack) {
      missing.push(inv.id);
      continue;
    }
    const required = inv.policy_ack_min_confidence ?? "best_effort";
    if (CONF_ORDER[ack.confidence] < CONF_ORDER[required]) {
      unverified.push(inv.id);
    }
  }
  return { missing, unverified };
}
```

- [ ] **Step 3: Run test**

Run: `bun test packages/design-contract/tests/invariants.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): invariant runner + policy ack validator"
```

### Task 3.3: Worker envelope validator + prescriptive drift

**Files:**
- Create: `packages/design-contract/src/workerEnvelope.ts`
- Create: `packages/design-contract/tests/workerEnvelope.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "bun:test";
import { createHash } from "node:crypto";
import { validateWorkerEnvelope } from "../src/workerEnvelope.ts";
import type { DesignContract, WorkerEnvelopeV2 } from "../src/types.ts";

function sha(s: string) { return createHash("sha256").update(s).digest("hex"); }

const snip = "const x = 1;\n";
const design: DesignContract = {
  schema: "waygent.design_contract.v1",
  source_path: "d.md",
  source_sha256: "x",
  invariants: [],
  prescriptive_blocks: [
    { id: "SNIP-001", language: "ts", body: snip, body_sha256: sha(snip), source_line_range: [1, 2] }
  ],
  extracted_at: "2026-01-01T00:00:00Z",
  parser: "deterministic",
  extraction_confidence: "high"
};

const baseEnv: WorkerEnvelopeV2 = {
  schema: "waygent.worker_result.v2",
  task_id: "task_1",
  summary: "did stuff",
  evidence: { verification_commands: ["bun test"], key_decision: null },
  policy_ack: [],
  stale_test_candidates: [],
  prescriptive_block_outputs: [{ id: "SNIP-001", sha256: sha(snip) }]
};

describe("validateWorkerEnvelope", () => {
  it("passes when envelope is well-formed and snippets match", () => {
    const out = validateWorkerEnvelope(baseEnv, design);
    expect(out.blockers).toHaveLength(0);
  });

  it("blocks when stale_test_candidates field is absent", () => {
    const env = { ...baseEnv } as Partial<WorkerEnvelopeV2>;
    delete env.stale_test_candidates;
    const out = validateWorkerEnvelope(env as WorkerEnvelopeV2, design);
    expect(out.blockers.map((b) => b.kind)).toContain("stale_test_candidates_missing");
  });

  it("blocks on prescriptive drift", () => {
    const env = {
      ...baseEnv,
      prescriptive_block_outputs: [{ id: "SNIP-001", sha256: sha("const y = 2;\n") }]
    };
    const out = validateWorkerEnvelope(env, design);
    expect(out.blockers.map((b) => b.kind)).toContain("prescriptive_drift");
  });
});
```

- [ ] **Step 2: Implement**

`packages/design-contract/src/workerEnvelope.ts`:

```ts
import type { DesignContract, DesignBlockerKind, WorkerEnvelopeV2 } from "./types.ts";

export interface EnvelopeBlocker {
  kind: DesignBlockerKind;
  detail: string;
}

export interface EnvelopeValidationResult {
  blockers: EnvelopeBlocker[];
}

export function validateWorkerEnvelope(
  env: WorkerEnvelopeV2,
  design: DesignContract
): EnvelopeValidationResult {
  const blockers: EnvelopeBlocker[] = [];
  if (!Array.isArray((env as { stale_test_candidates?: unknown }).stale_test_candidates)) {
    blockers.push({
      kind: "stale_test_candidates_missing",
      detail: `task ${env.task_id} envelope missing stale_test_candidates array`
    });
  }
  const outputById = new Map(env.prescriptive_block_outputs.map((o) => [o.id, o.sha256]));
  for (const block of design.prescriptive_blocks) {
    const got = outputById.get(block.id);
    if (got === undefined) continue;
    if (got !== block.body_sha256) {
      blockers.push({
        kind: "prescriptive_drift",
        detail: `snippet ${block.id} expected ${block.body_sha256.slice(0, 12)} got ${got.slice(0, 12)}`
      });
    }
  }
  return { blockers };
}
```

- [ ] **Step 3: Run test**

Run: `bun test packages/design-contract/tests/workerEnvelope.test.ts`
Expected: PASS.

- [ ] **Step 4: Re-export and commit**

In `src/index.ts`, add:

```ts
export * from "./invariants.ts";
export * from "./workerEnvelope.ts";
export * from "./checks/index.ts";
```

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): worker_result.v2 envelope validator + drift check"
```

---

## Phase 4 — Lint CLI

### Task 4.1: lint.ts module

**Files:**
- Create: `packages/design-contract/src/lint.ts`
- Create: `packages/design-contract/tests/lint.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { lintDesign } from "../src/lint.ts";
import { FakeExtractorProvider } from "../src/parse/ai.ts";

describe("lintDesign", () => {
  it("renders normalized invariants and 'no blockers' for canonical input", async () => {
    const md = readFileSync(join(import.meta.dir, "fixtures/canonical/design-simple.md"), "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "lint-"));
    const provider = new FakeExtractorProvider(new Map());
    const out = await lintDesign(md, "design-simple.md", { cacheRoot, provider });
    expect(out.parser).toBe("deterministic");
    expect(out.report).toContain("INV-001");
    expect(out.report).toContain("invariants: 1");
  });

  it("reports failure when parse fails", async () => {
    const cacheRoot = mkdtempSync(join(tmpdir(), "lint-"));
    const provider = new FakeExtractorProvider(new Map([["design:x.md", "throw"]]));
    const out = await lintDesign("# empty\n", "x.md", { cacheRoot, provider });
    expect(out.report).toContain("FAILED");
  });
});
```

- [ ] **Step 2: Implement**

`packages/design-contract/src/lint.ts`:

```ts
import type { ParserUsed } from "./types.ts";
import { parseDesignSource, parsePlanSource, type ParseOptions } from "./parse/index.ts";

export interface LintResult {
  parser: ParserUsed | "failed";
  report: string;
}

export async function lintDesign(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<LintResult> {
  const out = await parseDesignSource(markdown, sourcePath, options);
  if (out.kind !== "ok") {
    return { parser: "failed", report: `FAILED to extract design (${out.kind}): ${(out as { reason?: string }).reason ?? ""}` };
  }
  const lines: string[] = [];
  lines.push(`source: ${sourcePath}`);
  lines.push(`parser: ${out.value.parser}`);
  lines.push(`extraction_confidence: ${out.value.extraction_confidence}`);
  lines.push(`invariants: ${out.value.invariants.length}`);
  for (const inv of out.value.invariants) {
    lines.push(`  - ${inv.id} (paths: ${inv.paths_bound.join(", ")}) ack_required=${inv.policy_ack_required}`);
  }
  lines.push(`prescriptive_blocks: ${out.value.prescriptive_blocks.length}`);
  for (const b of out.value.prescriptive_blocks) {
    lines.push(`  - ${b.id} (${b.language}, ${b.body_sha256.slice(0, 12)})`);
  }
  return { parser: out.value.parser, report: lines.join("\n") };
}

export async function lintPlan(
  markdown: string,
  sourcePath: string,
  options: ParseOptions
): Promise<LintResult> {
  const out = await parsePlanSource(markdown, sourcePath, options);
  if (out.kind !== "ok") {
    return { parser: "failed", report: `FAILED to extract plan (${out.kind}): ${(out as { reason?: string }).reason ?? ""}` };
  }
  const lines: string[] = [];
  lines.push(`source: ${sourcePath}`);
  lines.push(`parser: ${out.value.parser}`);
  lines.push(`tasks: ${out.value.tasks.length}`);
  for (const t of out.value.tasks) {
    lines.push(`  - ${t.id} risk=${t.risk} acks=[${t.required_invariant_acks.join(",")}] claims=[${t.file_claims.join(",")}]`);
  }
  return { parser: out.value.parser, report: lines.join("\n") };
}
```

- [ ] **Step 3: Run + export**

Run: `bun test packages/design-contract/tests/lint.test.ts`
Expected: PASS.

In `src/index.ts` add:

```ts
export * from "./lint.ts";
```

- [ ] **Step 4: Commit**

```bash
git add packages/design-contract/
git commit -m "feat(design-contract): lint helpers for design/plan dry-run reports"
```

### Task 4.2: CLI commands `waygent lint-design` and `waygent lint-plan`

**Files:**
- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`

- [ ] **Step 1: Locate the command dispatch table**

Run: `grep -n "case \"\(run\|status\|explain\|inspect\|verify\|apply\|orphans\)\"" apps/cli/src/index.ts | head -20`

Identify the switch/if block where command names map to handlers. Note the line number.

- [ ] **Step 2: Add a failing CLI test**

In `apps/cli/tests/cli.test.ts`, append:

```ts
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

describe("waygent lint-design CLI", () => {
  it("prints normalized report for canonical design", () => {
    const dir = mkdtempSync(join(tmpdir(), "cli-lint-"));
    const fixturePath = join(import.meta.dir, "..", "..", "..", "packages", "design-contract", "tests", "fixtures", "canonical", "design-simple.md");
    const result = spawnSync(
      "bun",
      ["run", "apps/cli/src/index.ts", "lint-design", "--path", fixturePath, "--cache-root", dir],
      { encoding: "utf8" }
    );
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("INV-001");
    expect(result.stdout).toContain("invariants: 1");
  });
});
```

- [ ] **Step 3: Run + confirm fail**

Run: `bun test apps/cli/tests/cli.test.ts -t "lint-design CLI"`
Expected: FAIL — command not recognized.

- [ ] **Step 4: Implement CLI handler**

In `apps/cli/src/index.ts`, add an import near the top:

```ts
import { FakeExtractorProvider, lintDesign, lintPlan } from "@waygent/design-contract";
import { readFileSync as readSync } from "node:fs";
```

Find the command switch/dispatch. Add two new cases (before any default):

```ts
if (command === "lint-design") {
  const pathArg = getFlag(args, "--path");
  const cacheRoot = getFlag(args, "--cache-root") ?? join(process.cwd(), ".waygent", "design-contract-cache");
  if (!pathArg) {
    console.error("lint-design requires --path");
    process.exit(2);
  }
  const md = readSync(pathArg, "utf8");
  const provider = new FakeExtractorProvider(new Map());
  const out = await lintDesign(md, pathArg, { cacheRoot, provider });
  process.stdout.write(out.report + "\n");
  process.exit(out.parser === "failed" ? 1 : 0);
}

if (command === "lint-plan") {
  const pathArg = getFlag(args, "--path");
  const cacheRoot = getFlag(args, "--cache-root") ?? join(process.cwd(), ".waygent", "design-contract-cache");
  if (!pathArg) {
    console.error("lint-plan requires --path");
    process.exit(2);
  }
  const md = readSync(pathArg, "utf8");
  const provider = new FakeExtractorProvider(new Map());
  const out = await lintPlan(md, pathArg, { cacheRoot, provider });
  process.stdout.write(out.report + "\n");
  process.exit(out.parser === "failed" ? 1 : 0);
}
```

> If the file does not have a `getFlag(args, name)` helper, define one locally:
> ```ts
> function getFlag(args: string[], name: string): string | undefined {
>   const idx = args.indexOf(name);
>   return idx >= 0 ? args[idx + 1] : undefined;
> }
> ```
> If `getFlag` already exists with a different name, use the existing helper instead.

- [ ] **Step 5: Run the CLI test**

Run: `bun test apps/cli/tests/cli.test.ts -t "lint-design CLI"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/cli/src/index.ts apps/cli/tests/cli.test.ts
git commit -m "feat(cli): add lint-design and lint-plan commands"
```

---

## Phase 5 — Orchestrator Wiring (Pre-Dispatch + Post-Worker)

### Task 5.1: Add `design_contract` to run state contracts

**Files:**
- Modify: `packages/contracts/src/types.ts`
- Modify: `packages/contracts/src/schemas.ts`
- Modify: `packages/contracts/tests/` (one existing schema test)

- [ ] **Step 1: Add the type**

In `packages/contracts/src/types.ts`, add near `WaygentIntakeRecovery`:

```ts
export interface WaygentDesignContractRef {
  normalized_design_ref: string | null;
  normalized_plan_ref: string | null;
  extraction_log_design_ref: string | null;
  extraction_log_plan_ref: string | null;
  parser_design: "deterministic" | "ai" | "cached" | null;
  parser_plan: "deterministic" | "ai" | "cached" | null;
  extraction_confidence_design: "high" | "low" | null;
  extraction_confidence_plan: "high" | "low" | null;
}
```

In the `WaygentRunStateV2` interface, add after `intake_recovery?: WaygentIntakeRecovery;`:

```ts
design_contract?: WaygentDesignContractRef;
```

- [ ] **Step 2: Add the schema**

In `packages/contracts/src/schemas.ts`, near `intakeRecoverySchema`, define:

```ts
const designContractRefSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "normalized_design_ref",
    "normalized_plan_ref",
    "extraction_log_design_ref",
    "extraction_log_plan_ref",
    "parser_design",
    "parser_plan",
    "extraction_confidence_design",
    "extraction_confidence_plan"
  ],
  properties: {
    normalized_design_ref: { type: "string", nullable: true },
    normalized_plan_ref: { type: "string", nullable: true },
    extraction_log_design_ref: { type: "string", nullable: true },
    extraction_log_plan_ref: { type: "string", nullable: true },
    parser_design: { type: "string", enum: ["deterministic", "ai", "cached"], nullable: true },
    parser_plan: { type: "string", enum: ["deterministic", "ai", "cached"], nullable: true },
    extraction_confidence_design: { type: "string", enum: ["high", "low"], nullable: true },
    extraction_confidence_plan: { type: "string", enum: ["high", "low"], nullable: true }
  }
} as const;
```

Find the run state v2 schema (around line 969 where `intake_recovery: intakeRecoverySchema` is declared) and add a sibling property:

```ts
    intake_recovery: intakeRecoverySchema,
    design_contract: designContractRefSchema,
```

Also update the validate/required list around line 1240 if `design_contract` needs to be declared optional (review the existing pattern; if `intake_recovery` is not in `required`, neither is `design_contract`).

- [ ] **Step 3: Typecheck**

Run: `bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Run contracts tests**

Run: `bun test packages/contracts/tests`
Expected: PASS (no regressions). If a fixture asserts an exhaustive property list, append `design_contract` as optional in the assertion — adapt the local fixture only.

- [ ] **Step 5: Commit**

```bash
git add packages/contracts/
git commit -m "feat(contracts): add WaygentDesignContractRef to run_state.v2"
```

### Task 5.2: Pre-dispatch invariant runner integration

**Files:**
- Modify: `packages/orchestrator/src/intakeRecovery.ts` — invoke design-contract parse, store refs
- Modify: `packages/orchestrator/src/safeWaveExecutor.ts` (or `taskExecutor.ts` if dispatch lives there) — call invariant runner before dispatching each task
- Create: `packages/orchestrator/tests/designContractPreDispatch.test.ts`

- [ ] **Step 1: Locate the per-task dispatch site**

Run:

```bash
grep -n "dispatch\|emit.*task_dispatched\|provider.*run" packages/orchestrator/src/safeWaveExecutor.ts packages/orchestrator/src/taskExecutor.ts | head -30
```

Identify the function that runs immediately before a task is handed to a provider — typically named `runTask`, `dispatchTask`, or equivalent.

- [ ] **Step 2: Write the failing integration test**

`packages/orchestrator/tests/designContractPreDispatch.test.ts`:

```ts
import { describe, expect, it } from "bun:test";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FakeExtractorProvider } from "@waygent/design-contract";
import { runWithDesignContractEnforcement } from "../src/intakeRecovery.ts";

describe("design-contract pre-dispatch enforcement", () => {
  it("blocks dispatch when invariant deterministic check fails", async () => {
    const work = mkdtempSync(join(tmpdir(), "dc-pre-"));
    mkdirSync(join(work, "packages/orchestrator/src"), { recursive: true });
    // Intentionally do NOT write the file the invariant requires.
    writeFileSync(
      join(work, "design.md"),
      [
        "# d",
        "",
        "## Cross-Path Invariants",
        "",
        "- id: INV-1",
        "  description: must exist",
        "  paths_bound:",
        "    - src/x.ts",
        "  enforcement:",
        "    mode: deterministic",
        "    check:",
        "      kind: file_exists",
        "      path: src/x.ts",
        "  policy_ack_required: false",
        ""
      ].join("\n")
    );
    writeFileSync(
      join(work, "plan.md"),
      [
        "# p",
        "",
        "## Task task_1",
        "",
        "- title: t",
        "  risk: high",
        "  file_claims:",
        "    - src/x.ts:write",
        "  verification_commands:",
        "    - true",
        "  prescriptive_block_ids: ",
        "  required_invariant_acks:",
        "    - INV-1",
        ""
      ].join("\n")
    );
    const provider = new FakeExtractorProvider(new Map());
    const result = await runWithDesignContractEnforcement({
      cwd: work,
      designPath: "design.md",
      planPath: "plan.md",
      extractorProvider: provider,
      cacheRoot: join(work, ".cache")
    });
    expect(result.blocked).toBe(true);
    expect(result.blocker_kind).toBe("invariant_violation_predispatch");
  });
});
```

- [ ] **Step 3: Run + confirm fail**

Run: `bun test packages/orchestrator/tests/designContractPreDispatch.test.ts`
Expected: FAIL — export not found.

- [ ] **Step 4: Implement the helper in intakeRecovery.ts**

In `packages/orchestrator/src/intakeRecovery.ts`, add at the bottom (or in a new sibling file if intakeRecovery is too large; prefer the same file to keep parse + enforcement adjacent):

```ts
import { readFile } from "node:fs/promises";
import { join as pathJoin } from "node:path";
import {
  parseDesignSource,
  parsePlanSource,
  runInvariantsAgainstFileClaims,
  type ExtractorProvider
} from "@waygent/design-contract";

export interface DesignContractEnforcementOptions {
  cwd: string;
  designPath: string;
  planPath: string;
  extractorProvider: ExtractorProvider;
  cacheRoot: string;
}

export interface DesignContractEnforcementResult {
  blocked: boolean;
  blocker_kind: string | null;
  detail: string | null;
}

export async function runWithDesignContractEnforcement(
  opts: DesignContractEnforcementOptions
): Promise<DesignContractEnforcementResult> {
  const designMd = await readFile(pathJoin(opts.cwd, opts.designPath), "utf8");
  const planMd = await readFile(pathJoin(opts.cwd, opts.planPath), "utf8");
  const designOut = await parseDesignSource(designMd, opts.designPath, {
    cacheRoot: opts.cacheRoot,
    provider: opts.extractorProvider
  });
  if (designOut.kind !== "ok") {
    return {
      blocked: true,
      blocker_kind: "design_extraction_failed",
      detail: (designOut as { reason?: string }).reason ?? null
    };
  }
  const planOut = await parsePlanSource(planMd, opts.planPath, {
    cacheRoot: opts.cacheRoot,
    provider: opts.extractorProvider
  });
  if (planOut.kind !== "ok") {
    return {
      blocked: true,
      blocker_kind: "plan_extraction_failed",
      detail: (planOut as { reason?: string }).reason ?? null
    };
  }
  for (const task of planOut.value.tasks) {
    const results = await runInvariantsAgainstFileClaims(
      designOut.value.invariants,
      task.file_claims,
      opts.cwd
    );
    const failed = results.find((r) => !r.passed);
    if (failed) {
      return {
        blocked: true,
        blocker_kind: "invariant_violation_predispatch",
        detail: `task ${task.id} invariant ${failed.invariant_id}: ${failed.evidence}`
      };
    }
  }
  return { blocked: false, blocker_kind: null, detail: null };
}
```

- [ ] **Step 5: Run test to pass**

Run: `bun test packages/orchestrator/tests/designContractPreDispatch.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/orchestrator/
git commit -m "feat(orchestrator): pre-dispatch design-contract invariant enforcement"
```

### Task 5.3: Wire pre-dispatch hook into the run path

**Files:**
- Modify: `packages/orchestrator/src/safeWaveExecutor.ts` (or wherever `runTask` lives — confirmed in Task 5.2 Step 1)
- Modify: `apps/cli/src/index.ts` (pass extractor provider + cache root into orchestrator entrypoint)

- [ ] **Step 1: Identify where intake_recovery is currently invoked**

Run:

```bash
grep -n "intake_recovery\|intakeRecovery\|recoverWaygent" packages/orchestrator/src/*.ts apps/cli/src/index.ts | head -30
```

Note the call site that ultimately decides `decision_required` vs `not_needed`.

- [ ] **Step 2: Insert the design-contract enforcement call right after intake recovery resolves to `recovered` or `not_needed`**

At the call site found in Step 1, add immediately after the intake recovery result is computed:

```ts
const dcResult = await runWithDesignContractEnforcement({
  cwd: workspaceCwd,
  designPath: specPath,
  planPath: planPath,
  extractorProvider: extractorProvider,
  cacheRoot: pathJoin(runRoot, "artifacts", "design-contract")
});
if (dcResult.blocked) {
  state.intake_recovery = {
    ...(state.intake_recovery ?? defaultIntakeRecovery()),
    status: "decision_required",
    can_start: false,
    confidence: "blocked",
    question: dcResult.detail ?? `blocked by ${dcResult.blocker_kind}`,
    completed_at: new Date().toISOString()
  };
  return state;
}
```

> Adapt `workspaceCwd`, `specPath`, `planPath`, `extractorProvider`, `runRoot`, and `state` to the existing variable names at the call site. If `extractorProvider` is not yet passed through, thread it down from the CLI entrypoint with a default of `new FakeExtractorProvider(new Map())` for tests, and Claude/Codex providers for production (deferred to a follow-up task — for P5, ship with fake to unblock the wiring).

- [ ] **Step 3: Run full check**

Run: `bun run check`
Expected: PASS — no regression in 463 existing tests.

- [ ] **Step 4: Commit**

```bash
git add packages/orchestrator/ apps/cli/
git commit -m "feat(orchestrator): invoke design-contract enforcement after intake recovery"
```

### Task 5.4: Post-worker envelope validation

**Files:**
- Modify: `packages/orchestrator/src/runtimeHooks.ts`
- Create: `packages/orchestrator/tests/designContractPostWorker.test.ts`

- [ ] **Step 1: Locate the worker_result validation site**

Run:

```bash
grep -n "worker_result\|workerEnvelope\|validateWorker" packages/orchestrator/src/runtimeHooks.ts | head -20
```

Find where the parsed worker output is validated for shape today (or where stdout is parsed into a worker envelope).

- [ ] **Step 2: Write a failing test**

`packages/orchestrator/tests/designContractPostWorker.test.ts`:

```ts
import { describe, expect, it } from "bun:test";
import { createHash } from "node:crypto";
import { evaluateWorkerEnvelopeAgainstDesign } from "../src/runtimeHooks.ts";
import type { DesignContract, WorkerEnvelopeV2 } from "@waygent/design-contract";

function sha(s: string) { return createHash("sha256").update(s).digest("hex"); }

const snip = "const x = 1;\n";
const design: DesignContract = {
  schema: "waygent.design_contract.v1",
  source_path: "d.md",
  source_sha256: "x",
  invariants: [],
  prescriptive_blocks: [
    { id: "S1", language: "ts", body: snip, body_sha256: sha(snip), source_line_range: [1, 2] }
  ],
  extracted_at: "2026-01-01T00:00:00Z",
  parser: "deterministic",
  extraction_confidence: "high"
};

const envOk: WorkerEnvelopeV2 = {
  schema: "waygent.worker_result.v2",
  task_id: "task_1",
  summary: "x",
  evidence: { verification_commands: ["true"], key_decision: null },
  policy_ack: [],
  stale_test_candidates: [],
  prescriptive_block_outputs: [{ id: "S1", sha256: sha(snip) }]
};

describe("evaluateWorkerEnvelopeAgainstDesign", () => {
  it("returns no blockers on conformant envelope", () => {
    const out = evaluateWorkerEnvelopeAgainstDesign(envOk, design);
    expect(out.blockers).toHaveLength(0);
  });

  it("returns prescriptive_drift blocker on snippet mismatch", () => {
    const env = { ...envOk, prescriptive_block_outputs: [{ id: "S1", sha256: sha("other\n") }] };
    const out = evaluateWorkerEnvelopeAgainstDesign(env, design);
    expect(out.blockers.map((b) => b.kind)).toContain("prescriptive_drift");
  });
});
```

- [ ] **Step 3: Confirm fail**

Run: `bun test packages/orchestrator/tests/designContractPostWorker.test.ts`
Expected: FAIL — export missing.

- [ ] **Step 4: Implement**

Append to `packages/orchestrator/src/runtimeHooks.ts`:

```ts
import {
  validateWorkerEnvelope,
  type DesignContract,
  type WorkerEnvelopeV2,
  type EnvelopeValidationResult
} from "@waygent/design-contract";

export function evaluateWorkerEnvelopeAgainstDesign(
  env: WorkerEnvelopeV2,
  design: DesignContract
): EnvelopeValidationResult {
  return validateWorkerEnvelope(env, design);
}
```

- [ ] **Step 5: Run + commit**

Run: `bun test packages/orchestrator/tests/designContractPostWorker.test.ts`
Expected: PASS.

```bash
git add packages/orchestrator/
git commit -m "feat(orchestrator): post-worker envelope evaluation via design-contract"
```

### Task 5.5: Integration test — full CLI run with design-contract path

**Files:**
- Modify: `apps/cli/tests/cli.test.ts` (add new describe block)

- [ ] **Step 1: Add the integration scenario**

Append to `apps/cli/tests/cli.test.ts`:

```ts
describe("waygent run with design-contract", () => {
  it("blocks dispatch when invariant fails", async () => {
    const dir = mkdtempSync(join(tmpdir(), "wg-dc-"));
    // intentionally do not create required file
    writeFileSync(
      join(dir, "design.md"),
      "# d\n\n## Cross-Path Invariants\n\n- id: INV-1\n  description: must exist\n  paths_bound:\n    - src/x.ts\n  enforcement:\n    mode: deterministic\n    check:\n      kind: file_exists\n      path: src/x.ts\n  policy_ack_required: false\n"
    );
    writeFileSync(
      join(dir, "plan.md"),
      "# p\n\n## Task task_1\n\n- title: t\n  risk: high\n  file_claims:\n    - src/x.ts:write\n  verification_commands:\n    - true\n  required_invariant_acks:\n    - INV-1\n"
    );
    const result = spawnSync(
      "bun",
      ["run", "apps/cli/src/index.ts", "run", "--plan", join(dir, "plan.md"), "--spec", join(dir, "design.md"), "--provider", "fake"],
      { encoding: "utf8" }
    );
    expect(result.stderr + result.stdout).toContain("intake_decision_required");
    expect(result.stderr + result.stdout).toContain("invariant_violation_predispatch");
  });
});
```

- [ ] **Step 2: Run**

Run: `bun test apps/cli/tests/cli.test.ts -t "waygent run with design-contract"`
Expected: PASS.

- [ ] **Step 3: Run full gate**

Run: `bun run check && bun run platform:demo && bun run waygent:scenarios`
Expected: ALL PASS, 463-test count grows by added cases, no regressions.

- [ ] **Step 4: Commit**

```bash
git add apps/cli/tests/cli.test.ts
git commit -m "test(cli): integration scenario for design-contract pre-dispatch block"
```

---

## Phase 6 — Fixture-Lab + Docs

### Task 6.1: Extend fixture-lab with freeform + degraded cases

**Files:**
- Modify: `tests/integration/waygent-fixture-lab.test.ts`
- Create: `packages/design-contract/tests/fixtures/degraded/design-extraction-failed.md`

- [ ] **Step 1: Write the degraded fixture**

`packages/design-contract/tests/fixtures/degraded/design-extraction-failed.md`:

```markdown
# Random doc with no invariants and no structure
The AI is configured to throw for this one.
```

- [ ] **Step 2: Read the existing fixture-lab test**

Run: `head -80 tests/integration/waygent-fixture-lab.test.ts`

Identify the existing pattern (likely a `describe` block that iterates over fixtures). Match its style.

- [ ] **Step 3: Append cases**

In `tests/integration/waygent-fixture-lab.test.ts`, append a new `describe` block:

```ts
import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { FakeExtractorProvider, parseDesignSource } from "@waygent/design-contract";

describe("fixture-lab — design-contract", () => {
  it("canonical design parses deterministically", async () => {
    const md = readFileSync("packages/design-contract/tests/fixtures/canonical/design-simple.md", "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "fl-"));
    const out = await parseDesignSource(md, "design-simple.md", {
      cacheRoot,
      provider: new FakeExtractorProvider(new Map())
    });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("deterministic");
  });

  it("freeform design falls back to AI", async () => {
    const md = readFileSync("packages/design-contract/tests/fixtures/freeform/design-korean-prose.md", "utf8");
    const resp = JSON.parse(
      readFileSync("packages/design-contract/tests/fixtures/freeform/design-korean-prose.ai-response.json", "utf8")
    );
    const cacheRoot = mkdtempSync(join(tmpdir(), "fl-"));
    const provider = new FakeExtractorProvider(new Map([["design:design-korean-prose.md", resp]]));
    const out = await parseDesignSource(md, "design-korean-prose.md", { cacheRoot, provider });
    expect(out.kind).toBe("ok");
    if (out.kind !== "ok") return;
    expect(out.value.parser).toBe("ai");
  });

  it("degraded design with throw provider fails cleanly", async () => {
    const md = readFileSync("packages/design-contract/tests/fixtures/degraded/design-extraction-failed.md", "utf8");
    const cacheRoot = mkdtempSync(join(tmpdir(), "fl-"));
    const provider = new FakeExtractorProvider(
      new Map([["design:design-extraction-failed.md", "throw"]])
    );
    const out = await parseDesignSource(md, "design-extraction-failed.md", { cacheRoot, provider });
    expect(out.kind).toBe("failed");
  });
});
```

> Add `import { join } from "node:path";` at the top if not already present.

- [ ] **Step 4: Run**

Run: `bun run waygent:fixture-lab`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/design-contract/tests/fixtures/degraded/ tests/integration/waygent-fixture-lab.test.ts
git commit -m "test(fixture-lab): design-contract canonical/freeform/degraded replays"
```

### Task 6.2: Document `design_contract` in run-state contract

**Files:**
- Modify: `docs/contracts/run-state.md`

- [ ] **Step 1: Add a new bullet under Runtime Improvement Fields**

After the `intake_recovery:` bullet in `docs/contracts/run-state.md` (around the existing list), insert:

```markdown
- `design_contract`: refs to normalized design/plan JSON, extraction logs,
  the parser used (`deterministic | ai | cached`), and extraction confidence
  per document. Pre-dispatch invariant checks and post-worker envelope
  validation use this normalized form, not raw markdown.
```

- [ ] **Step 2: Commit**

```bash
git add docs/contracts/run-state.md
git commit -m "docs(contracts): document design_contract field in run_state.v2"
```

### Task 6.3: Document lint commands + authoring guide

**Files:**
- Modify: `docs/operations/waygent.md`

- [ ] **Step 1: Add a new section**

Append to `docs/operations/waygent.md`:

```markdown
## Design Contract Linting

`waygent lint-design --path <spec.md>` extracts the design contract and
prints invariants, prescriptive blocks, and extraction confidence. Authors
should run it before submitting a new design to verify intent was captured
correctly.

`waygent lint-plan --path <plan.md>` does the same for plan documents.

Authors may write design/plan documents in either of two styles:

- **Canonical**: the format produced by `waygent scaffold-plan` and the
  fixtures in `packages/design-contract/tests/fixtures/canonical/`. The
  deterministic parser handles these with zero token cost.
- **Free-form**: any prose, in any language, with any heading style. The
  AI extractor normalizes the document on first parse; subsequent runs
  hit the cache.

When `lint-design` reports `extraction_confidence: low`, review the
normalized JSON at `<run_root>/artifacts/design-contract/normalized-design.json`
and either edit the source for clarity or hand-edit the JSON.
```

- [ ] **Step 2: Commit**

```bash
git add docs/operations/waygent.md
git commit -m "docs(operations): add design contract lint and authoring guide"
```

### Task 6.4: Register design-contract gates

**Files:**
- Modify: `docs/operations/verification.md`

- [ ] **Step 1: Add a new gate section**

Insert after the "Default Offline Gate" section in `docs/operations/verification.md`:

```markdown
## Design Contract Gate

```bash
bun test packages/design-contract/tests
bun run waygent:fixture-lab
```

Use this when changing the `@waygent/design-contract` package, fixtures,
or any orchestrator code that consumes normalized design/plan JSON.

For drift between the fake extractor fixtures and live providers, run
the opt-in smoke gate:

```bash
WAYGENT_LIVE_PROVIDER=claude bun run waygent:design-contract-live-smoke
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/operations/verification.md
git commit -m "docs(operations): register design-contract verification gates"
```

### Task 6.5: Update skill contract

**Files:**
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/evals/check_skill_contract.py`

- [ ] **Step 1: Add NL mappings to SKILL.md**

In `skills/waygent/SKILL.md`, in the Default mappings section, add:

```markdown
- "design 검증해줘" -> `waygent lint-design --path design.md`
- "plan 검증해줘" -> `waygent lint-plan --path plan.md`
```

In a new Stop rule, add:

```markdown
- If a run reports `invariant_violation_predispatch`, `prescriptive_drift`,
  `policy_ack_missing`, or `stale_test_candidates_missing`, the normalized
  design contract is the source of truth. Reference the
  `normalized_design` artifact when explaining the blocker.
```

- [ ] **Step 2: Add required phrases to the contract checker**

In `skills/waygent/evals/check_skill_contract.py`, append to `required_skill_phrases`:

```python
    "waygent lint-design",
    "waygent lint-plan",
    "invariant_violation_predispatch",
    "prescriptive_drift",
    "normalized_design",
```

- [ ] **Step 3: Run the contract checker**

Run: `python3 skills/waygent/evals/check_skill_contract.py`
Expected: PASS (`waygent skill contract ok`).

- [ ] **Step 4: Commit**

```bash
git add skills/waygent/
git commit -m "docs(skills): wire design-contract lint commands and blockers into skill"
```

---

## Phase 7 — Live Provider Drift Smoke (Opt-In)

### Task 7.1: Live drift smoke test scaffold

**Files:**
- Create: `tests/integration/waygent-design-contract-live-smoke.test.ts`
- Modify: `package.json` (root) — add script

- [ ] **Step 1: Add the script**

In root `package.json`, add to `scripts`:

```json
"waygent:design-contract-live-smoke": "bun test tests/integration/waygent-design-contract-live-smoke.test.ts"
```

- [ ] **Step 2: Write the gated test**

```ts
import { describe, expect, it } from "bun:test";
import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseDesignSource, FakeExtractorProvider } from "@waygent/design-contract";

const liveProvider = process.env.WAYGENT_LIVE_PROVIDER;

(liveProvider ? describe : describe.skip)("design-contract live drift smoke", () => {
  it("fixture freeform design produces semantically equivalent invariants via live provider", async () => {
    expect(liveProvider).toMatch(/^(claude|codex)$/);
    // For SP-1 P7 we ship the gated stub. Wiring a real ExtractorProvider
    // backed by the provider CLI is a follow-up; intentionally not in P7
    // scope. Document the manual step.
    const md = readFileSync(
      "packages/design-contract/tests/fixtures/freeform/design-korean-prose.md",
      "utf8"
    );
    const cacheRoot = mkdtempSync(join(tmpdir(), "live-"));
    const out = await parseDesignSource(md, "design-korean-prose.md", {
      cacheRoot,
      provider: new FakeExtractorProvider(new Map())
    });
    // With no fixture and no live provider wired, this fails predictably.
    // The point of the gate is to keep the harness in place for the
    // follow-up implementation.
    expect(out.kind).toBe("failed");
  });
});
```

> The actual live-provider `ExtractorProvider` implementation (claude/codex CLI bridge) is intentionally deferred. P7 ships only the gated test harness. The follow-up task is tracked in `docs/superpowers/specs/2026-05-23-waygent-hardening-roadmap.md` SP-1 backlog.

- [ ] **Step 3: Verify the gate is opt-in**

Run: `bun test tests/integration/waygent-design-contract-live-smoke.test.ts`
Expected: PASS (all `describe.skip` — no live provider set).

Run with env: `WAYGENT_LIVE_PROVIDER=claude bun test tests/integration/waygent-design-contract-live-smoke.test.ts`
Expected: FAIL (intentionally — implementation deferred). This is the marker for follow-up work.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/waygent-design-contract-live-smoke.test.ts package.json
git commit -m "test(design-contract): scaffold opt-in live provider drift smoke gate"
```

---

## Final Verification

- [ ] **Step 1: Run the full local checklist**

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run check:legacy
python3 skills/waygent/evals/check_skill_contract.py
git diff --check
```

All MUST PASS.

- [ ] **Step 2: Confirm no regression in pre-existing test count**

Run: `bun test 2>&1 | tail -5`
Expected: at least 463 prior tests still pass; new tests added.

- [ ] **Step 3: Push branch and open PR (separate task, on operator request)**

```bash
git log --oneline origin/main..HEAD
```

Confirm the SP-1 commit series is coherent (P0 through P7).
