# Living Docs and Agent Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give humans and agents one shared docs map, and shrink `AGENTS.md` / tool files to invariants, a code map, and Done.

**Architecture:** Lock the IA in `scripts/agent/guidance-ia.test.ts` first. Then rewrite root guidance, then current docs (including `agentlens.md` → `lens.md`). Do not move `apps/`, `packages/`, `native/`, or archive trees.

**Tech Stack:** Markdown, Bun test, Git.

**Spec:** `docs/superpowers/specs/2026-09-11-living-docs-and-agent-guidance-design.md`

## Global Constraints

- Current docs and root guidance only. No code-directory moves.
- Do not edit `docs/history/`, `docs/migration/`, or existing `docs/superpowers/` file bodies (this plan file is the one new plan).
- Do not add package README files.
- Do not change `waygent run --plan/--spec` default directories.
- Do not present `components/agentlens` or `AgentLens/` as active/current/primary.
- Keep the Lens prohibition as `Do not recreate \`components/agentlens\``.
- Schema name `agentlens.event.v3` stays.
- Subtree `apps/AGENTS.md`, `packages/AGENTS.md`, `native/kernel/AGENTS.md` stay as they are.
- `PLANS.md` and `code_review.md` stay; edit only if a link this work introduces would break.
- Live provider checks stay opt-in and are not run.
- Do not require `bun run check`, `waygent:scenarios`, console build, or `cargo test`.
- Commits are local. Push, PR, merge, or deploy needs separate user authorization.
- Before editing or committing: `pwd`, `git status --short --branch --untracked-files=all`, `git branch --show-current`, `git rev-parse HEAD`, `git worktree list --porcelain`.

---

## File Map

- `scripts/agent/guidance-ia.test.ts` — IA lock tests (created, then appended).
- `AGENTS.md` — three sections only: Invariants, Map, Done.
- `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/archive.mdc`, `.github/copilot-instructions.md`, `.codex/README.md` — tool pointer plus tool-only notes.
- `README.md` — intro, short first commands, links.
- `docs/README.md` — shared “what to read” map.
- `docs/architecture/agentlens.md` → `docs/architecture/lens.md` — current Lens page.
- `docs/architecture/waygent.md` — Lens link only.
- `docs/architecture/runtime.md` — drop Default gates command list.
- `docs/operations/waygent.md` — relabel `--plan`/`--spec` dirs.
- `docs/roadmap/README.md` — one sentence relabel.
- `docs/getting-started.md` — edit only if it still duplicates the map or live-provider policy that `README.md` is dropping.

Do not create package READMEs. Do not move `docs/superpowers/` files.

---

### Task 1: Lock and rewrite AGENTS.md

```yaml waygent-task
id: task_1
title: Lock and rewrite AGENTS.md to Invariants, Map, and Done
dependencies: []
file_claims:
  - path: scripts/agent/guidance-ia.test.ts
    mode: owned
  - path: AGENTS.md
    mode: owned
risk: low
verify:
  - bun test scripts/agent/guidance-ia.test.ts
  - bun run agent:contract
```

**Files:**
- Create: `scripts/agent/guidance-ia.test.ts`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: spec sections “AGENTS.md” and “Verification”.
- Produces: `AGENTS.md` with H2 headings `Invariants`, `Map`, `Done` only; map strings listed in the test; `readRepoFile` / `markdownH2` helpers in `scripts/agent/guidance-ia.test.ts` for later tasks.

- [ ] **Step 1: Write the failing test file**

Create `scripts/agent/guidance-ia.test.ts` with this exact content:

