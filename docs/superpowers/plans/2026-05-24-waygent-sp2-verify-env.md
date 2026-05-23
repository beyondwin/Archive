# Waygent SP-2 Verify Env Worktree-Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the silent fast-path failure where worker worktree edits to `@waygent/*` packages are masked by main's `node_modules` during verification. Add an `isolated_workspace_resolve` strategy with content-addressed snapshot cache, strict-block semantics on isolation failure, and per-task strategy selection.

**Architecture:** Split `verificationEnvironment.ts` into a thin dispatcher plus two strategy modules: `inheritStrategy` (existing fast path) and `isolatedStrategy/` (new). A pure `strategyDecider` picks between them using either an explicit plan-task field or a `git status --porcelain` analysis of the worker's worktree. The isolated path runs `bun install` once per content-addressed snapshot, caches the result under `.waygent/verify-env-snapshot/<key>/`, and materializes it into each worktree while rewriting `@waygent/*` entries to worktree-local `packages/*`. Failure surfaces as `runway.verification_environment` with `isolation_status="unavailable"` and never falls through silently.

**Tech Stack:** TypeScript, Bun test runner, `@waygent/orchestrator`, `@waygent/design-contract`, `apps/cli`, Node.js fs/child_process.

---

## Context

**Spec:** `docs/superpowers/specs/2026-05-24-waygent-sp2-verify-env-design.md`

**Parent roadmap:** `docs/superpowers/specs/2026-05-23-waygent-hardening-roadmap.md` (SP-2 entry)

**Failure mode this closes:** Failure Mode A in the hardening roadmap — `inherit_node_modules` makes the worker worktree's `@waygent/*` invisible to integration tests; main's source is resolved instead.

**Brainstorming decisions baked in:** Q1=(D) explicit tag + worktree-diff fallback; Q2=(D) single `bun install` path with snapshot cache; Q3=(A) strict block on isolation failure, no auto-retry, no degrade.

**Constraints:**

- No new external dependencies. `bun` is already required.
- Existing `WAYGENT_DISABLE_VERIFICATION_ENV=1` kill switch must keep working.
- `bun run check`, `bun run platform:demo`, `bun run waygent:scenarios` must keep passing.
- Existing evidence consumers read `status`, `strategy`, `cleanup_status` only — new fields must be additive.
- Plans without `verify_isolation` must keep working unchanged.

**Out of scope:**

- Auto-retry, degrade fallback (Q3).
- `error_code` taxonomy (SP-3).
- `apply --up-to` / `retry --task` (SP-4).

**SP-1 Contract Obligations (workers must satisfy when executing this plan):**

- Populate `worker_result.evidence.policy_ack` for CPI-SP2-1, CPI-SP2-2,
  CPI-SP2-3 (spec Section 9.1). One line each describing where and how the
  invariant is enforced.
- Populate `worker_result.evidence.stale_test_candidates` (expected `[]` —
  inheritStrategy tests are preserved by design; flag anything otherwise).
- Populate `worker_result.evidence.design_ambiguity_flagged`. Spec Section
  5.2 fixed `cache_key` ordering; the only known live ambiguity is
  hardlink-vs-symlink for the materialize step (spec Section 11) — resolve
  empirically in T3d Step 4 and amend the spec before T4.
- Code blocks in this plan: types and the failure table are
  **prescriptive** (copy verbatim). Pseudocode in spec Section 5.1 and the
  example implementations in T3a–T3d are **illustrative** — worker may
  improve the implementation provided invariants and tests still hold.

## File Structure

**New files:**

- `packages/orchestrator/src/inheritStrategy.ts` — fast path, extracted from current `verificationEnvironment.ts`.
- `packages/orchestrator/src/strategyDecider.ts` — pure function selecting strategy from plan field + worktree diff.
- `packages/orchestrator/src/isolatedStrategy/index.ts` — orchestrates cache lookup → prepare → materialize → manifest verify.
- `packages/orchestrator/src/isolatedStrategy/cacheKey.ts` — content-addressed key from `bun.lock` + workspace package manifests.
- `packages/orchestrator/src/isolatedStrategy/snapshot.ts` — read/write `.waygent/verify-env-snapshot/<key>/` and LRU eviction.
- `packages/orchestrator/src/isolatedStrategy/workspaceManifest.ts` — enumerate `@waygent/*` from `packages/*/package.json`.
- `packages/orchestrator/tests/strategyDecider.test.ts`
- `packages/orchestrator/tests/cacheKey.test.ts`
- `packages/orchestrator/tests/workspaceManifest.test.ts`
- `packages/orchestrator/tests/isolatedStrategy.integ.test.ts` (gated by `WAYGENT_RUN_INTEG_TESTS=1`)
- `tests/sp2-reproduction/cross-package-edit.test.ts`
- `docs/operations/verification.md`

**Modified files:**

- `packages/orchestrator/src/verificationEnvironment.ts` — shrunk to dispatcher; signature gains optional `task`/`worktreeDiff`.
- `packages/orchestrator/src/taskExecutor.ts` — collect worktree diff, thread it through, emit new `runway.verification_environment` event on isolated failure.
- `packages/orchestrator/tests/verificationEnvironment.test.ts` → renamed `inheritStrategy.test.ts`; assertions unchanged.
- `packages/design-contract/src/types.ts` — add `verify_isolation` to `PlanTask`.
- `packages/design-contract/src/parse/` — parse the new field from plan markdown.
- `AGENTS.md` — short note on verify env isolation behavior.
- `skills/waygent/SKILL.md` — `verify_isolation` plan-author guide.

---

## Task 1: Extract `inheritStrategy` (zero behavior change)

**Files:**
- Create: `packages/orchestrator/src/inheritStrategy.ts`
- Modify: `packages/orchestrator/src/verificationEnvironment.ts`
- Rename: `packages/orchestrator/tests/verificationEnvironment.test.ts` → `packages/orchestrator/tests/inheritStrategy.test.ts`

- [ ] **Step 1: Rename existing test file.**

```bash
git mv packages/orchestrator/tests/verificationEnvironment.test.ts \
       packages/orchestrator/tests/inheritStrategy.test.ts
```

Inside the renamed file, update any `from "../src/verificationEnvironment"` import to `from "../src/inheritStrategy"`. Keep all test assertions identical.

- [ ] **Step 2: Run the renamed test — expect failure (import broken).**

```bash
bun test packages/orchestrator/tests/inheritStrategy.test.ts
```

Expected: FAIL with `Cannot find module ../src/inheritStrategy`.

- [ ] **Step 3: Create `packages/orchestrator/src/inheritStrategy.ts` by moving the current implementation verbatim.**

```typescript
import { existsSync, lstatSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";

export interface InheritStrategyEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: "inherit_node_modules" | "none";
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedInheritStrategy {
  evidence: InheritStrategyEvidence;
  cleanup(): void;
}

export function prepareInheritStrategy(input: {
  workspace: string;
  worktree: string;
  disabled?: boolean;
}): PreparedInheritStrategy {
  const sourceNodeModules = join(input.workspace, "node_modules");
  const worktreeNodeModules = join(input.worktree, "node_modules");
  const evidence: InheritStrategyEvidence = {
    status: "skipped",
    strategy: "none",
    created_paths: [],
    cleanup_status: "not_needed",
    reason: null
  };

  if (input.disabled) {
    evidence.reason = "disabled";
    return { evidence, cleanup: () => {} };
  }
  if (!existsSync(sourceNodeModules)) {
    evidence.reason = "source_node_modules_missing";
    return { evidence, cleanup: () => {} };
  }
  if (existsSync(worktreeNodeModules)) {
    evidence.reason = "worktree_node_modules_exists";
    return { evidence, cleanup: () => {} };
  }

  try {
    symlinkSync(sourceNodeModules, worktreeNodeModules, "dir");
    evidence.status = "prepared";
    evidence.strategy = "inherit_node_modules";
    evidence.created_paths = ["node_modules"];
    evidence.cleanup_status = "pending";
  } catch (error) {
    evidence.status = "failed";
    evidence.reason = error instanceof Error ? error.message : String(error);
    evidence.cleanup_status = "not_needed";
  }

  return {
    evidence,
    cleanup() {
      if (evidence.cleanup_status !== "pending") return;
      try {
        if (existsSync(worktreeNodeModules)) {
          if (!lstatSync(worktreeNodeModules).isSymbolicLink()) {
            evidence.cleanup_status = "failed";
            evidence.reason = "node_modules cleanup skipped: created path is not a symbolic link";
            return;
          }
          rmSync(worktreeNodeModules, { force: true, recursive: true });
        }
        evidence.cleanup_status = "removed";
      } catch (error) {
        evidence.cleanup_status = "failed";
        evidence.reason = error instanceof Error ? error.message : String(error);
      }
    }
  };
}
```

