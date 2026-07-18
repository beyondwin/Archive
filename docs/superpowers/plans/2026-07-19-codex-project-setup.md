# Archive Codex Project Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build repository-owned Codex guidance and verification that routes Archive work correctly, detects instruction drift, selects meaningful checks from changed paths, and enforces destructive-command boundaries.

**Architecture:** Keep the root `AGENTS.md` as a concise canonical router refined by nearest-subtree files. Add dependency-free Bun/TypeScript contract and verification tools under `scripts/agent/`, expose one local entry point through `package.json`, test Codex execpolicy decisions, and make GitHub Actions invoke the same commands.

**Tech Stack:** Markdown, Bun 1.3.10, TypeScript 5.9, Bun test, Git, Codex execpolicy, GitHub Actions, Rust stable/rustfmt

## Global Constraints

- Before editing or finalizing, inspect full Git status, branch, HEAD, and all worktrees; preserve dirty state.
- Waygent and the TypeScript Lens path remain active. Do not route new work into the removed Python AgentLens tree.
- Do not change Waygent product behavior, event contracts, or either executor's scheduling and quality policy.
- Do not install connectors/plugins, delete worktrees/runtime evidence/sessions, or standardize user-global model, sandbox, approval, authentication, or MCP policy.
- Do not commit credentials, transcripts, runtime state, generated output, caches, or machine-specific absolute paths.
- Verification tooling must not install dependencies, start live providers, rewrite generated files, or mutate Waygent/executor state.
- Live-provider checks remain opt-in and are reported as not run when omitted.
- Add no production runtime dependency; use Bun, TypeScript, Git, and existing CLIs.
- Commits are local. A push, PR, merge, or deployment requires separate user authorization.

---

## File Map

- `AGENTS.md`: canonical routing, preflight, authority, and done contract.
- `apps/AGENTS.md`, `packages/AGENTS.md`, `native/kernel/AGENTS.md`, `skills/AGENTS.md`: subtree invariants.
- `skills/kws-codex-plan-executor/AGENTS.md`: strict-thin executor contract.
- `scripts/agent/contract.ts`: active-path and tracked-state contract data.
- `scripts/agent/check-contract.ts`: contract validator and CLI.
- `scripts/agent/verification-map.ts`: path-to-command manifest.
- `scripts/agent/check-markdown-links.ts`: touched-Markdown local-link checker.
- `scripts/agent/verify.ts`: changed-path collection and fail-fast executor.
- `scripts/agent/*.test.ts`: deterministic contract, classifier, runner, link, and execpolicy tests.
- `.codex/rules/archive.rules`: destructive-command decisions.
- `.github/workflows/agent-contract.yml`: CI using the same local entry points.
- `docs/operations/codex-local-setup.md`: machine-local operator setup.

### Task 1: Canonical Guidance And Subtree Routing

**Files:**
- Modify: `AGENTS.md:1-183`
- Create: `apps/AGENTS.md`
- Create: `packages/AGENTS.md`
- Create: `native/kernel/AGENTS.md`
- Create: `skills/AGENTS.md`
- Create: `skills/kws-codex-plan-executor/AGENTS.md`
- Modify: `CLAUDE.md:1-36`
- Modify: `GEMINI.md:1-24`
- Modify: `.cursor/rules/archive.mdc:1-19`
- Modify: `.github/copilot-instructions.md:1-21`
- Modify: `.gitignore:109-111`
- Modify: `PLANS.md:1-50`
- Modify: `code_review.md:1-45`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-19-codex-project-setup-design.md`.
- Produces: current guidance paths and active claims consumed by Task 2. Keep
  the existing concrete verification matrix until Task 4 creates its
  replacement command.

- [ ] **Step 1: Capture RED routing evidence**

Run:

```bash
rg -n 'Active code lives in `AgentLens/`|AgentLens/docs/spec|npm run gen-types' \
  .cursor/rules/archive.mdc .gitignore code_review.md
for path in apps/AGENTS.md packages/AGENTS.md native/kernel/AGENTS.md \
  skills/AGENTS.md skills/kws-codex-plan-executor/AGENTS.md; do
  test -f "$path"