```ts
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";

const root = process.cwd();

function readRepoFile(path: string): string {
  return readFileSync(join(root, path), "utf8");
}

function markdownH2(markdown: string): string[] {
  return [...markdown.matchAll(/^## (.+)$/gm)].map((match) => match[1]!);
}

describe("AGENTS.md guidance IA", () => {
  test("has only Invariants, Map, and Done sections", () => {
    expect(markdownH2(readRepoFile("AGENTS.md"))).toEqual([
      "Invariants",
      "Map",
      "Done",
    ]);
  });

  test("map names every current package and app", () => {
    const text = readRepoFile("AGENTS.md");
    for (const path of [
      "apps/cli",
      "apps/api",
      "apps/console",
      "packages/orchestrator",
      "packages/runway-control",
      "packages/provider-adapters",
      "native/kernel",
      "packages/kernel-client",
      "packages/policy",
      "packages/lens-store",
      "packages/lens-projectors",
      "packages/contracts",
      "packages/design-contract",
      "packages/context-packer",
      "packages/testkit",
    ]) {
      expect(text).toContain(path);
    }
  });

  test("does not keep ceremony sections", () => {
    const text = readRepoFile("AGENTS.md");
    expect(text).not.toContain("## Preflight");
    expect(text).not.toContain("## Prompts");
    expect(text).not.toContain("## Safety");
    expect(text).not.toContain("## Git");
    expect(text).not.toContain("git add -A");
    expect(text).not.toContain("Claude Code then reads");
  });

  test("keeps the Lens prohibition in do-not form", () => {
    expect(readRepoFile("AGENTS.md")).toContain(
      "Do not recreate `components/agentlens`",
    );
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
```

Expected: FAIL. Current `AGENTS.md` headings are `Layout`, `Preflight`, `Routing`, `Done`, `Prompts`, `Safety`, `Editing`, `Git`, so `has only Invariants, Map, and Done sections` fails. `packages/context-packer` is also missing from the file.

- [ ] **Step 3: Rewrite AGENTS.md**

Replace `AGENTS.md` with this exact content:

```markdown
# AGENTS.md - Archive

Read this first. If you edit a subtree, also read that subtree's `AGENTS.md`.
Plans: [PLANS.md](PLANS.md). Reviews: [code_review.md](code_review.md).
Docs map: [docs/README.md](docs/README.md).

## Invariants

Waygent owns scheduling, worktrees, providers, verification, recovery, apply,
and event emission. Drive runs with the `waygent` CLI. Do not orchestrate
workers from chat. Do not add a `skills/` tree.

Lens is TypeScript. Do not recreate `components/agentlens`. JSON/JSONL is the
source of truth; SQLite is a rebuildable cache. New events use `platform.*`,
`runway.*`, `kernel.*`, and `lens.*` inside `agentlens.event.v3` records. Old
`agentrunway.*`, `kws-cpe.*`, and `kws-cme.*` names are history, not the
Waygent model.

Do not revert unrelated user work. Keep runtime state out of git: `.waygent/`,
`.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`,
`.superpowers/`, `node_modules/`, `.venv/`, build outputs, caches. Do not
commit secrets or full transcripts. Prefer existing parsers over ad hoc text
scraping. If a behavior change hits a documented contract, update the docs in
the same commit. Reply in Korean when the user writes Korean, unless the
artifact is conventionally English.

## Map

| Area | Paths |
| --- | --- |
| Surfaces | `apps/cli`, `apps/api`, `apps/console` |
| Orchestration | `packages/orchestrator`, `packages/runway-control` |
| Providers and kernel | `packages/provider-adapters`, `native/kernel`, `packages/kernel-client`, `packages/policy` |
| Lens | `packages/lens-store`, `packages/lens-projectors` |
| Contracts and plans | `packages/contracts`, `packages/design-contract`, `packages/context-packer` |
| Tests | `packages/testkit` |

Workflow surface: `waygent` CLI in `apps/cli`.

## Done

Run `bun run agent:verify` plus any extra live evidence the task asked for.
Review against `code_review.md`. Report changed files, exact command results,
skipped opt-in checks, leftover risk, and local vs remote state.
```

- [ ] **Step 4: Run tests and contract**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
bun run agent:contract
```

Expected: both PASS / exit 0. `agent:contract` must not report `stale_active_claim` on `AGENTS.md`.

- [ ] **Step 5: Commit**

```bash
git add -- scripts/agent/guidance-ia.test.ts AGENTS.md
git commit -m "$(cat <<'EOF'
docs: shrink AGENTS.md to invariants, map, and Done