- [ ] **Step 4: Replace `packages/orchestrator/src/verificationEnvironment.ts` with a dispatcher that delegates to inheritStrategy (no new strategies yet).**

```typescript
import { prepareInheritStrategy, type InheritStrategyEvidence, type PreparedInheritStrategy } from "./inheritStrategy";

export type VerificationStrategy = "none" | "inherit_node_modules" | "isolated_workspace_resolve";

// Backward-compat shape: callers still read these fields from evidence.
// Additional fields (decision, isolation_status, cache, isolated_packages, resolved_paths)
// are added in Task 4 once the dispatcher consumes the decider output.
export type VerificationEnvironmentEvidence = InheritStrategyEvidence;
export type PreparedVerificationEnvironment = PreparedInheritStrategy;

export function prepareVerificationEnvironment(input: {
  workspace: string;
  worktree: string;
  disabled?: boolean;
}): PreparedVerificationEnvironment {
  return prepareInheritStrategy(input);
}
```

- [ ] **Step 5: Adjust import in the renamed test to call `prepareInheritStrategy`.**

Inside `packages/orchestrator/tests/inheritStrategy.test.ts`, replace every `prepareVerificationEnvironment(` with `prepareInheritStrategy(` and update the import line:

```typescript
import { prepareInheritStrategy } from "../src/inheritStrategy";
```

- [ ] **Step 6: Run the renamed test — expect PASS.**

```bash
bun test packages/orchestrator/tests/inheritStrategy.test.ts
```

Expected: all original assertions pass.

- [ ] **Step 7: Run the full orchestrator test suite to confirm zero behavior change.**

```bash
bun test packages/orchestrator
```

Expected: all tests pass.

- [ ] **Step 8: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 9: Commit.**

```bash
git add packages/orchestrator/src/inheritStrategy.ts \
        packages/orchestrator/src/verificationEnvironment.ts \
        packages/orchestrator/tests/inheritStrategy.test.ts
git commit -m "refactor(orchestrator): extract inheritStrategy from verificationEnvironment (SP-2 T1)"
```

---

## Task 2: `strategyDecider` (pure function, no callers yet)

**Files:**
- Create: `packages/orchestrator/src/strategyDecider.ts`
- Create: `packages/orchestrator/tests/strategyDecider.test.ts`

- [ ] **Step 1: Write the failing test.**

```typescript
// packages/orchestrator/tests/strategyDecider.test.ts
import { describe, expect, it } from "bun:test";
import { decideVerificationStrategy } from "../src/strategyDecider";

describe("decideVerificationStrategy", () => {
  it("returns isolated with reason=explicit_tag when verify_isolation=isolated", () => {
    const out = decideVerificationStrategy({ requested: "isolated", worktreeDiff: [] });
    expect(out).toEqual({ resolved: "isolated", reason: "explicit_tag" });
  });

  it("returns fast with reason=explicit_tag when verify_isolation=fast even with cross-package diff", () => {
    const out = decideVerificationStrategy({
      requested: "fast",
      worktreeDiff: [" M packages/a/src/x.ts", " M packages/b/src/y.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "explicit_tag" });
  });

  it("auto: returns fast with reason=diff_no_package_changes when no packages touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M apps/cli/src/index.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "diff_no_package_changes" });
  });

  it("auto: returns fast with reason=diff_single_package when exactly one packages/* is touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M packages/orchestrator/src/x.ts", " M packages/orchestrator/tests/x.test.ts"]
    });
    expect(out).toEqual({ resolved: "fast", reason: "diff_single_package" });
  });

  it("auto: returns isolated with reason=diff_cross_package when two or more packages/* touched", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M packages/a/src/x.ts", " M packages/b/src/y.ts"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_cross_package" });
  });

  it("auto: returns isolated with reason=diff_lockfile_touched when bun.lock changes", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M bun.lock"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_lockfile_touched" });
  });

  it("auto: returns isolated when root package.json changes", () => {
    const out = decideVerificationStrategy({
      requested: "auto",
      worktreeDiff: [" M package.json"]
    });
    expect(out).toEqual({ resolved: "isolated", reason: "diff_lockfile_touched" });
  });

  it("treats absent verify_isolation as auto", () => {
    const out = decideVerificationStrategy({
      requested: undefined,
      worktreeDiff: [" M apps/cli/src/index.ts"]
    });
    expect(out.resolved).toBe("fast");
  });
});
```

- [ ] **Step 2: Run the test — expect failure (module missing).**

```bash
bun test packages/orchestrator/tests/strategyDecider.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement `strategyDecider.ts`.**

```typescript
// packages/orchestrator/src/strategyDecider.ts

export type VerifyIsolationRequest = "isolated" | "fast" | "auto";

export interface StrategyDecision {
  resolved: "isolated" | "fast";
  reason: string;
}

export interface DeciderInput {
  requested: VerifyIsolationRequest | undefined;
  worktreeDiff: string[]; // lines from `git status --porcelain`
}

const PACKAGE_DIR_PREFIX = "packages/";
const LOCKFILE_PATHS = new Set(["bun.lock", "package.json"]);

export function decideVerificationStrategy(input: DeciderInput): StrategyDecision {
  const requested: VerifyIsolationRequest = input.requested ?? "auto";

  if (requested === "isolated") return { resolved: "isolated", reason: "explicit_tag" };
  if (requested === "fast") return { resolved: "fast", reason: "explicit_tag" };

  const paths = input.worktreeDiff
    .map((line) => extractPath(line))
    .filter((p): p is string => p !== null);

  if (paths.some((p) => LOCKFILE_PATHS.has(p))) {
    return { resolved: "isolated", reason: "diff_lockfile_touched" };
  }

  const packageDirs = new Set<string>();
  for (const p of paths) {
    if (p.startsWith(PACKAGE_DIR_PREFIX)) {
      const rest = p.slice(PACKAGE_DIR_PREFIX.length);
      const slash = rest.indexOf("/");
      const top = slash === -1 ? rest : rest.slice(0, slash);
      if (top.length > 0) packageDirs.add(top);
    }
  }

  if (packageDirs.size === 0) return { resolved: "fast", reason: "diff_no_package_changes" };
  if (packageDirs.size === 1) return { resolved: "fast", reason: "diff_single_package" };
  return { resolved: "isolated", reason: "diff_cross_package" };
}

function extractPath(porcelainLine: string): string | null {
  // `git status --porcelain` lines: "XY path" where XY is two status chars + space.
  // Renamed lines use "R  old -> new"; for our purposes the new path matters.
  if (porcelainLine.length < 4) return null;
  const body = porcelainLine.slice(3).trim();
  const arrow = body.indexOf(" -> ");
  return arrow === -1 ? body : body.slice(arrow + 4);
}
```

- [ ] **Step 4: Run the test — expect PASS.**

```bash
bun test packages/orchestrator/tests/strategyDecider.test.ts
```

Expected: 8 tests pass.

- [ ] **Step 5: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 6: Commit.**

```bash
git add packages/orchestrator/src/strategyDecider.ts \
        packages/orchestrator/tests/strategyDecider.test.ts
