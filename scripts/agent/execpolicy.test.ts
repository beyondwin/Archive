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
  expect(await decision(["git", "status", "--short"])).toBe("prompt");
  expect(await decision(["git", "worktree", "list", "--porcelain"]))
    .toBe("prompt");
});

test("force-with-lease requires confirmation", async () => {
  expect(await decision(["git", "push", "--force-with-lease", "origin", "main"]))
    .toBe("prompt");
});

test("destructive option spellings cannot bypass the policy", async () => {
  expect(await decision(["git", "push", "--force-with-lease=refs/heads/main", "origin", "main"]))
    .toBe("prompt");
  expect(await decision(["git", "branch", "--delete", "--force", "feature"]))
    .toBe("prompt");
  expect(await decision(["git", "branch", "-d", "--force", "feature"]))
    .toBe("prompt");
  expect(await decision(["git", "push", "-f", "origin", "main"]))
    .toBe("forbidden");
  expect(await decision(["git", "push", "origin", "main", "--force"]))
    .toBe("prompt");
  expect(await decision(["git", "push", "origin", "main", "--force-with-lease=refs/heads/main"]))
    .toBe("prompt");
});

test("global Git options cannot bypass the prompt fallback", async () => {
  expect(await decision(["git", "-C", "/tmp", "push", "--force", "origin", "main"]))
    .toBe("prompt");
  expect(await decision(["git", "--git-dir=/tmp/example.git", "push", "--force", "origin", "main"]))
    .toBe("prompt");
  expect(await decision(["git", "--work-tree=/tmp", "push", "-f", "origin", "main"]))
    .toBe("prompt");
  expect(await decision(["git", "log", "-1", "--oneline"])).toBe("prompt");
});