Keep only what an agent must not skip, and name every current package
in the code map.
EOF
)"
```

---

### Task 2: Thin tool guidance files

```yaml waygent-task
id: task_2
title: Thin CLAUDE.md and other tool guidance to pointers
dependencies: [task_1]
file_claims:
  - path: scripts/agent/guidance-ia.test.ts
    mode: shared_append
  - path: CLAUDE.md
    mode: owned
  - path: GEMINI.md
    mode: owned
  - path: .cursor/rules/archive.mdc
    mode: owned
  - path: .github/copilot-instructions.md
    mode: owned
  - path: .codex/README.md
    mode: owned
risk: low
verify:
  - bun test scripts/agent/guidance-ia.test.ts
  - bun run agent:contract
```

**Files:**
- Modify: `scripts/agent/guidance-ia.test.ts` (append the tool-file describe block)
- Modify: `CLAUDE.md`
- Modify: `GEMINI.md`
- Modify: `.cursor/rules/archive.mdc`
- Modify: `.github/copilot-instructions.md`
- Modify: `.codex/README.md`

**Interfaces:**
- Consumes: Task 1 `AGENTS.md` as the only code map and check-command owner.
- Produces: tool files that start from “read `AGENTS.md` first” and do not repeat `bun run check`, `components/agentlens`, or the package inventory.

- [ ] **Step 1: Append failing tool-file tests**

Keep the Task 1 helpers and `AGENTS.md` describe block. Append this describe block to `scripts/agent/guidance-ia.test.ts` (do not delete Task 1 tests):

```ts
describe("tool guidance files", () => {
  test("CLAUDE.md keeps only Claude deltas", () => {
    const text = readRepoFile("CLAUDE.md");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).toContain("Subagents do not write Lens events");
    expect(text).toContain("Keep `.claude/` out of git");
    expect(text).not.toContain("bun run check");
    expect(text).not.toContain("bun run platform:demo");
    expect(text).not.toContain("components/agentlens");
  });

  test("GEMINI.md is a pointer", () => {
    const text = readRepoFile("GEMINI.md");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).not.toContain("apps/cli");
    expect(text).not.toContain("bun run");
  });

  test("cursor rules keep alwaysApply and point at AGENTS.md", () => {
    const text = readRepoFile(".cursor/rules/archive.mdc");
    expect(text).toContain("alwaysApply: true");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).not.toContain("packages/orchestrator");
  });

  test("copilot instructions are a pointer", () => {
    const text = readRepoFile(".github/copilot-instructions.md");
    expect(text).toContain("Read `AGENTS.md`");
    expect(text).not.toContain("packages/lens-store");
  });

  test("codex README keeps config facts and points at AGENTS.md", () => {
    const text = readRepoFile(".codex/README.md");
    expect(text).toContain("config.toml");
    expect(text).toContain("docs/operations/codex-local-setup.md");
    expect(text).toContain("AGENTS.md");
    expect(text).not.toContain("Product surfaces:");
  });
});
```

After the append, the file must still import `readFileSync`, `join`, `describe`, `expect`, and `test`, and still define `readRepoFile` and `markdownH2`.

- [ ] **Step 2: Run the test and confirm the new cases fail**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
```

Expected: FAIL on `CLAUDE.md keeps only Claude deltas` because current `CLAUDE.md` contains `bun run check` and `components/agentlens`. `GEMINI.md is a pointer` also fails because current `GEMINI.md` contains `apps/cli`.

- [ ] **Step 3: Rewrite the tool files**

Replace `CLAUDE.md` with:

```markdown
# CLAUDE.md - Archive

Read `AGENTS.md` first. This file only adds Claude-specific notes.

- Subagents do not write Lens events. Waygent owns drain and emission.
- Keep `.claude/` out of git.
```

Replace `GEMINI.md` with:

```markdown
# GEMINI.md - Archive

Read `AGENTS.md` first. This file only adds Gemini-specific notes.
```

Replace `.cursor/rules/archive.mdc` with:

```markdown
---
description: Archive repository instructions for Cursor agents
alwaysApply: true
---

# Archive

Read `AGENTS.md` first, then the nearest subtree `AGENTS.md`.
```

