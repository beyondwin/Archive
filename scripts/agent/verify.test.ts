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
        ? "packages/z.ts\0문서/새 파일.md\0line\nbreak.ts\0"
        : "docs/new.md\0packages/z.ts\0";
    },
  });

  expect(calls).toEqual([
    ["diff", "--name-only", "--diff-filter=ACMR", "-z", "HEAD"],
    ["ls-files", "--others", "--exclude-standard", "-z"],
  ]);
  expect(paths).toEqual([
    "docs/new.md",
    "line\nbreak.ts",
    "packages/z.ts",
    "문서/새 파일.md",
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
      return "docs/README.md\0";
    },
  });

  expect(calls).toEqual([
    ["diff", "--name-only", "--diff-filter=ACMR", "-z", "origin/main...HEAD"],
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

test("live provider evidence is selected but never executed by default", async () => {
  const calls: string[] = [];
  const result = await runVerification({
    root: process.cwd(),
    paths: ["bun.lock"],
    run: async (command) => {
      calls.push(command.id);
      return 0;
    },
  });

  expect(calls).not.toContain("waygent-live-provider-smoke");
  expect(result.commandResults).toContainEqual({
    id: "waygent-live-provider-smoke",
    exitCode: 0,
    skipped: true,
  });
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
    "  \"AGENTS.md\"",
    "  \"docs/README.md\"",
    "scopes:",
    "  \"docs\"",
    "commands:",
    "  [skipped] \"markdown-links\": argv=[\"bun\",\"run\",\"scripts/agent/check-markdown-links.ts\",\"AGENTS.md\",\"docs/README.md\"]",
    "  [skipped] \"agent-contract\": argv=[\"bun\",\"run\",\"agent:contract\"]",
    "  [skipped] \"diff-check\": argv=[\"git\",\"diff\",\"--check\"]",
    "opt-in:",
    "  none",
    "exit-code: 0",
    "",
  ].join("\n"));
});

test("CLI reports live provider evidence as opt-in and not run", async () => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const child = Bun.spawn([
    "bun", script, "--dry-run", "--path", "bun.lock",
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(0);
  const stdout = await new Response(child.stdout).text();
  expect(stdout).toContain(
    "[NOT RUN (opt-in)] \"waygent-live-provider-smoke\": argv=[\"bun\",\"run\",\"waygent:live-provider-smoke\"]",
  );
  expect(stdout).toContain(
    "NOT RUN (opt-in) \"waygent-live-provider-smoke\": argv=[\"bun\",\"run\",\"waygent:live-provider-smoke\"]",
  );
});

test.each([
  ["console", "apps/console/src/App.tsx", "\"console-test\": argv=[\"bun\",\"test\",\"src\"] cwd=\"apps/console\""],
  ["native", "native/kernel/crates/kernel-cli/src/main.rs", "\"rust-test\": argv=[\"cargo\",\"test\",\"--workspace\"] cwd=\"native/kernel\""],
  ["executor", "skills/kws-codex-plan-executor/scripts/cpe.py", "\"codex-executor-eval\": argv=[\"./evals/run.sh\"] cwd=\"skills/kws-codex-plan-executor\""],
])("CLI includes cwd in $0 command summaries", async (_name, path, expected) => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const child = Bun.spawn([
    "bun", script, "--dry-run", "--path", path,
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(0);
  expect(await new Response(child.stdout).text()).toContain(expected);
});

test("CLI JSON-escapes newline paths in paths, command IDs, and argv", async () => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const path = "tests/line\ncommands:\nattack.test.ts";
  const child = Bun.spawn([
    "bun", script, "--dry-run", "--path", path,
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(0);
  const stdout = await new Response(child.stdout).text();
  expect(stdout).toContain("\"tests/line\\ncommands:\\nattack.test.ts\"");
  expect(stdout).toContain(
    "argv=[\"bun\",\"test\",\"tests/line\\ncommands:\\nattack.test.ts\"]",
  );
  expect(stdout.match(/^commands:$/gm)).toHaveLength(1);
});

test.each(["../outside.test.ts", "/tmp/outside.test.ts"])(
  "CLI rejects explicit path outside root before selection: %s",
  async (path) => {
    const script = join(process.cwd(), "scripts/agent/verify.ts");
    const child = Bun.spawn([
      "bun", script, "--dry-run", "--path", path,
    ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

    expect(await child.exited).toBe(2);
    expect(await new Response(child.stdout).text()).toBe("");
    expect(await new Response(child.stderr).text()).toBe(
      `--path must stay within repository: ${JSON.stringify(path)}\n`,
    );
  },
);