done
```

Expected: three stale claims print and the loop exits non-zero on a missing subtree file.

- [ ] **Step 2: Rewrite the root file as a compact router**

Add these exact sections while retaining safety, editing, and Git-hygiene rules:

```markdown
## Mandatory Start Preflight

Before editing, finalizing, committing, or reporting branch state, run `pwd`,
full Git status, current branch, `git rev-parse HEAD`, and
`git worktree list --porcelain`. Treat the current directory as a checkout,
not automatically as authoritative `main`. Identify the nearest applicable
`AGENTS.md` before changing a subtree.

## Task Routing

- Waygent orchestration: `packages/orchestrator/`, `packages/runway-control/`
- Provider execution: `packages/provider-adapters/`, `native/kernel/`
- Lens storage/projection: `packages/lens-store/`, `packages/lens-projectors/`
- Product surfaces: `apps/cli/`, `apps/api/`, `apps/console/`
- Waygent workflow contract: `skills/waygent/`
- Sequential Codex plan execution: `skills/kws-codex-plan-executor/`
- Claude executor: `skills/kws-claude-multi-agent-executor/`

```

- [ ] **Step 3: Add subtree contracts**

Each file begins with its scope and includes these invariants:

```markdown
# Apps Agent Instructions
- Preserve CLI flags, API response shapes, and console read-model compatibility.
- Console changes require focused Bun tests and a production build.
- Browser checks supplement deterministic tests; they do not replace them.
```

```markdown
# Packages Agent Instructions
- Filesystem JSON/JSONL artifacts are source of truth; SQLite is rebuildable.
- Providers do not write Lens storage or SQLite directly.
- Event changes require contract, projector, and consumer coverage.
- Changes spanning two or more `packages/*` use the offline closure gate.
```

```markdown
# Native Kernel Agent Instructions
- Keep process, filesystem, Git, and sandbox enforcement in the Rust boundary.
- Treat platform-specific process control as an explicit support boundary.
- Run rustfmt check and `cargo test --workspace` from `native/kernel/`.
```

```markdown
# Skills Agent Instructions
- Read the target `SKILL.md`, README, change protocol, and nearest instructions.
- Keep skill docs, evals, and advertised commands synchronized.
- Skills do not redefine Waygent product ownership.
```

```markdown
# Codex Plan Executor Agent Instructions
- Preserve the strict-thin sequential wrapper and Python standard-library runtime.
- Approved Superpowers documents own intent and quality policy.
- Do not migrate this executor into Bun/Waygent or add task-mapping policy.
- Run `./evals/run.sh` before claiming executor changes are complete.
```

- [ ] **Step 4: Make cross-agent files thin adapters**

Keep tool-specific notes after a pointer to `AGENTS.md`. Replace the Cursor
`AgentLens/` active-path claim, correct the `.gitignore` Superpowers path
comment, and replace `npm run gen-types` with `bun run typecheck` plus targeted
contract/projector/consumer tests. Task 4 replaces that temporary matrix with
the path-aware entry point after the command exists.

- [ ] **Step 5: Verify GREEN and commit**

```bash
rg -n 'Active code lives in `AgentLens/`|AgentLens/docs/spec|npm run gen-types' \
  .cursor/rules/archive.mdc .gitignore code_review.md
for path in apps/AGENTS.md packages/AGENTS.md native/kernel/AGENTS.md \
  skills/AGENTS.md skills/kws-codex-plan-executor/AGENTS.md; do
  test -s "$path"
done
git diff --check
```

Expected: `rg` has no matches, all files are non-empty, and diff hygiene passes.

```bash
git add AGENTS.md apps/AGENTS.md packages/AGENTS.md native/kernel/AGENTS.md \
  skills/AGENTS.md skills/kws-codex-plan-executor/AGENTS.md CLAUDE.md GEMINI.md \
  .cursor/rules/archive.mdc .github/copilot-instructions.md .gitignore \
  PLANS.md code_review.md
git commit -m "docs: establish layered agent guidance"
```

### Task 2: Instruction Contract Validator

**Files:**
- Create: `scripts/agent/contract.ts`
- Create: `scripts/agent/check-contract.ts`
- Create: `scripts/agent/check-contract.test.ts`
- Modify: `package.json:8-21`

**Interfaces:**
- Consumes: guidance paths from Task 1.
- Produces: `ContractIssue`, `checkContract()`, and `formatContractIssues()` for Task 4.

- [ ] **Step 1: Write failing tests**

```ts
import { describe, expect, test } from "bun:test";
import { checkContract } from "./check-contract";