Replace `.github/copilot-instructions.md` with:

```markdown
# GitHub Copilot Instructions - Archive

Read `AGENTS.md` and the nearest subtree `AGENTS.md` first. This file only
adds Copilot-specific notes.
```

Replace `.codex/README.md` with:

```markdown
# Codex project config

Committed, project-scoped Codex config. Runtime state stays in ignored dirs
listed in `AGENTS.md`.

- `config.toml` — defaults for Codex sessions in this repo

No execpolicy rules are committed. Desktop Full Access tasks skip interactive
approvals, and a project rule that asks for confirmation can reject ordinary
Git commands. Destructive-operation boundaries stay in `AGENTS.md` and the
runner's worktree / protected-ref / remote-mutation checks.

Restart Codex or start a new task after changing project config. See
[local setup](../docs/operations/codex-local-setup.md).
```

- [ ] **Step 4: Run tests and contract**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
bun run agent:contract
```

Expected: both PASS / exit 0.

- [ ] **Step 5: Commit**

```bash
git add -- scripts/agent/guidance-ia.test.ts CLAUDE.md GEMINI.md \
  .cursor/rules/archive.mdc .github/copilot-instructions.md .codex/README.md
git commit -m "$(cat <<'EOF'
docs: thin tool guidance to AGENTS.md pointers

Keep Claude, Gemini, Cursor, Copilot, and Codex files to tool-only
notes so the code map lives in one place.
EOF
)"
```

---

### Task 3: Shared map, lens rename, and current-doc labels

```yaml waygent-task
id: task_3
title: Point current docs at one map and rename lens.md
dependencies: [task_2]
file_claims:
  - path: scripts/agent/guidance-ia.test.ts
    mode: shared_append
  - path: README.md
    mode: owned
  - path: docs/README.md
    mode: owned
  - path: docs/architecture/agentlens.md
    mode: owned
  - path: docs/architecture/lens.md
    mode: owned
  - path: docs/architecture/waygent.md
    mode: owned
  - path: docs/architecture/runtime.md
    mode: owned
  - path: docs/operations/waygent.md
    mode: owned
  - path: docs/roadmap/README.md
    mode: owned
  - path: docs/getting-started.md
    mode: owned
risk: low
verify:
  - bun test scripts/agent/guidance-ia.test.ts
  - bun run agent:contract
  - bun run scripts/agent/check-markdown-links.ts README.md docs/README.md docs/architecture/waygent.md docs/architecture/runtime.md docs/architecture/lens.md docs/operations/waygent.md docs/roadmap/README.md docs/getting-started.md AGENTS.md CLAUDE.md GEMINI.md .github/copilot-instructions.md .codex/README.md