git commit -m "feat(orchestrator): strategyDecider pure function (SP-2 T2)"
```

---

## Task 3a: `cacheKey` content-addressed hashing

**Files:**
- Create: `packages/orchestrator/src/isolatedStrategy/cacheKey.ts`
- Create: `packages/orchestrator/tests/cacheKey.test.ts`

- [ ] **Step 1: Write the failing test.**

```typescript
// packages/orchestrator/tests/cacheKey.test.ts
import { describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { computeCacheKey } from "../src/isolatedStrategy/cacheKey";

function makeWorkspace(layout: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "sp2-cachekey-"));
  for (const [path, content] of Object.entries(layout)) {
    const full = join(root, path);
    mkdirSync(join(full, ".."), { recursive: true });
    writeFileSync(full, content);
  }
  return root;
}

describe("computeCacheKey", () => {
  it("returns identical key for identical inputs", () => {
    const ws = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": JSON.stringify({ workspaces: ["packages/*"], dependencies: { foo: "1.0" } }),
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a", version: "0.1.0" }),
      "packages/b/package.json": JSON.stringify({ name: "@waygent/b", version: "0.1.0" })
    });
    expect(computeCacheKey(ws)).toBe(computeCacheKey(ws));
  });

  it("changes when bun.lock contents change", () => {
    const before = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": "{}",
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" })
    });
    const after = makeWorkspace({
      "bun.lock": "lock-v2",
      "package.json": "{}",
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" })
    });
    expect(computeCacheKey(before)).not.toBe(computeCacheKey(after));
  });

  it("changes when a packages/* package.json is added", () => {
    const before = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": "{}",
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" })
    });
    const after = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": "{}",
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" }),
      "packages/b/package.json": JSON.stringify({ name: "@waygent/b" })
    });
    expect(computeCacheKey(before)).not.toBe(computeCacheKey(after));
  });

  it("ignores unrelated root package.json keys (only workspaces/dependencies matter)", () => {
    const before = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": JSON.stringify({ workspaces: ["packages/*"], dependencies: { foo: "1.0" }, description: "before" }),
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" })
    });
    const after = makeWorkspace({
      "bun.lock": "lock-v1",
      "package.json": JSON.stringify({ workspaces: ["packages/*"], dependencies: { foo: "1.0" }, description: "after" }),
      "packages/a/package.json": JSON.stringify({ name: "@waygent/a" })
    });
    expect(computeCacheKey(before)).toBe(computeCacheKey(after));
  });

  it("returns a 64-char hex string", () => {
    const ws = makeWorkspace({
      "bun.lock": "",
      "package.json": "{}"
    });
    expect(computeCacheKey(ws)).toMatch(/^[0-9a-f]{64}$/);
  });
});
```

- [ ] **Step 2: Run — expect failure.**

```bash
bun test packages/orchestrator/tests/cacheKey.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement `cacheKey.ts`.**

```typescript
// packages/orchestrator/src/isolatedStrategy/cacheKey.ts
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export function computeCacheKey(workspace: string): string {
  const hash = createHash("sha256");

  // 1. bun.lock raw bytes
  const lockPath = join(workspace, "bun.lock");
  try {
    hash.update(readFileSync(lockPath));
  } catch {
    // Treat missing lockfile as empty input — still hashable.
  }
  hash.update("\0");

  // 2. packages/*/package.json sorted lexicographically by relative path
  const packagesDir = join(workspace, "packages");
  const entries = safeReaddir(packagesDir)
    .map((name) => join(packagesDir, name, "package.json"))
    .filter((p) => safeIsFile(p))
    .sort((a, b) => a.localeCompare(b));

  for (const p of entries) {
    hash.update(relative(workspace, p));
    hash.update("\0");
    hash.update(readFileSync(p));
    hash.update("\0");
  }

  // 3. Root package.json filtered: only workspaces + dependencies
  try {
    const rootText = readFileSync(join(workspace, "package.json"), "utf8");
    const root = JSON.parse(rootText) as Record<string, unknown>;
    const filtered: Record<string, unknown> = {};
    if (root.workspaces !== undefined) filtered.workspaces = root.workspaces;
    if (root.dependencies !== undefined) filtered.dependencies = root.dependencies;
    const sortedKeys = Object.keys(filtered).sort();
    hash.update(JSON.stringify(filtered, sortedKeys, 0));
  } catch {
    // Missing or invalid root package.json — degrade gracefully, still deterministic.
  }

  return hash.digest("hex");
}

function safeReaddir(path: string): string[] {
  try {
    return readdirSync(path);
  } catch {
    return [];
  }
}

function safeIsFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}
```

- [ ] **Step 4: Run — expect PASS.**

```bash
bun test packages/orchestrator/tests/cacheKey.test.ts
```

Expected: 5 tests pass.

- [ ] **Step 5: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 6: Commit.**

```bash
git add packages/orchestrator/src/isolatedStrategy/cacheKey.ts \
        packages/orchestrator/tests/cacheKey.test.ts
git commit -m "feat(orchestrator): content-addressed cacheKey (SP-2 T3a)"
```

---

## Task 3b: `workspaceManifest` enumeration

**Files:**
- Create: `packages/orchestrator/src/isolatedStrategy/workspaceManifest.ts`
- Create: `packages/orchestrator/tests/workspaceManifest.test.ts`

- [ ] **Step 1: Write the failing test.**

```typescript
// packages/orchestrator/tests/workspaceManifest.test.ts
import { describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { enumerateWaygentPackages, detectManifestDrift } from "../src/isolatedStrategy/workspaceManifest";

function makeWs(packages: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "sp2-manifest-"));
  for (const [dir, name] of Object.entries(packages)) {
    const pkgDir = join(root, "packages", dir);
    mkdirSync(pkgDir, { recursive: true });
    writeFileSync(join(pkgDir, "package.json"), JSON.stringify({ name }));
  }
  return root;
}

describe("enumerateWaygentPackages", () => {
  it("returns @waygent/* package names mapped to relative paths", () => {
    const ws = makeWs({ orchestrator: "@waygent/orchestrator", contracts: "@waygent/contracts" });
    const out = enumerateWaygentPackages(ws);
    expect(out).toEqual({
      "@waygent/orchestrator": "packages/orchestrator",
      "@waygent/contracts": "packages/contracts"
    });
  });

  it("skips packages whose name is not under @waygent/", () => {
    const ws = makeWs({ external: "third-party", orchestrator: "@waygent/orchestrator" });
    const out = enumerateWaygentPackages(ws);
    expect(out).toEqual({ "@waygent/orchestrator": "packages/orchestrator" });
  });

  it("returns empty object when packages/ does not exist", () => {
    const ws = mkdtempSync(join(tmpdir(), "sp2-manifest-empty-"));
    expect(enumerateWaygentPackages(ws)).toEqual({});
  });
});

describe("detectManifestDrift", () => {
  it("returns null when current matches snapshot", () => {
    const snap = { "@waygent/a": "packages/a" };
    const cur = { "@waygent/a": "packages/a" };
    expect(detectManifestDrift(snap, cur)).toBeNull();
  });

  it("returns added-package reason when current has a package the snapshot lacks", () => {
    const snap = { "@waygent/a": "packages/a" };
    const cur = { "@waygent/a": "packages/a", "@waygent/b": "packages/b" };
    const drift = detectManifestDrift(snap, cur);
    expect(drift).not.toBeNull();
    expect(drift!.reason).toContain("@waygent/b");
    expect(drift!.kind).toBe("added");
  });

  it("returns removed-package reason when snapshot has a package the current lacks", () => {
    const snap = { "@waygent/a": "packages/a", "@waygent/b": "packages/b" };
    const cur = { "@waygent/a": "packages/a" };
    const drift = detectManifestDrift(snap, cur);
    expect(drift).not.toBeNull();
    expect(drift!.reason).toContain("@waygent/b");
    expect(drift!.kind).toBe("removed");
  });
});
```

- [ ] **Step 2: Run — expect failure.**

```bash
bun test packages/orchestrator/tests/workspaceManifest.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement `workspaceManifest.ts`.**

```typescript
// packages/orchestrator/src/isolatedStrategy/workspaceManifest.ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

export type WorkspaceManifest = Record<string, string>; // "@waygent/foo" → "packages/foo"

export interface ManifestDrift {
  kind: "added" | "removed";
  reason: string; // e.g. "@waygent/b added since snapshot"
}

export function enumerateWaygentPackages(workspace: string): WorkspaceManifest {
  const result: WorkspaceManifest = {};
  const packagesDir = join(workspace, "packages");
  let entries: string[];
  try {
    entries = readdirSync(packagesDir);
  } catch {
    return result;
  }
  for (const dir of entries) {
    const pkgJson = join(packagesDir, dir, "package.json");
    try {
      if (!statSync(pkgJson).isFile()) continue;
      const parsed = JSON.parse(readFileSync(pkgJson, "utf8")) as { name?: unknown };
      if (typeof parsed.name === "string" && parsed.name.startsWith("@waygent/")) {
        result[parsed.name] = `packages/${dir}`;
      }
    } catch {
      // Ignore unreadable/invalid package.json.
    }
  }
  return result;
}

export function detectManifestDrift(
  snapshot: WorkspaceManifest,
  current: WorkspaceManifest
): ManifestDrift | null {
  for (const name of Object.keys(current)) {
    if (!(name in snapshot)) {
      return { kind: "added", reason: `${name} added since snapshot` };
    }
  }
  for (const name of Object.keys(snapshot)) {
    if (!(name in current)) {
      return { kind: "removed", reason: `${name} removed since snapshot` };
    }
  }
  return null;
}
```

- [ ] **Step 4: Run — expect PASS.**

```bash
bun test packages/orchestrator/tests/workspaceManifest.test.ts
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add packages/orchestrator/src/isolatedStrategy/workspaceManifest.ts \
        packages/orchestrator/tests/workspaceManifest.test.ts
git commit -m "feat(orchestrator): workspaceManifest enumeration + drift detection (SP-2 T3b)"
```

---

## Task 3c: `snapshot` storage with LRU eviction

**Files:**
- Create: `packages/orchestrator/src/isolatedStrategy/snapshot.ts`

This module wraps filesystem I/O for `.waygent/verify-env-snapshot/<key>/`. Unit-test surface is small (LRU eviction logic); the heavier paths run in T3d integration tests.

- [ ] **Step 1: Write the failing test (LRU only).**

```typescript
// packages/orchestrator/tests/snapshotLru.test.ts
import { describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, readdirSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { evictLru } from "../src/isolatedStrategy/snapshot";

function makeSnapshots(root: string, keys: string[]): void {
  let ts = Math.floor(Date.now() / 1000) - keys.length * 60;
  for (const key of keys) {
    const dir = join(root, key);
    mkdirSync(dir, { recursive: true });
    utimesSync(dir, ts, ts);
    ts += 60;
  }
}

describe("evictLru", () => {
  it("keeps newest N snapshots and removes the rest", () => {
    const root = mkdtempSync(join(tmpdir(), "sp2-lru-"));
    makeSnapshots(root, ["k1", "k2", "k3", "k4", "k5", "k6"]);
    evictLru(root, 3);
    const remaining = readdirSync(root).sort();
    expect(remaining).toEqual(["k4", "k5", "k6"]);
  });

  it("is a no-op when count <= keep", () => {
    const root = mkdtempSync(join(tmpdir(), "sp2-lru-"));
    makeSnapshots(root, ["k1", "k2"]);
    evictLru(root, 5);
    expect(readdirSync(root).sort()).toEqual(["k1", "k2"]);
  });

  it("handles missing root gracefully", () => {
    expect(() => evictLru(join(tmpdir(), "sp2-lru-missing"), 5)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run — expect failure.**

```bash
bun test packages/orchestrator/tests/snapshotLru.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement `snapshot.ts`.**

```typescript
// packages/orchestrator/src/isolatedStrategy/snapshot.ts
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { WorkspaceManifest } from "./workspaceManifest";

export const SNAPSHOT_ROOT_REL = ".waygent/verify-env-snapshot";

export interface SnapshotPaths {
  root: string;             // <workspace>/.waygent/verify-env-snapshot
  dir: string;              // <root>/<cacheKey>
  nodeModules: string;      // <dir>/node_modules
  manifestFile: string;     // <dir>/manifest.json
}

export function snapshotPaths(workspace: string, cacheKey: string): SnapshotPaths {
  const root = join(workspace, SNAPSHOT_ROOT_REL);
  const dir = join(root, cacheKey);
  return {
    root,
    dir,
    nodeModules: join(dir, "node_modules"),
    manifestFile: join(dir, "manifest.json")
  };
}

export function snapshotExists(paths: SnapshotPaths): boolean {
  return existsSync(paths.nodeModules) && existsSync(paths.manifestFile);
}

export function ensureRoot(paths: SnapshotPaths): void {
  mkdirSync(paths.root, { recursive: true });
}

export function writeManifest(paths: SnapshotPaths, manifest: WorkspaceManifest): void {
  writeFileSync(paths.manifestFile, JSON.stringify(manifest, Object.keys(manifest).sort(), 2));
}

export function readManifest(paths: SnapshotPaths): WorkspaceManifest {
  return JSON.parse(readFileSync(paths.manifestFile, "utf8")) as WorkspaceManifest;
}

export function moveDirIntoSnapshot(src: string, paths: SnapshotPaths): void {
  // Use cp + remove to handle cross-device cases; safer than rename for tmpdir → workspace moves.
  mkdirSync(paths.dir, { recursive: true });
  cpSync(src, paths.nodeModules, { recursive: true, dereference: false });
  rmSync(src, { force: true, recursive: true });
}

export function removeSnapshot(paths: SnapshotPaths): void {
  rmSync(paths.dir, { force: true, recursive: true });
}

export function evictLru(rootPath: string, keep: number): void {
  if (!existsSync(rootPath)) return;
  const entries = readdirSync(rootPath)
    .map((name) => {
      const full = join(rootPath, name);
      try {
        return { name, full, mtimeMs: statSync(full).mtimeMs };
      } catch {
        return null;
      }
    })
    .filter((e): e is { name: string; full: string; mtimeMs: number } => e !== null)
    .sort((a, b) => a.mtimeMs - b.mtimeMs);

  const removeCount = Math.max(0, entries.length - keep);
  for (let i = 0; i < removeCount; i++) {
    rmSync(entries[i].full, { force: true, recursive: true });
  }
}
```

- [ ] **Step 4: Run — expect PASS.**

```bash
bun test packages/orchestrator/tests/snapshotLru.test.ts
```

Expected: 3 tests pass.

- [ ] **Step 5: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 6: Commit.**

```bash
git add packages/orchestrator/src/isolatedStrategy/snapshot.ts \
        packages/orchestrator/tests/snapshotLru.test.ts
git commit -m "feat(orchestrator): snapshot storage + LRU eviction (SP-2 T3c)"
```

---

## Task 3d: `isolatedStrategy` core + integration tests

**Files:**
- Create: `packages/orchestrator/src/isolatedStrategy/index.ts`
- Create: `packages/orchestrator/tests/isolatedStrategy.integ.test.ts`

- [ ] **Step 1: Write the integration test (gated by `WAYGENT_RUN_INTEG_TESTS=1`).**

```typescript
// packages/orchestrator/tests/isolatedStrategy.integ.test.ts
import { describe, expect, it } from "bun:test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readlinkSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { prepareIsolatedStrategy } from "../src/isolatedStrategy";

const RUN = process.env.WAYGENT_RUN_INTEG_TESTS === "1";
const dscribe = RUN ? describe : describe.skip;

function makeWorkspace(): { workspace: string; cleanup: () => void } {
  const workspace = mkdtempSync(join(tmpdir(), "sp2-integ-"));
  writeFileSync(join(workspace, "bun.lock"), "");
  writeFileSync(
    join(workspace, "package.json"),
    JSON.stringify({
      name: "sp2-integ-root",
      private: true,
      workspaces: ["packages/*"]
    })
  );
  mkdirSync(join(workspace, "packages/foo"), { recursive: true });
  writeFileSync(
    join(workspace, "packages/foo/package.json"),
    JSON.stringify({ name: "@waygent-test/foo", version: "0.0.1", main: "index.js" })
  );
  writeFileSync(join(workspace, "packages/foo/index.js"), "module.exports = { value: 'main' };");
  return {
    workspace,
    cleanup: () => rmSync(workspace, { force: true, recursive: true })
  };
}

function copyAsWorktree(workspace: string): string {
  const worktree = mkdtempSync(join(tmpdir(), "sp2-wt-"));
  cpSync(workspace, worktree, { recursive: true, dereference: false });
  return worktree;
}

dscribe("isolatedStrategy (integration)", () => {
  it("scenario A: cold cache prepares snapshot and resolves to worktree-local packages/*", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const worktree = copyAsWorktree(workspace);
      // Worker modifies the package in worktree
      writeFileSync(join(worktree, "packages/foo/index.js"), "module.exports = { value: 'worker' };");

      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      expect(prepared.evidence.isolation_status).toBe("prepared");
      expect(prepared.evidence.cache.hit).toBe(false);
      expect(prepared.evidence.isolated_packages).toContain("@waygent-test/foo");

      // Resolve @waygent-test/foo inside the worktree's node_modules — must point at worktree, not workspace
      const linkPath = join(worktree, "node_modules/@waygent-test/foo");
      expect(existsSync(linkPath)).toBe(true);
      const target = readlinkSync(linkPath);
      const resolved = require("node:path").resolve(join(linkPath, ".."), target);
      expect(resolved.startsWith(worktree)).toBe(true);

      // Reading the file through the link surfaces the worker's value
      const indexContent = readFileSync(join(linkPath, "index.js"), "utf8");
      expect(indexContent).toContain("worker");

      prepared.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario B: warm cache hit skips bun install", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const wt1 = copyAsWorktree(workspace);
      const first = prepareIsolatedStrategy({ workspace, worktree: wt1 });
      expect(first.evidence.cache.hit).toBe(false);
      first.cleanup();

      const wt2 = copyAsWorktree(workspace);
      const second = prepareIsolatedStrategy({ workspace, worktree: wt2 });
      expect(second.evidence.cache.hit).toBe(true);
      expect(second.evidence.isolation_status).toBe("prepared");
      second.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario C: manifest drift triggers strict block", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const wt1 = copyAsWorktree(workspace);
      prepareIsolatedStrategy({ workspace, worktree: wt1 }).cleanup();

      // Add a new package to the workspace
      mkdirSync(join(workspace, "packages/bar"), { recursive: true });
      writeFileSync(
        join(workspace, "packages/bar/package.json"),
        JSON.stringify({ name: "@waygent-test/bar", version: "0.0.1" })
      );

      const wt2 = copyAsWorktree(workspace);
      const drifted = prepareIsolatedStrategy({ workspace, worktree: wt2 });
      // cache_key changes when packages/bar's package.json exists → miss path, NOT manifest drift.
      // To force manifest drift, mutate the workspace AFTER snapshot creation but BEFORE worktree copy.
      // Reproduce by deleting the new package from worktree only:
      rmSync(join(wt2, "packages/bar"), { force: true, recursive: true });
      const drifted2 = prepareIsolatedStrategy({ workspace: wt2, worktree: wt2 });
      // Cache from `workspace` does not match `wt2`'s package set → drift surfaces.
      expect(drifted2.evidence.isolation_status).toBe("unavailable");
      expect(drifted2.evidence.reason).toContain("manifest_drift");
      drifted.cleanup();
      drifted2.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario D: bun install failure surfaces as strict block", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      // Corrupt the root package.json to make bun install fail
      writeFileSync(join(workspace, "package.json"), "{not valid json");
      const worktree = copyAsWorktree(workspace);
      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      expect(prepared.evidence.isolation_status).toBe("unavailable");
      expect(prepared.evidence.reason).toContain("isolation_unavailable.");
      prepared.cleanup();
    } finally {
      cleanup();
    }
  });

  it("scenario E: cleanup removes worktree links but preserves snapshot", () => {
    const { workspace, cleanup } = makeWorkspace();
    try {
      const worktree = copyAsWorktree(workspace);
      const prepared = prepareIsolatedStrategy({ workspace, worktree });
      const snapshotDir = prepared.evidence.cache.snapshot_path!;
      expect(existsSync(snapshotDir)).toBe(true);
      prepared.cleanup();
      // node_modules link gone from worktree, snapshot stays.
      expect(existsSync(join(worktree, "node_modules"))).toBe(false);
      expect(existsSync(snapshotDir)).toBe(true);
    } finally {
      cleanup();
    }
  });
});
```

- [ ] **Step 2: Run — expect failure (module missing).**

```bash
WAYGENT_RUN_INTEG_TESTS=1 bun test packages/orchestrator/tests/isolatedStrategy.integ.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement `isolatedStrategy/index.ts`.**

```typescript
// packages/orchestrator/src/isolatedStrategy/index.ts
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { computeCacheKey } from "./cacheKey";
import { detectManifestDrift, enumerateWaygentPackages, type WorkspaceManifest } from "./workspaceManifest";
import {
  ensureRoot,
  evictLru,
  moveDirIntoSnapshot,
  readManifest,
  removeSnapshot,
  snapshotExists,
  snapshotPaths,
  writeManifest,
  SNAPSHOT_ROOT_REL
} from "./snapshot";

const DEFAULT_KEEP = Number(process.env.WAYGENT_VERIFY_SNAPSHOT_KEEP ?? "5");

export interface IsolatedStrategyEvidence {
  status: "prepared" | "failed";
  strategy: "isolated_workspace_resolve";
  isolation_status: "prepared" | "unavailable";
  isolated_packages: string[];
  resolved_paths: Record<string, string>;
  cache: { hit: boolean; key: string; snapshot_path: string | null };
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedIsolatedStrategy {
  evidence: IsolatedStrategyEvidence;
  cleanup(): void;
}

export function prepareIsolatedStrategy(input: {
  workspace: string;
  worktree: string;
}): PreparedIsolatedStrategy {
  const evidence: IsolatedStrategyEvidence = {
    status: "failed",
    strategy: "isolated_workspace_resolve",
    isolation_status: "unavailable",
    isolated_packages: [],
    resolved_paths: {},
    cache: { hit: false, key: "", snapshot_path: null },
    created_paths: [],
    cleanup_status: "not_needed",
    reason: null
  };

  let cacheKey: string;
  try {
    cacheKey = computeCacheKey(input.workspace);
  } catch (error) {
    evidence.reason = `isolation_unavailable.cache_key_io: ${describe(error)}`;
    return { evidence, cleanup: () => {} };
  }
  evidence.cache.key = cacheKey;
  const paths = snapshotPaths(input.workspace, cacheKey);

  if (snapshotExists(paths)) {
    evidence.cache.hit = true;
  } else {
    evidence.cache.hit = false;
    try {
      buildSnapshot(input.workspace, paths);
    } catch (error) {
      removeSnapshot(paths);
      evidence.reason = `${normalizeFailureCode(error)}: ${describe(error)}`;
      return { evidence, cleanup: () => {} };
    }
  }
  evidence.cache.snapshot_path = paths.dir;

  let snapshotManifest: WorkspaceManifest;
  try {
    snapshotManifest = readManifest(paths);
  } catch (error) {
    evidence.reason = `isolation_unavailable.snapshot_io: ${describe(error)}`;
    return { evidence, cleanup: () => {} };
  }

  const currentManifest = enumerateWaygentPackages(input.worktree);
  const drift = detectManifestDrift(snapshotManifest, currentManifest);
  if (drift) {
    removeSnapshot(paths);
    evidence.reason = `isolation_unavailable.manifest_drift: ${drift.reason}`;
    return { evidence, cleanup: () => {} };
  }

  let resolvedPaths: Record<string, string>;
  try {
    resolvedPaths = materialize(input.worktree, paths, currentManifest);
    evidence.created_paths = ["node_modules"];
    evidence.cleanup_status = "pending";
  } catch (error) {
    cleanupWorktreeLinks(input.worktree);
    evidence.reason = `isolation_unavailable.materialize: ${describe(error)}`;
    return { evidence, cleanup: () => {} };
  }

  evidence.status = "prepared";
  evidence.isolation_status = "prepared";
  evidence.isolated_packages = Object.keys(currentManifest).sort();
  evidence.resolved_paths = resolvedPaths;

  if (!evidence.cache.hit) {
    try {
      evictLru(paths.root, DEFAULT_KEEP);
    } catch {
      // Eviction failures are non-fatal — log via evidence reason without changing status.
      evidence.reason = `eviction_warning: failed_after_finalize`;
    }
  }

  return {
    evidence,
    cleanup() {
      if (evidence.cleanup_status !== "pending") return;
      try {
        cleanupWorktreeLinks(input.worktree);
        evidence.cleanup_status = "removed";
      } catch (error) {
        evidence.cleanup_status = "failed";
        evidence.reason = describe(error);
      }
    }
  };
}

function buildSnapshot(workspace: string, paths: ReturnType<typeof snapshotPaths>): void {
  ensureRoot(paths);
  // Stage workspace into a tmpdir for a clean `bun install`.
  const staging = mkdtempSync(join(tmpdir(), "sp2-staging-"));
  try {
    cpSync(workspace, staging, { recursive: true, dereference: false });
    // Remove any existing node_modules in the staging copy to force a fresh install.
    rmSync(join(staging, "node_modules"), { force: true, recursive: true });
    rmSync(join(staging, SNAPSHOT_ROOT_REL), { force: true, recursive: true });

    const result = spawnSync("bun", ["install", "--frozen-lockfile"], {
      cwd: staging,
      encoding: "utf8",
      env: { ...process.env, BUN_INSTALL_VERBOSE: "0" }
    });
    if (result.status !== 0) {
      const tail = (result.stderr || "").slice(-2000);
      const err = new Error(`bun install failed: exit ${result.status}\n${tail}`);
      (err as Error & { code?: string }).code = "isolation_unavailable.bun_install";
      throw err;
    }

    moveDirIntoSnapshot(join(staging, "node_modules"), paths);
    writeManifest(paths, enumerateWaygentPackages(staging));
  } finally {
    rmSync(staging, { force: true, recursive: true });
  }
}

function materialize(
  worktree: string,
  paths: ReturnType<typeof snapshotPaths>,
  currentManifest: WorkspaceManifest
): Record<string, string> {
  const target = join(worktree, "node_modules");
  if (existsSync(target)) {
    throw new Error("worktree_node_modules_exists");
  }
  // Hardlink the snapshot's node_modules into the worktree.
  cpSync(paths.nodeModules, target, { recursive: true, dereference: false });

  // Rewrite @waygent/* entries to worktree-local packages/*.
  const resolved: Record<string, string> = {};
  for (const [pkgName, relPath] of Object.entries(currentManifest)) {
    const linkPath = join(target, pkgName);
    rmSync(linkPath, { force: true, recursive: true });
    mkdirSync(join(linkPath, ".."), { recursive: true });
    const linkTarget = relative(join(linkPath, ".."), join(worktree, relPath));
    symlinkSync(linkTarget, linkPath, "dir");
    resolved[pkgName] = join(worktree, relPath);
  }
  return resolved;
}

function cleanupWorktreeLinks(worktree: string): void {
  const target = join(worktree, "node_modules");
  if (existsSync(target)) {
    rmSync(target, { force: true, recursive: true });
  }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function normalizeFailureCode(error: unknown): string {
  if (error instanceof Error) {
    const code = (error as Error & { code?: string }).code;
    if (typeof code === "string" && code.startsWith("isolation_unavailable.")) return code;
  }
  return "isolation_unavailable.snapshot_io";
}
```

- [ ] **Step 4: Run integration tests — expect PASS.**

```bash
WAYGENT_RUN_INTEG_TESTS=1 bun test packages/orchestrator/tests/isolatedStrategy.integ.test.ts
```

Expected: 5 scenarios pass. If scenario A's symlink assertion fails because hardlink resolution doesn't expose the worker's edit, decide hardlink-vs-symlink for materialize per the spec's open question and amend `materialize()` (the integration test is the empirical ground truth). Record the decision in `docs/superpowers/specs/2026-05-24-waygent-sp2-verify-env-design.md` Section 11 before committing.

- [ ] **Step 5: Run unit suite — expect no regressions.**

```bash
bun test packages/orchestrator
```

Expected: all tests pass.

- [ ] **Step 6: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 7: Commit.**

```bash
git add packages/orchestrator/src/isolatedStrategy/index.ts \
        packages/orchestrator/tests/isolatedStrategy.integ.test.ts
git commit -m "feat(orchestrator): isolatedStrategy core + integration scenarios (SP-2 T3d)"
```

---

## Task 4: Dispatcher activates `auto`, evidence/events extended, plan field parser

**Files:**
- Modify: `packages/orchestrator/src/verificationEnvironment.ts`
- Modify: `packages/orchestrator/src/taskExecutor.ts`
- Modify: `packages/design-contract/src/types.ts`
- Modify: `packages/design-contract/src/parse/` (whichever file parses task fields — discover via grep)

- [ ] **Step 1: Add `verify_isolation` to `PlanTask` type and parser. Write failing test first.**

The `PlanTask` interface lives in `packages/design-contract/src/types.ts`.
The task parser lives under `packages/design-contract/src/parse/` — discover
the YAML-block reader via `grep -n "title\|owner_boundary" packages/design-contract/src/parse/`. Pick the parse file that reads task YAML blocks. Then write a new test:

```typescript
// packages/design-contract/tests/verifyIsolationField.test.ts
import { describe, expect, it } from "bun:test";
import { parsePlanMarkdown } from "../src/parse"; // adjust to actual entry point if different

const FIXTURE = `
# Plan

## Task 1

\`\`\`yaml
id: T1
title: test
verify_isolation: isolated
\`\`\`

## Task 2

\`\`\`yaml
id: T2
title: test
\`\`\`
`;

describe("verify_isolation field", () => {
  it("parses explicit isolated value", () => {
    const plan = parsePlanMarkdown(FIXTURE);
    const t1 = plan.tasks.find((t) => t.id === "T1");
    expect(t1?.verify_isolation).toBe("isolated");
  });

  it("omits the field on tasks that do not set it", () => {
    const plan = parsePlanMarkdown(FIXTURE);
    const t2 = plan.tasks.find((t) => t.id === "T2");
    expect(t2?.verify_isolation).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the test — expect failure.**

```bash
bun test packages/design-contract/tests/verifyIsolationField.test.ts
```

Expected: FAIL (field not parsed).

- [ ] **Step 3: Add field to type definition in `packages/design-contract/src/types.ts`.**

Locate `PlanTask` interface and add the optional field:

```typescript
verify_isolation?: "isolated" | "fast" | "auto";
```

- [ ] **Step 4: Extend the parser to read `verify_isolation` from each task YAML block.**

In the parser file identified above, after the existing fields are parsed, add:

```typescript
if (typeof raw.verify_isolation === "string") {
  const value = raw.verify_isolation.trim();
  if (value === "isolated" || value === "fast" || value === "auto") {
    task.verify_isolation = value;
  }
}
```

- [ ] **Step 5: Run the test — expect PASS.**

```bash
bun test packages/design-contract/tests/verifyIsolationField.test.ts
```

Expected: 2 tests pass.

- [ ] **Step 6: Rewrite `packages/orchestrator/src/verificationEnvironment.ts` to dispatch via the decider.**

```typescript
// packages/orchestrator/src/verificationEnvironment.ts
import { spawnSync } from "node:child_process";
import { prepareInheritStrategy, type InheritStrategyEvidence } from "./inheritStrategy";
import {
  prepareIsolatedStrategy,
  type IsolatedStrategyEvidence
} from "./isolatedStrategy";
import { decideVerificationStrategy, type VerifyIsolationRequest } from "./strategyDecider";

export type VerificationStrategy = "none" | "inherit_node_modules" | "isolated_workspace_resolve";

export type IsolationStatus = "not_required" | "prepared" | "unavailable";

export interface VerificationEnvironmentEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: VerificationStrategy;
  decision: {
    requested: VerifyIsolationRequest | "auto";
    resolved: "isolated" | "fast";
    reason: string;
  };
  isolation_status: IsolationStatus;
  isolated_packages: string[];
  resolved_paths: Record<string, string>;
  cache: { hit: boolean; key: string; snapshot_path: string | null } | null;
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedVerificationEnvironment {
  evidence: VerificationEnvironmentEvidence;
  cleanup(): void;
}

export interface PrepareInput {
  workspace: string;
  worktree: string;
  disabled?: boolean;
  verifyIsolation?: VerifyIsolationRequest;
}

export function prepareVerificationEnvironment(input: PrepareInput): PreparedVerificationEnvironment {
  if (input.disabled) {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: "disabled"
    });
  }

  if (process.env.WAYGENT_DISABLE_ISOLATED_VERIFY_ENV === "1") {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: "killed_by_env_var"
    });
  }

  const worktreeDiff = collectDiff(input.worktree);
  const decision = decideVerificationStrategy({
    requested: input.verifyIsolation,
    worktreeDiff
  });

  if (decision.resolved === "fast") {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: decision.reason
    });
  }

  const prepared = prepareIsolatedStrategy({ workspace: input.workspace, worktree: input.worktree });
  return wrapIsolated(prepared, {
    requested: input.verifyIsolation ?? "auto",
    resolved: "isolated",
    reason: decision.reason
  });
}

function collectDiff(worktree: string): string[] {
  const result = spawnSync("git", ["status", "--porcelain"], { cwd: worktree, encoding: "utf8" });
  if (result.status !== 0) return [];
  return result.stdout.split("\n").filter((line) => line.length > 0);
}

function wrapInherit(
  prepared: { evidence: InheritStrategyEvidence; cleanup(): void },
  decision: VerificationEnvironmentEvidence["decision"]
): PreparedVerificationEnvironment {
  const evidence: VerificationEnvironmentEvidence = {
    status: prepared.evidence.status,
    strategy: prepared.evidence.strategy === "inherit_node_modules" ? "inherit_node_modules" : "none",
    decision,
    isolation_status: "not_required",
    isolated_packages: [],
    resolved_paths: {},
    cache: null,
    created_paths: prepared.evidence.created_paths,
    cleanup_status: prepared.evidence.cleanup_status,
    reason: prepared.evidence.reason
  };
  return {
    evidence,
    cleanup() {
      prepared.cleanup();
      evidence.cleanup_status = prepared.evidence.cleanup_status;
      evidence.reason = prepared.evidence.reason;
    }
  };
}

function wrapIsolated(
  prepared: { evidence: IsolatedStrategyEvidence; cleanup(): void },
  decision: VerificationEnvironmentEvidence["decision"]
): PreparedVerificationEnvironment {
  const evidence: VerificationEnvironmentEvidence = {
    status: prepared.evidence.status === "prepared" ? "prepared" : "failed",
    strategy: "isolated_workspace_resolve",
    decision,
    isolation_status: prepared.evidence.isolation_status,
    isolated_packages: prepared.evidence.isolated_packages,
    resolved_paths: prepared.evidence.resolved_paths,
    cache: prepared.evidence.cache,
    created_paths: prepared.evidence.created_paths,
    cleanup_status: prepared.evidence.cleanup_status,
    reason: prepared.evidence.reason
  };
  return {
    evidence,
    cleanup() {
      prepared.cleanup();
      evidence.cleanup_status = prepared.evidence.cleanup_status;
      evidence.reason = prepared.evidence.reason;
    }
  };
}
```

- [ ] **Step 7: Thread `verify_isolation` from the task definition into `prepareVerificationEnvironment` call in `taskExecutor.ts`.**

In `packages/orchestrator/src/taskExecutor.ts` find the line `const verificationEnvironment = prepareVerificationEnvironment({` (around line 263 per spec context). Add the new argument:

```typescript
const verificationEnvironment = prepareVerificationEnvironment({
  workspace: input.workspace,
  worktree: taskWorktree.path,
  disabled: process.env.WAYGENT_DISABLE_VERIFICATION_ENV === "1",
  verifyIsolation: input.task.verify_isolation
});
```

- [ ] **Step 8: Emit a `runway.verification_environment` event when isolated strategy fails.**

In `taskExecutor.ts`, after the verify phase completes, add an event when `verificationEnvironmentEvidence.isolation_status === "unavailable"`. Locate the existing `events.push({ ... runway.verification_result ... })` block (around line 337) and add immediately before it:

```typescript
if (verificationEnvironmentEvidence.isolation_status === "unavailable") {
  events.push({
    run_id: input.run_id,
    event_type: "runway.verification_environment",
    phase: "verify",
    outcome: "failed",
    summary: `Isolated workspace resolve unavailable: ${verificationEnvironmentEvidence.reason ?? "unknown"}`,
    payload: {
      task_id: input.task.id,
      strategy: verificationEnvironmentEvidence.strategy,
      isolation_status: verificationEnvironmentEvidence.isolation_status,
      decision: verificationEnvironmentEvidence.decision,
      cache: verificationEnvironmentEvidence.cache,
      reason: verificationEnvironmentEvidence.reason
    }
  });
}
```

- [ ] **Step 9: Ensure isolated failure routes through `environmentBlockedVerification`.**

In `taskExecutor.ts`, find the existing `if (verificationEnvironment.evidence.status === "failed")` branch (around line 270). It already calls `environmentBlockedVerification`. Confirm the condition also fires when `isolation_status === "unavailable"` — extend the condition:

```typescript
if (
  verificationEnvironment.evidence.status === "failed" ||
  verificationEnvironment.evidence.isolation_status === "unavailable"
) {
  return environmentBlockedVerification(input.task.id, verificationEnvironment.evidence.reason);
}
```

- [ ] **Step 10: Run full orchestrator tests.**

```bash
bun test packages/orchestrator
```

Expected: all tests pass.

- [ ] **Step 11: Run integration tests.**

```bash
WAYGENT_RUN_INTEG_TESTS=1 bun test packages/orchestrator/tests/isolatedStrategy.integ.test.ts
```

Expected: 5 scenarios pass.

- [ ] **Step 12: Run `bun run check`.**

```bash
bun run check
```

Expected: type check clean.

- [ ] **Step 13: Run platform and scenario suites.**

```bash
bun run platform:demo
bun run waygent:scenarios
```

Expected: pass. No new isolated-strategy invocations from these demos (they should land in the fast path).

- [ ] **Step 14: Commit.**

```bash
git add packages/orchestrator/src/verificationEnvironment.ts \
        packages/orchestrator/src/taskExecutor.ts \
        packages/design-contract/src/types.ts \
        packages/design-contract/src/parse \
        packages/design-contract/tests/verifyIsolationField.test.ts
git commit -m "feat(orchestrator,design-contract): activate auto-isolation + verify_isolation field (SP-2 T4)"
```

---

## Task 5: SP-2 Reproduction Test (Acceptance Gate)

**Files:**
- Create: `tests/sp2-reproduction/cross-package-edit.test.ts`

This is the load-bearing test from the spec — it must fail before T4 lands and pass after.

- [ ] **Step 1: Write the reproduction test.**

```typescript
// tests/sp2-reproduction/cross-package-edit.test.ts
import { describe, expect, it } from "bun:test";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { prepareVerificationEnvironment } from "../../packages/orchestrator/src/verificationEnvironment";
import { spawnSync } from "node:child_process";

const RUN = process.env.WAYGENT_RUN_INTEG_TESTS === "1";
const dscribe = RUN ? describe : describe.skip;

function buildSyntheticMain(): { workspace: string; cleanup: () => void } {
  const ws = mkdtempSync(join(tmpdir(), "sp2-repro-main-"));
  writeFileSync(join(ws, "bun.lock"), "");
  writeFileSync(
    join(ws, "package.json"),
    JSON.stringify({ name: "sp2-repro", private: true, workspaces: ["packages/*"] })
  );

  mkdirSync(join(ws, "packages/a"), { recursive: true });
  writeFileSync(
    join(ws, "packages/a/package.json"),
    JSON.stringify({ name: "@waygent-test/a", version: "0.0.1", main: "index.js" })
  );
  writeFileSync(join(ws, "packages/a/index.js"), "module.exports = { value: 'main' };");

  mkdirSync(join(ws, "packages/b"), { recursive: true });
  writeFileSync(
    join(ws, "packages/b/package.json"),
    JSON.stringify({
      name: "@waygent-test/b",
      version: "0.0.1",
      main: "index.js",
      dependencies: { "@waygent-test/a": "*" }
    })
  );
  writeFileSync(
    join(ws, "packages/b/index.js"),
    "const a = require('@waygent-test/a'); console.log(a.value);"
  );

  // Initialise as a git repo so `git status --porcelain` works inside the worktree
  spawnSync("git", ["init", "-q"], { cwd: ws });
  spawnSync("git", ["add", "."], { cwd: ws });
  spawnSync("git", ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "main"], { cwd: ws });

  return { workspace: ws, cleanup: () => rmSync(ws, { force: true, recursive: true }) };
}

dscribe("SP-2 reproduction: worker cross-package edit", () => {
  it("verify command sees the worker's value, not main's", () => {
    const { workspace, cleanup } = buildSyntheticMain();
    try {
      // Worker worktree branched from main
      const worktree = mkdtempSync(join(tmpdir(), "sp2-repro-wt-"));
      cpSync(workspace, worktree, { recursive: true, dereference: false });

      // Worker modifies packages/a (cross-package change relative to packages/b which it also touches)
      writeFileSync(join(worktree, "packages/a/index.js"), "module.exports = { value: 'worker' };");
      writeFileSync(
        join(worktree, "packages/b/index.js"),
        "const a = require('@waygent-test/a'); console.log('B says:', a.value);"
      );

      const prepared = prepareVerificationEnvironment({ workspace, worktree });
      try {
        expect(prepared.evidence.decision.resolved).toBe("isolated");
        expect(prepared.evidence.isolation_status).toBe("prepared");

        const run = spawnSync("node", ["packages/b/index.js"], { cwd: worktree, encoding: "utf8" });
        expect(run.status).toBe(0);
        expect(run.stdout).toContain("B says: worker");
        expect(run.stdout).not.toContain("B says: main");
      } finally {
        prepared.cleanup();
      }
    } finally {
      cleanup();
    }
  });
});
```

- [ ] **Step 2: Run — expect PASS (T4 is already landed).**

```bash
WAYGENT_RUN_INTEG_TESTS=1 bun test tests/sp2-reproduction/cross-package-edit.test.ts
```

Expected: PASS. If it fails, the regression is real — do not commit until resolved.

- [ ] **Step 3: Verify the test would have failed pre-SP-2 (sanity check, no commit).**

Temporarily set `WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1` and re-run:

```bash
WAYGENT_RUN_INTEG_TESTS=1 WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1 \
  bun test tests/sp2-reproduction/cross-package-edit.test.ts
```

Expected: FAIL — stdout shows `B says: main`. This confirms the test discriminates SP-2 vs pre-SP-2 behavior. Unset the env var and re-run Step 2 to confirm PASS again.

- [ ] **Step 4: Commit.**

```bash
git add tests/sp2-reproduction/cross-package-edit.test.ts
git commit -m "test(sp2): cross-package edit reproduction acceptance gate (SP-2 T5)"
```

---

## Task 6: Docs

**Files:**
- Create: `docs/operations/verification.md`
- Modify: `AGENTS.md`
- Modify: `skills/waygent/SKILL.md`

- [ ] **Step 1: Confirm `.waygent/` is already gitignored.**

```bash
grep -n "^\.waygent" .gitignore
```

Expected: at least one matching line. If missing, append `.waygent/` to `.gitignore` and stage that change as part of this task.

- [ ] **Step 2: Create `docs/operations/verification.md`.**

```markdown
# Verification Environment

Waygent prepares an isolated dependency environment per task before running
verification commands. Two strategies exist:

## Strategies

- **inherit_node_modules** (fast path) — symlinks the workspace's
  `node_modules` into the worktree. Used when the worker's diff stays inside
  a single `packages/*` or when verify only runs unit tests. Wall-clock cost
  is negligible.
- **isolated_workspace_resolve** (isolated) — runs `bun install` against a
  content-addressed snapshot, materializes it into the worktree, and rewrites
  `@waygent/*` entries to worktree-local paths. Used when the worker edits
  two or more `packages/*`, touches `bun.lock`/root `package.json`, or the
  plan task carries `verify_isolation: "isolated"`.

## Plan task field

```yaml
verify_isolation: "isolated" | "fast" | "auto"   # default: "auto"
```

- `"isolated"` — always isolate, even if the diff is small.
- `"fast"` — always use inherit_node_modules, even if the diff is
  cross-package. Author intent overrides automatic detection.
- `"auto"` — let the strategy decider pick based on the worker's worktree
  diff.

## Failure surface

When isolation cannot be prepared, the verify phase fails with
`failure_class="verification_environment_unavailable"` and emits a
`runway.verification_environment` event with `isolation_status="unavailable"`.
The `reason` field is namespaced:

| reason code                            | meaning                                  |
|----------------------------------------|------------------------------------------|
| `isolation_unavailable.bun_install`    | `bun install` exited non-zero            |
| `isolation_unavailable.snapshot_io`    | filesystem error reading/writing snapshot |
| `isolation_unavailable.materialize`    | failed to materialize node_modules in worktree |
| `isolation_unavailable.manifest_drift` | workspace package set differs from snapshot |
| `isolation_unavailable.cache_key_io`   | failed to compute cache key              |

There is no automatic retry and no automatic fallback to the fast path. The
operator must intervene.

## Cache

- Location: `<workspace>/.waygent/verify-env-snapshot/<cache_key>/`
- Key: `sha256(bun.lock + packages/*/package.json + root workspaces/dependencies)`
- LRU: keep newest 5 snapshots by default (`WAYGENT_VERIFY_SNAPSHOT_KEEP=N`).

## Kill switches

- `WAYGENT_DISABLE_VERIFICATION_ENV=1` — disable verify env preparation
  entirely.
- `WAYGENT_DISABLE_ISOLATED_VERIFY_ENV=1` — force every task to fast path
  regardless of `verify_isolation` value. Evidence records
  `decision.reason="killed_by_env_var"`. Operator-controlled fall-through is
  not a policy violation.
```

- [ ] **Step 3: Update `AGENTS.md` verification commands section.**

Find the existing "Verification Commands" or equivalent section and add a single line at the end:

```markdown
- Tasks that edit two or more `packages/*` or touch `bun.lock` automatically
  run verify under `isolated_workspace_resolve`. See
  `docs/operations/verification.md`.
```

- [ ] **Step 4: Update `skills/waygent/SKILL.md`.**

Find the plan-authoring guidance section and add:

```markdown
### verify_isolation (optional)

Each task may declare `verify_isolation: "isolated" | "fast" | "auto"`. The
default is `"auto"`. Use `"isolated"` when the verify command must observe
the worker's cross-package changes (most integration tests). Use `"fast"`
to opt out of automatic escalation when you are certain the diff is
self-contained. See `docs/operations/verification.md` for details.
```

- [ ] **Step 5: Run `git diff --check`.**

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 6: Run `bun run check` and the legacy doc check if available.**

```bash
bun run check
```

Expected: pass.

- [ ] **Step 7: Commit.**

```bash
git add docs/operations/verification.md AGENTS.md skills/waygent/SKILL.md .gitignore
git commit -m "docs(verification): document SP-2 isolation, verify_isolation, kill switches (SP-2 T6)"
```

---

## Verification (full plan acceptance)

After all tasks land, run:

```bash
bun run check
bun test packages/orchestrator
bun test packages/design-contract
WAYGENT_RUN_INTEG_TESTS=1 bun test packages/orchestrator/tests/isolatedStrategy.integ.test.ts
WAYGENT_RUN_INTEG_TESTS=1 bun test tests/sp2-reproduction/cross-package-edit.test.ts
bun run platform:demo
bun run waygent:scenarios
git diff --check
```

All commands must pass. The reproduction test under
`tests/sp2-reproduction/` is the acceptance gate for failure mode A from
the parent roadmap.

## Review

Use `code_review.md` before reporting completion.