describe("checkContract", () => {
  test("accepts the repository contract", async () => {
    expect(await checkContract({ root: process.cwd() })).toEqual([]);
  });

  test("reports a missing active path", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: ["definitely-missing/"],
      requiredAgentFiles: [],
      trackedFiles: [],
    });
    expect(issues[0]?.code).toBe("missing_active_path");
  });

  test("rejects tracked local state", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: [],
      requiredAgentFiles: [],
      trackedFiles: [".waygent/runs/example.json"],
    });
    expect(issues.map((issue) => issue.code)).toContain("tracked_local_state");
  });
});
```

- [ ] **Step 2: Run RED**

Run: `bun test scripts/agent/check-contract.test.ts`

Expected: module-not-found failure.

- [ ] **Step 3: Define contract data**

```ts
export const REQUIRED_PATHS = [
  "apps/cli", "apps/api", "apps/console",
  "packages/orchestrator", "packages/runway-control",
  "packages/provider-adapters", "packages/lens-store",
  "packages/lens-projectors", "native/kernel", "skills/waygent",
  "skills/kws-codex-plan-executor", "skills/kws-claude-multi-agent-executor",
] as const;

export const REQUIRED_AGENT_FILES = [
  "AGENTS.md", "apps/AGENTS.md", "packages/AGENTS.md",
  "native/kernel/AGENTS.md", "skills/AGENTS.md",
  "skills/kws-codex-plan-executor/AGENTS.md",
  "skills/kws-claude-multi-agent-executor/AGENTS.md",
] as const;

export const CURRENT_GUIDANCE_FILES = [
  "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursor/rules/archive.mdc",
  ".github/copilot-instructions.md", ".gitignore", "code_review.md",
] as const;

export const LOCAL_STATE_PATTERN =
  /^(?:\.waygent|\.agentlens|\.claude|\.codex-orchestrator|\.orchestrator|\.superpowers|node_modules|native\/kernel\/target)(?:\/|$)/;

export type ContractIssueCode =
  | "missing_active_path" | "missing_agent_file" | "stale_active_claim"
  | "missing_package_script" | "non_executable_gate"
  | "tracked_local_state" | "invalid_verification_map"
  | "codex_execpolicy_unavailable";

export interface ContractIssue {
  code: ContractIssueCode;
  path: string;
  message: string;
}
```

- [ ] **Step 4: Implement validator and CLI**

```ts
export interface CheckContractOptions {
  root?: string;
  requiredPaths?: readonly string[];
  requiredAgentFiles?: readonly string[];
  trackedFiles?: readonly string[];
}

export async function checkContract(
  options: CheckContractOptions = {},
): Promise<ContractIssue[]>;

export function formatContractIssues(
  issues: readonly ContractIssue[],
): string;
```

Use `git ls-files -z` unless tracked files are injected. Verify required
paths/files, `package.json` scripts, executable executor `evals/run.sh` gates,
the files in `CURRENT_GUIDANCE_FILES`, and tracked local-state patterns. The
CLI prints `agent contract: PASS` or stable
`[issue-code] [path] [message]` lines and exits 1.

Add:

```json
"agent:contract": "bun run scripts/agent/check-contract.ts"
```

- [ ] **Step 5: Run GREEN and commit**

```bash
bun test scripts/agent/check-contract.test.ts
bun run agent:contract
git diff --check
git add scripts/agent/contract.ts scripts/agent/check-contract.ts \
  scripts/agent/check-contract.test.ts package.json
git commit -m "feat: validate agent instruction contract"
```

### Task 3: Path-To-Verification Manifest

**Files:**
- Create: `scripts/agent/verification-map.ts`
- Create: `scripts/agent/verification-map.test.ts`
- Modify: `scripts/agent/check-contract.ts`
- Modify: `scripts/agent/check-contract.test.ts`

**Interfaces:**
- Consumes: Task 2 contract types.
- Produces: `selectVerification(paths)` and `VerificationSelection` for Task 4.

- [ ] **Step 1: Write failing matrix tests**

```ts
import { expect, test } from "bun:test";
import { selectVerification } from "./verification-map";