```

**Files:**
- Modify: `scripts/agent/guidance-ia.test.ts` (append the current-docs describe block)
- Modify: `README.md`
- Modify: `docs/README.md`
- Rename: `docs/architecture/agentlens.md` → `docs/architecture/lens.md`
- Modify: `docs/architecture/waygent.md`
- Modify: `docs/architecture/runtime.md`
- Modify: `docs/operations/waygent.md`
- Modify: `docs/roadmap/README.md`
- Modify: `docs/getting-started.md` only if Step 5 finds leftover overlap

**Interfaces:**
- Consumes: Task 1 `AGENTS.md` as the code-map owner; spec table for `docs/README.md`.
- Produces: `docs/architecture/lens.md` as the current Lens page; current docs that do not link to `agentlens.md`; superpowers labeled as executable plan/spec default paths.

- [ ] **Step 1: Append failing current-docs tests**

Keep all Task 1 and Task 2 tests. Append this describe block to `scripts/agent/guidance-ia.test.ts`:

```ts
describe("current docs map", () => {
  test("Lens architecture page is lens.md", () => {
    expect(existsSync(join(root, "docs/architecture/lens.md"))).toBe(true);
    expect(readRepoFile("docs/architecture/lens.md")).toContain("# Lens");
    expect(readRepoFile("docs/architecture/lens.md")).toContain(
      "agentlens.event.v3",
    );
  });

  test("current docs do not link to architecture/agentlens.md", () => {
    for (const path of ["docs/README.md", "docs/architecture/waygent.md"]) {
      const text = readRepoFile(path);
      expect(text).not.toContain("architecture/agentlens.md");
      expect(text).not.toContain("./agentlens.md");
    }
  });

  test("docs/README.md labels superpowers as executable plan/spec paths", () => {
    const text = readRepoFile("docs/README.md");
    expect(text).toContain("docs/superpowers/plans/");
    expect(text).toContain("docs/superpowers/specs/");
    expect(text).not.toMatch(/Design scratch/i);
  });

  test("runtime.md does not list default gate commands", () => {
    const text = readRepoFile("docs/architecture/runtime.md");
    expect(text).not.toContain("## Default gates");
    expect(text).not.toContain("bun run check");
    expect(text).toContain("operations/verification.md");
  });

  test("roadmap does not call superpowers mere proposals", () => {
    expect(readRepoFile("docs/roadmap/README.md")).not.toContain(
      "are proposals until",
    );
  });

  test("root README does not restate apply or live-provider policy", () => {
    const text = readRepoFile("README.md");
    expect(text).toContain("docs/getting-started.md");
    expect(text).toContain("docs/README.md");
    expect(text).not.toContain("WAYGENT_LIVE_PROVIDER");
    expect(text).not.toContain("waygent apply");
    expect(text).not.toContain("## Layout");
  });
});
```

`existsSync` is already imported from `node:fs` in the Task 1 file. Do not add a second import.

- [ ] **Step 2: Run the test and confirm the new cases fail**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
```

Expected: FAIL on `Lens architecture page is lens.md` because `docs/architecture/lens.md` does not exist yet. `current docs do not link to architecture/agentlens.md` also fails (`docs/README.md` and `docs/architecture/waygent.md` still point at `agentlens.md`).

- [ ] **Step 3: Rename the Lens page and retarget current links**

Run:

```bash
git mv docs/architecture/agentlens.md docs/architecture/lens.md
```

Do not change the body of `docs/architecture/lens.md`. It already starts with `# Lens` and already names `agentlens.event.v3`.

In `docs/architecture/waygent.md`, change only the Pages list item:

```markdown
- [Lens](./lens.md)
```

Leave the “Who owns what” table and the ASCII flow as they are. Do not paste the `AGENTS.md` package inventory into this file.

- [ ] **Step 4: Rewrite the shared map, thin README, and relabel superpowers**

Replace `docs/README.md` with:

```markdown
# Docs

Start with the root [README](../README.md) or [AGENTS.md](../AGENTS.md), then
pick a path.

| If you want to | Read |
| --- | --- |
| Install and run | [Getting started](getting-started.md) |
| See which code to change | [AGENTS.md](../AGENTS.md) |
| Understand the runtime | [Architecture](architecture/waygent.md) |
| Run, apply, recover | [Operations](operations/waygent.md) |
| Event and state schemas | [Contracts](contracts/events.md) |
| Author a plan or review | [PLANS.md](../PLANS.md), [code_review.md](../code_review.md) |
| Old records | [history](history/README.md) — not current behavior |
| Executable plan/spec | `docs/superpowers/plans/`, `docs/superpowers/specs/` — default `waygent --plan` / `--spec` paths. Older scratch files also live here |

## Architecture

- [Waygent](architecture/waygent.md)
- [Runtime](architecture/runtime.md)
- [Lens](architecture/lens.md)
- [Decisions](architecture/decisions.md)

## Operations

- [Run, inspect, apply](operations/waygent.md)
- [Codex setup](operations/codex-local-setup.md)
- [Codex best loop](operations/codex-best-loop.md)
- [Recovery](operations/recovery.md)
- [Verification](operations/verification.md)
- [Plan authoring](operations/plan-authoring.md)
- [State root](operations/state-root-migration.md)

## Contracts

- [Events](contracts/events.md)
- [Run state](contracts/run-state.md)
- [Provider result](contracts/provider-result.md)

## History

Old designs, incidents, and migration notes: [history](history/README.md).
```

