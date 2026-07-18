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

test("force-with-lease requires confirmation", async () => {
  expect(await decision(["git", "push", "--force-with-lease", "origin", "main"]))
    .toBe("prompt");
});