const ids = (paths: string[]) => selectVerification(paths).scopeIds;

test("required scope matrix", () => {
  expect(ids(["docs/README.md"])).toEqual(["docs"]);
  expect(ids(["apps/console/src/App.tsx"])).toEqual(["console"]);
  expect(ids([
    "packages/orchestrator/src/index.ts",
    "packages/runway-control/src/scheduler.ts",
  ])).toEqual(["waygent-closure"]);
  expect(ids(["native/kernel/crates/kernel-cli/src/main.rs"])).toEqual(["native"]);
  expect(ids(["skills/kws-codex-plan-executor/scripts/cpe.py"]))
    .toEqual(["codex-executor"]);
  expect(ids(["skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py"]))
    .toEqual(["claude-executor"]);
  expect(ids(["unexpected/new-surface.txt"])).toEqual(["full-offline"]);
});
```

Run: `bun test scripts/agent/verification-map.test.ts`

Expected: module-not-found failure.

- [ ] **Step 2: Implement manifest interfaces**

```ts
export type ScopeId =
  | "docs" | "console" | "app" | "package" | "waygent-closure"
  | "native" | "waygent-skill" | "codex-executor"
  | "claude-executor" | "full-offline";

export interface CommandSpec {
  id: string;
  argv: readonly string[];
  cwd?: string;
  optIn?: boolean;
}

export interface VerificationSelection {
  scopeIds: ScopeId[];
  commands: CommandSpec[];
  markdownFiles: string[];
  unknownPaths: string[];
  reasons: string[];
}

