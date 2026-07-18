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

test("native kernel and CI pin the same Rust toolchain", async () => {
  const [workflow, manifest] = await Promise.all([
    readFile(join(process.cwd(), ".github/workflows/agent-contract.yml"), "utf8"),
    readFile(join(process.cwd(), "native/kernel/rust-toolchain.toml"), "utf8"),
  ]);

  expect(workflow).toContain("toolchain: 1.95.0");
  expect(manifest).toContain('channel = "1.95.0"');
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
    ["rev-parse", "--verify", "origin/main"],
    ["rev-parse", "--verify", "HEAD"],
    ["diff", "--name-only", "--diff-filter=ACMR", "-z", "origin/main...HEAD"],
  ]);
  expect(paths).toEqual(["docs/README.md"]);
});

test("all-zero push base diffs the empty tree against the final branch head", async () => {
  const calls: string[][] = [];
  const paths = await collectChangedPaths({
    root: process.cwd(),
    base: "0000000000000000000000000000000000000000",
    head: "new-branch-head",
    git: async (args) => {
      calls.push([...args]);
      if (args[0] === "hash-object") return "empty-tree-oid\n";
      return args.includes("--name-only") ? "first-commit.md\0second-commit.md\0" : "";
    },
  });
  expect(paths).toEqual(["first-commit.md", "second-commit.md"]);
  expect(calls).toEqual([
    ["rev-parse", "--verify", "new-branch-head"],
    ["hash-object", "-t", "tree", "/dev/null"],
    [
      "diff", "--name-only", "--diff-filter=ACMR", "-z",
      "empty-tree-oid", "new-branch-head",
    ],
  ]);
});

test("all-zero SHA-256 push base uses the empty tree endpoint", async () => {
  const calls: string[][] = [];
  await collectChangedPaths({
    root: process.cwd(),
    base: "0".repeat(64),
    head: "sha256-head",
    git: async (args) => {
      calls.push([...args]);
      return args[0] === "hash-object" ? "sha256-empty-tree\n" : "";
    },
  });

  expect(calls).toEqual([
    ["rev-parse", "--verify", "sha256-head"],
    ["hash-object", "-t", "tree", "/dev/null"],
    [
      "diff", "--name-only", "--diff-filter=ACMR", "-z",
      "sha256-empty-tree", "sha256-head",
    ],
  ]);
});

test.each([1, 39, 41, 63, 65])(
  "invalid %i-zero base uses normal range validation",
  async (length) => {
    const base = "0".repeat(length);
    const head = "HEAD";
    const calls: string[][] = [];

    await expect(collectChangedPaths({
      root: process.cwd(),
      base,
      head,
      git: async (args) => {
        calls.push([...args]);
        if (args.at(-1) === base || args.at(-1) === head) {
          throw new Error("unknown revision");
        }
        return "";
      },
    })).rejects.toMatchObject({
      code: "invalid_git_range",
      base,
      head,
    });

    expect(calls).toEqual([
      ["rev-parse", "--verify", base],
      ["rev-parse", "--verify", head],
    ]);
  },
);

test("reports the original range when normal range refs cannot resolve", async () => {
  const base = "missing-base";
  const head = "missing-head";
  const calls: string[][] = [];

  await expect(collectChangedPaths({
    root: process.cwd(),
    base,
    head,
    git: async (args) => {
      calls.push([...args]);
      if (args.at(-1) === base || args.at(-1) === head) {
        throw new Error("unknown revision");
      }
      return "";
    },
  })).rejects.toMatchObject({
    code: "invalid_git_range",
    base,
    head,
  });
  expect(calls).toEqual([
    ["rev-parse", "--verify", base],
    ["rev-parse", "--verify", head],
  ]);
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

test("Claude offline checks execute while the live full eval stays opt-in", async () => {
  const calls: string[] = [];
  const result = await runVerification({
    root: process.cwd(),
    paths: ["skills/kws-claude-multi-agent-executor/SKILL.md"],
    run: async (command) => {
      calls.push(command.id);
      return 0;
    },
  });

  expect(calls).toContain("claude-executor-offline");
  expect(calls).not.toContain("claude-executor-eval");
  expect(result.commandResults).toContainEqual({
    id: "claude-executor-eval",
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

test("CLI reports the Claude full eval as opt-in and not run", async () => {
  const script = join(process.cwd(), "scripts/agent/verify.ts");
  const child = Bun.spawn([
    "bun", script, "--dry-run", "--path", "skills/kws-claude-multi-agent-executor/SKILL.md",
  ], { cwd: process.cwd(), stdout: "pipe", stderr: "pipe" });

  expect(await child.exited).toBe(0);
  const stdout = await new Response(child.stdout).text();
  expect(stdout).toContain(
    "[NOT RUN (opt-in)] \"claude-executor-eval\": argv=[\"./evals/run.sh\"] cwd=\"skills/kws-claude-multi-agent-executor\"",
  );
  expect(stdout).toContain(
    "NOT RUN (opt-in) \"claude-executor-eval\": argv=[\"./evals/run.sh\"] cwd=\"skills/kws-claude-multi-agent-executor\"",
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
