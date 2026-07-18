import { expect, test } from "bun:test";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { collectChangedPaths, runVerification } from "./verify";

test("typecheck targets project configs instead of every workspace entry", async () => {
  const packageJson = JSON.parse(await readFile(join(process.cwd(), "package.json"), "utf8")) as {
    scripts: Record<string, string>;
  };

  expect(packageJson.scripts.typecheck).toBe(
    "tsc -b apps/*/tsconfig.json packages/*/tsconfig.json",
  );
});

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

test("fail-fast records commands after the failure as skipped", async () => {
  const result = await runVerification({
    root: process.cwd(),
    paths: ["apps/console/src/App.tsx"],
    run: async (command) => command.id === "console-test" ? 1 : 0,
  });

  expect(result.commandResults.at(-1)).toEqual({
    id: "console-build",
    exitCode: 0,
    skipped: true,
  });
});

test("collects working tree and untracked paths without a range", async () => {
  const calls: string[][] = [];
  const paths = await collectChangedPaths({
    root: "/fixture",
    git: async (args) => {
      calls.push([...args]);
      return args[0] === "diff"
        ? "packages/z.ts\napps/api/src/index.ts\n"
        : "docs/new.md\npackages/z.ts\n";
    },
  });

  expect(calls).toEqual([
    ["diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
    ["ls-files", "--others", "--exclude-standard"],
  ]);
  expect(paths).toEqual([
    "apps/api/src/index.ts",
    "docs/new.md",
    "packages/z.ts",
  ]);
});

test("collects a three-dot commit range", async () => {
  const calls: string[][] = [];
  const paths = await collectChangedPaths({
    root: "/fixture",
    base: "origin/main",
    head: "HEAD",
    git: async (args) => {
      calls.push([...args]);
      return "docs/README.md\n";
    },
  });

  expect(calls).toEqual([
    ["diff", "--name-only", "--diff-filter=ACMR", "origin/main...HEAD"],
  ]);
  expect(paths).toEqual(["docs/README.md"]);
});

test("rejects an incomplete commit range", async () => {
  expect(collectChangedPaths({ root: "/fixture", base: "origin/main" }))
    .rejects.toThrow("base and head must be provided together");
});

test("dry-run records selected commands as skipped", async () => {
  const result = await runVerification({
    root: process.cwd(),
    paths: ["docs/README.md"],
    dryRun: true,
  });

  expect(result.commandResults).toEqual([
    { id: "markdown-links", exitCode: 0, skipped: true },
    { id: "agent-contract", exitCode: 0, skipped: true },
    { id: "diff-check", exitCode: 0, skipped: true },
  ]);
  expect(result.exitCode).toBe(0);
});

test("Markdown links run before the selected verification commands", async () => {
  const calls: string[] = [];
  await runVerification({
    root: process.cwd(),
    paths: ["docs/README.md"],
    run: async (command) => {
      calls.push(command.id);
      return 0;
    },
  });

  expect(calls).toEqual(["markdown-links", "agent-contract", "diff-check"]);
});

test("CLI rejects mixing explicit paths and a commit range", async () => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const child = Bun.spawn([
    "bun", script,
    "--dry-run", "--path", "docs/README.md",
    "--base", "origin/main", "--head", "HEAD",
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(2);
  expect(await new Response(child.stderr).text()).toBe(
    "cannot mix --path with --base/--head\n",
  );
});

test("CLI prints a stable dry-run summary for repeated paths", async () => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const child = Bun.spawn([
    "bun", script,
    "--dry-run", "--path", "docs/README.md", "--path", "AGENTS.md",
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(0);
  expect(await new Response(child.stdout).text()).toBe([
    "paths:",
    "  AGENTS.md",
    "  docs/README.md",
    "scopes:",
    "  docs",
    "commands:",
    "  [skipped] markdown-links: bun run scripts/agent/check-markdown-links.ts AGENTS.md docs/README.md",
    "  [skipped] agent-contract: bun run agent:contract",
    "  [skipped] diff-check: git diff --check",
    "opt-in:",
    "  none",
    "exit-code: 0",
    "",
  ].join("\n"));
});