Replace `README.md` with this file body (the `bash` fences belong inside `README.md`):

````markdown
# Waygent

Local runtime for multi-agent implementation work.

It schedules tasks, isolates worktrees, talks to Codex, Claude, or a fake
provider, verifies the result, and applies only when the run is ready. Lens
stores and projects the evidence. You drive it with the `waygent` CLI.

## First run

See [Getting started](docs/getting-started.md). Codex checkout:
[local setup](docs/operations/codex-local-setup.md).

```bash
bun install --frozen-lockfile
bun run check
bun run platform:demo
```

```bash
waygent run --latest
waygent status --last
waygent explain --last
```

## Docs

- [Getting started](docs/getting-started.md)
- [Doc index](docs/README.md)
- [AGENTS.md](AGENTS.md) for agent work
````

In `docs/architecture/runtime.md`, delete the whole `## Default gates` section (the heading and the three-command bash fence). Append this paragraph at the end of the file:

```markdown
Verification commands live in [verification](../operations/verification.md).
Agent Done is `bun run agent:verify` in [AGENTS.md](../../AGENTS.md).
```

In `docs/operations/waygent.md`, replace the `--plan` / `--spec` paragraph with:

```markdown
`--plan` and `--spec` accept full paths or basenames under
`docs/superpowers/plans/` and `docs/superpowers/specs/`. Those directories are
the default executable plan/spec locations. Older scratch files also live
there. Ambiguous basenames fail with candidates. Typos fail; they are not
treated as inline spec text.
```

In `docs/roadmap/README.md`, replace this sentence:

```markdown
`docs/superpowers/specs/` and `docs/superpowers/plans/` are proposals until
the matching contracts, code, and checks ship.
```

with:

```markdown
`docs/superpowers/specs/` and `docs/superpowers/plans/` are the default
`waygent --plan` / `--spec` locations. Older scratch files also live there.
```

Do not edit the rest of the roadmap file.

- [ ] **Step 5: Check getting-started leftover overlap**

Run:

```bash
rg -n "WAYGENT_LIVE_PROVIDER|## Layout|Design scratch" docs/getting-started.md
```

Expected: no matches. `docs/getting-started.md` already owns install, first commands, and live providers, and does not contain a code map. If this command prints nothing, leave the file unchanged even though it is claimed. If it prints a map or live-provider block that now also lives in `README.md`, delete only that leftover from `docs/getting-started.md` (keep install and first commands there; they are the canonical copy).

- [ ] **Step 6: Run tests, contract, and markdown links**

Run:

```bash
bun test scripts/agent/guidance-ia.test.ts
bun run agent:contract
bun run scripts/agent/check-markdown-links.ts README.md docs/README.md \
  docs/architecture/waygent.md docs/architecture/runtime.md \
  docs/architecture/lens.md docs/operations/waygent.md \
  docs/roadmap/README.md docs/getting-started.md AGENTS.md CLAUDE.md \
  GEMINI.md .github/copilot-instructions.md .codex/README.md
```

Expected: all exit 0.

If `check-markdown-links` reports a missing local target `agentlens.md` from a file that this task is not allowed to edit (`docs/history/`, `docs/migration/`, or `docs/superpowers/`), do not edit the archive file. Recreate a stub at `docs/architecture/agentlens.md` with only:

```markdown
# Lens (moved)

This filename is a stub. Current page: [lens.md](./lens.md).
```

Then rerun the same `check-markdown-links` command. If the reporter is a current-doc file listed above, fix that file’s link instead of adding a stub.

- [ ] **Step 7: Commit**

```bash
git add -- scripts/agent/guidance-ia.test.ts README.md docs/README.md \
  docs/architecture/lens.md docs/architecture/waygent.md \
  docs/architecture/runtime.md docs/operations/waygent.md \
  docs/roadmap/README.md docs/getting-started.md
git add -u -- docs/architecture/agentlens.md
git commit -m "$(cat <<'EOF'
docs: share one map and rename the Lens architecture page

Point humans and agents at docs/README.md, drop overlapping root
README policy, and label superpowers as the executable plan/spec path.
EOF
)"
```