export function selectVerification(
  paths: readonly string[],
): VerificationSelection;
```

Define command specs for contract, `git diff --check`, typecheck, `bun run check`, platform demo, scenarios, fixture lab, dogfood, console test/build, Rust format/test, Waygent skill eval, and both executor evals. Always deduplicate by `cwd + argv`.

- [ ] **Step 3: Implement escalation rules**

Rules are exact:

- docs/guidance: contract, touched Markdown links, diff hygiene;
- console: contract, diff, `bun test src`, `bun run build` in `apps/console`;
- other app or one package: contract, diff, focused tests where present, typecheck;
- two or more `packages/*` or `bun.lock`: replace narrow TypeScript scopes with offline closure;
- native: rustfmt and Cargo workspace tests;
- each skill: its own eval plus directly relevant product check;
- unknown: all deterministic offline gates and `unknownPaths`.

- [ ] **Step 4: Validate manifest integrity and commit**

Extend `checkContract()` to reject duplicate scope IDs, conflicting command IDs, empty matchers, and scopes without commands.

```bash
bun test scripts/agent/verification-map.test.ts scripts/agent/check-contract.test.ts
bun run agent:contract
git add scripts/agent/verification-map.ts scripts/agent/verification-map.test.ts \
  scripts/agent/check-contract.ts scripts/agent/check-contract.test.ts \
  scripts/agent/contract.ts
git commit -m "feat: map changed paths to verification"
```

### Task 4: Markdown Links And Verification Runner

**Files:**
- Create: `scripts/agent/check-markdown-links.ts`
- Create: `scripts/agent/check-markdown-links.test.ts`
- Create: `scripts/agent/verify.ts`
- Create: `scripts/agent/verify.test.ts`
- Modify: `package.json:8-23`
- Modify: `AGENTS.md`
- Modify: `code_review.md`

**Interfaces:**
- Consumes: Tasks 2-3.
- Produces: `collectChangedPaths()`, `runVerification()`, and `bun run agent:verify`.

- [ ] **Step 1: Write failing tests**

```ts
import { expect, test } from "bun:test";
import { checkMarkdownLinks } from "./check-markdown-links";

test("reports only missing local targets", async () => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () =>
      "[ok](../README.md) [bad](missing.md) [web](https://openai.com)",
    exists: async (path) => path === "/fixture/README.md",
  });
  expect(issues).toEqual([{ file: "docs/readme.md", target: "missing.md" }]);
});
```

```ts
import { expect, test } from "bun:test";
import { runVerification } from "./verify";

test("dry-run does not execute", async () => {
  const calls: string[] = [];
  const result = await runVerification({
    root: process.cwd(),
    paths: ["apps/console/src/App.tsx"],
    dryRun: true,
    run: async (command) => { calls.push(command.id); return 0; },
  });
  expect(calls).toEqual([]);
  expect(result.selectedScopes).toEqual(["console"]);
});

test("execution stops after first failure", async () => {
  const calls: string[] = [];
  const result = await runVerification({
    root: process.cwd(),
    paths: ["apps/console/src/App.tsx"],
    run: async (command) => {
      calls.push(command.id);
      return command.id === "console-test" ? 1 : 0;
    },
  });
  expect(calls).not.toContain("console-build");
  expect(result.exitCode).toBe(1);
});
```

Run: `bun test scripts/agent/check-markdown-links.test.ts scripts/agent/verify.test.ts`

Expected: module-not-found failures.

- [ ] **Step 2: Implement link checking**

```ts
export interface MarkdownLinkIssue { file: string; target: string }

export interface MarkdownLinkOptions {
  root: string;
  files: readonly string[];
  readText?: (path: string) => Promise<string>;
  exists?: (path: string) => Promise<boolean>;
}

export async function checkMarkdownLinks(
  options: MarkdownLinkOptions,
): Promise<MarkdownLinkIssue[]>;
```

Strip fragments/query strings, decode local targets, resolve from the document directory, accept files/directories, ignore web/mail/fragment-only targets, and return sorted issues.

- [ ] **Step 3: Implement changed-path collection and runner**

```ts
export interface ChangedPathOptions {
  root: string;
  base?: string;
  head?: string;
  git?: (args: readonly string[]) => Promise<string>;
}

export async function collectChangedPaths(
  options: ChangedPathOptions,
): Promise<string[]>;

export interface VerificationResult {
  selectedScopes: ScopeId[];
  paths: string[];
  commandResults: Array<{ id: string; exitCode: number; skipped: boolean }>;
  unknownPaths: string[];
  exitCode: number;
}

export async function runVerification(options: {
  root: string;
  paths: readonly string[];
  dryRun?: boolean;
  run?: (command: CommandSpec) => Promise<number>;
}): Promise<VerificationResult>;
```

Without a range, combine `git diff --name-only --diff-filter=ACMR HEAD` with untracked files. With a range, use `<base>...<head>`. Support repeated `--path`, reject mixing paths and ranges, execute fail-fast, and print stable paths/scopes/commands/opt-in summary.

- [ ] **Step 4: Add scripts, run GREEN, and commit**

```json
"agent:test": "bun test scripts/agent",
"agent:verify": "bun run scripts/agent/verify.ts"
```

Replace the root verification matrix with the now-executable contract:

```markdown
## Definition Of Done

Run `bun run agent:verify` plus explicitly required live evidence. Review
against `code_review.md`, then report changed files, exact command results,
skipped opt-in evidence, residual risks, and local-versus-remote state.
```

```bash
bun run agent:test
bun run agent:verify -- --dry-run --path docs/README.md
bun run agent:verify -- --dry-run --path apps/console/src/App.tsx
git add scripts/agent/check-markdown-links.ts \
  scripts/agent/check-markdown-links.test.ts scripts/agent/verify.ts \
  scripts/agent/verify.test.ts package.json AGENTS.md code_review.md
git commit -m "feat: run path-aware agent verification"
```

Expected: tests pass; dry runs select `docs` and `console` without executing.

### Task 5: Tested Destructive-Command Policy

**Files:**
- Modify: `.codex/rules/archive.rules:1-40`
- Create: `scripts/agent/execpolicy.test.ts`
- Modify: `scripts/agent/check-contract.ts`
- Modify: `scripts/agent/check-contract.test.ts`
- Modify: `scripts/agent/contract.ts`

**Interfaces:**
- Consumes: Codex `execpolicy check` JSON.
- Produces: tested forbidden, prompt, and unmatched safety decisions.

- [ ] **Step 1: Write failing policy tests**

```ts
import { expect, test } from "bun:test";

async function decision(command: string[]): Promise<string | undefined> {
  const proc = Bun.spawn([
    process.env.CODEX_BIN ?? "codex", "execpolicy", "check",
    "--rules", ".codex/rules/archive.rules", "--", ...command,
  ], { stdout: "pipe", stderr: "pipe" });
  const output = await new Response(proc.stdout).text();
  expect(await proc.exited).toBe(0);
  return JSON.parse(output).decision;
}

test("destructive policy matrix", async () => {
  expect(await decision(["git", "reset", "--hard"])).toBe("forbidden");
  expect(await decision(["git", "push", "--force", "origin", "main"]))
    .toBe("forbidden");
  expect(await decision(["git", "clean", "-fd"])).toBe("prompt");
  expect(await decision(["git", "branch", "-D", "feature"])).toBe("prompt");
  expect(await decision(["git", "worktree", "remove", "/tmp/wt"]))
    .toBe("prompt");
  expect(await decision(["git", "status", "--short"])).toBeUndefined();
  expect(await decision(["git", "worktree", "list", "--porcelain"]))
    .toBeUndefined();
});
```

Run: `bun test scripts/agent/execpolicy.test.ts`

Expected: new force-push, branch-delete, and worktree-remove cases fail.

- [ ] **Step 2: Add precise rules**

```python
prefix_rule(
    pattern = ["git", "push", "--force"],
    decision = "forbidden",
    justification = "Force push can overwrite remote history; use an explicitly approved safer workflow.",
)

prefix_rule(
    pattern = ["git", "push", "--force-with-lease"],
    decision = "prompt",
    justification = "History rewrite requires explicit authorization and a fresh remote check.",
)

prefix_rule(
    pattern = ["git", "branch", "-D"],
    decision = "prompt",
    justification = "Forced branch deletion can discard unmerged work.",
)

prefix_rule(
    pattern = ["git", "worktree", "remove"],
    decision = "prompt",
    justification = "Worktree removal must confirm the exact target and preserve active work.",
)
```

Do not add a hook: execpolicy expresses and tests every invariant in this task.

- [ ] **Step 3: Integrate availability checking and commit**

`checkContract()` emits `codex_execpolicy_unavailable` when the local `codex` binary cannot run the fixture command. This is a visible environment blocker, never a silent skip.

```bash
bun test scripts/agent/execpolicy.test.ts scripts/agent/check-contract.test.ts
bun run agent:contract
git diff --check
git add .codex/rules/archive.rules scripts/agent/execpolicy.test.ts \
  scripts/agent/check-contract.ts scripts/agent/check-contract.test.ts \
  scripts/agent/contract.ts
git commit -m "chore: harden and test Codex command policy"
```

### Task 6: Reproducible CI

**Files:**
- Create: `.bun-version`
- Create: `.github/workflows/agent-contract.yml`
- Modify: `scripts/agent/verify.ts`
- Modify: `scripts/agent/verify.test.ts`

**Interfaces:**
- Consumes: all local agent commands.
- Produces: pull-request and main-push verification with identical entry points.

- [ ] **Step 1: Test all-zero push bases**

Add this injected-Git test:

```ts
test("all-zero push base falls back to the head parent", async () => {
  const calls: string[][] = [];
  const paths = await collectChangedPaths({
    root: process.cwd(),
    base: "0000000000000000000000000000000000000000",
    head: "HEAD",
    git: async (args) => {
      calls.push([...args]);
      return args.includes("--name-only") ? "AGENTS.md\nAGENTS.md\n" : "";
    },
  });
  expect(paths).toEqual(["AGENTS.md"]);
  expect(calls.some((args) => args.includes("HEAD^...HEAD"))).toBe(true);
});
```

Add a companion test whose injected Git runner rejects both refs and assert
error code `invalid_git_range` plus the exact base and head strings.

Run: `bun test scripts/agent/verify.test.ts`

Expected: RED until range normalization is implemented.

- [ ] **Step 2: Implement range normalization**

Use the `git` injection from `ChangedPathOptions`. Convert a forty-zero base to `<head>^`; fail explicitly if neither ref resolves.

- [ ] **Step 3: Pin Bun and create workflow**

Write `1.3.10` to `.bun-version` and create:

```yaml
name: agent-contract

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version-file: .bun-version
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt
      - run: bun install --frozen-lockfile
      - run: npm install --global @openai/codex@0.144.6
      - run: bun run agent:test
      - run: bun run agent:contract
      - if: github.event_name == 'pull_request'
        run: bun run agent:verify -- --base "${{ github.event.pull_request.base.sha }}" --head "${{ github.event.pull_request.head.sha }}"
      - if: github.event_name == 'push'
        run: bun run agent:verify -- --base "${{ github.event.before }}" --head "${{ github.sha }}"
```

- [ ] **Step 4: Validate and commit**

```bash
bun run agent:test
bun run agent:contract
bun run agent:verify -- --dry-run --base HEAD~1 --head HEAD
git diff --check
git add .bun-version .github/workflows/agent-contract.yml \
  scripts/agent/verify.ts scripts/agent/verify.test.ts
git commit -m "ci: verify the agent contract and changed scope"
```

### Task 7: Operator Docs And Full Acceptance

**Files:**
- Create: `docs/operations/codex-local-setup.md`
- Modify: `docs/operations/verification.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Modify: `.codex/README.md`
- Modify: `skills/README.md`

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: discoverable setup instructions and final evidence.

- [ ] **Step 1: Write operator setup**

Include exact first-run commands:

```bash
codex doctor --summary --no-color
bun install --frozen-lockfile
bun run agent:contract
bun run agent:verify -- --dry-run --path README.md
```

Document repository trust, restart/new-task reload boundaries, local-only auth/MCP/sandbox/session concerns, local minimum execpolicy support `0.144.1`, CI pin `0.144.6`, and intentional pin updates. Do not include credentials or absolute user paths.

- [ ] **Step 2: Update verification and discovery docs**

Document:

```bash
bun run agent:contract
bun run agent:test
bun run agent:verify
bun run agent:verify -- --dry-run --path apps/console/src/App.tsx
bun run agent:verify -- --base origin/main --head HEAD
```

Explain unknown-path escalation and deterministic versus opt-in live evidence. Link the guide from root/docs/Codex READMEs and document the Codex executor subtree contract in `skills/README.md`.

- [ ] **Step 3: Prove classifier acceptance**

```bash
bun run agent:verify -- --dry-run --path docs/README.md
bun run agent:verify -- --dry-run --path apps/console/src/App.tsx
bun run agent:verify -- --dry-run \
  --path packages/orchestrator/src/index.ts \
  --path packages/runway-control/src/scheduler.ts
bun run agent:verify -- --dry-run --path native/kernel/crates/kernel-cli/src/main.rs
bun run agent:verify -- --dry-run --path skills/kws-codex-plan-executor/scripts/cpe.py
bun run agent:verify -- --dry-run --path skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py
bun run agent:verify -- --dry-run --path unexpected/new-surface.txt
```

Expected scopes: `docs`, `console`, `waygent-closure`, `native`, `codex-executor`, `claude-executor`, `full-offline`.

- [ ] **Step 4: Run full deterministic acceptance**

```bash
bun run agent:test
bun run agent:contract
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run waygent:fixture-lab
bun run waygent:dogfood
bun run --cwd apps/console build
(cd native/kernel && cargo fmt --all -- --check && cargo test --workspace)
(cd skills/waygent && ./evals/run.sh)
(cd skills/kws-codex-plan-executor && ./evals/run.sh)
(cd skills/kws-claude-multi-agent-executor && ./evals/run.sh)
git diff --check
```

Expected: every deterministic gate exits 0; live-provider checks are reported `NOT RUN (opt-in)`.

- [ ] **Step 5: Review, commit, and recheck state**

Review against `code_review.md`. Confirm no generated/runtime files, credentials, absolute user paths, unrelated worktree changes, or CI write permissions.

```bash
git add docs/operations/codex-local-setup.md docs/operations/verification.md \
  docs/README.md README.md .codex/README.md skills/README.md
git commit -m "docs: publish Codex operator and verification guide"
git status --short --branch --untracked-files=all
git log --oneline --decorate -10
git worktree list --porcelain
```

Expected: implementation checkout clean, unrelated worktrees unchanged, commits local, and no push/PR/deploy performed.