If the stub was created, include `docs/architecture/agentlens.md` in `git add` instead of treating it as deleted.

---

### Task 4: Scoped verification

```yaml waygent-task
id: task_4
title: Verify the living-docs IA on every changed path
dependencies: [task_3]
file_claims:
  - path: scripts/agent/guidance-ia.test.ts
    mode: read_only
  - path: AGENTS.md
    mode: read_only
  - path: CLAUDE.md
    mode: read_only
  - path: GEMINI.md
    mode: read_only
  - path: README.md
    mode: read_only
  - path: docs/README.md
    mode: read_only
risk: low
verify:
  - bun test scripts/agent
  - bun run agent:contract
  - bun run agent:verify -- --path AGENTS.md --path CLAUDE.md --path GEMINI.md --path README.md --path docs/README.md --path docs/architecture/lens.md --path docs/architecture/waygent.md --path docs/architecture/runtime.md --path docs/operations/waygent.md --path docs/roadmap/README.md --path docs/getting-started.md --path .github/copilot-instructions.md --path .codex/README.md --path .cursor/rules/archive.mdc --path scripts/agent/guidance-ia.test.ts
```

**Files:**
- Test only. No content edits unless a command above fails for a reason this plan already names (broken current-doc link, `stale_active_claim`, failing IA test).

**Interfaces:**
- Consumes: all Task 1–3 files.
- Produces: a passing scoped `agent:verify` receipt. Live provider commands stay reported as not run.

- [ ] **Step 1: Run the agent test suite and contract**

Run:

```bash
bun test scripts/agent
bun run agent:contract
```

Expected: PASS / exit 0.

- [ ] **Step 2: Run scoped agent:verify on every path this plan changed**

Run:

```bash
bun run agent:verify -- \
  --path AGENTS.md \
  --path CLAUDE.md \
  --path GEMINI.md \
  --path README.md \
  --path docs/README.md \
  --path docs/architecture/lens.md \
  --path docs/architecture/waygent.md \
  --path docs/architecture/runtime.md \
  --path docs/operations/waygent.md \
  --path docs/roadmap/README.md \
  --path docs/getting-started.md \
  --path .github/copilot-instructions.md \
  --path .codex/README.md \
  --path .cursor/rules/archive.mdc \
  --path scripts/agent/guidance-ia.test.ts
```

If Task 3 created the `docs/architecture/agentlens.md` stub, add `--path docs/architecture/agentlens.md`.

Expected:
- exit 0
- scopes include `docs` (and `full-offline` only if an unknown path appears — that is a bug; do not pass unknown paths)
- `markdown-links` passed on the live `.md` files
- live-provider commands listed as `NOT RUN (opt-in)` if they appear
- do not run `bun run check`, `waygent:scenarios`, console build, or `cargo test`

If `docs/getting-started.md` was never modified, `agent:verify` may still receive `--path docs/getting-started.md`. That is required so the link checker covers the canonical install page after README stopped duplicating it. If verify reports it as an unchanged path, that is fine.

- [ ] **Step 3: Report leftover risk**

In the task completion notes, record this leftover risk verbatim:

`waygent --plan` / `--spec` still default to `docs/superpowers/`. This work only relabeled that fact. Moving those directories is a later change.

- [ ] **Step 4: Commit only if Step 1 or Step 2 forced a fix**

If no files changed in this task, do not create an empty commit. If a fix was required, commit only those files with a message that names the fix, for example:

```bash
git add -- <fixed-paths>
git commit -m "$(cat <<'EOF'
docs: close living-docs IA verification gaps

Fix the scoped verify failure found after the map and guidance rewrite.
EOF
)"
```

---

## Execution notes

- Sequential: Task 1 → Task 2 → Task 3 → Task 4.
- `scripts/agent/guidance-ia.test.ts` is `owned` in Task 1 and `shared_append` after that.
- Do not invoke `scripts/agent/check-markdown-links.ts` with zero file arguments.
- English artifacts. Reply to the user in Korean if they write Korean.
