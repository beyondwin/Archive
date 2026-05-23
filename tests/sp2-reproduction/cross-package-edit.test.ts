import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { prepareVerificationEnvironment } from "../../packages/orchestrator/src/verificationEnvironment";

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
    JSON.stringify({ name: "@waygent/a", version: "0.0.1", main: "index.js" })
  );
  writeFileSync(join(ws, "packages/a/index.js"), "module.exports = { value: 'main' };");

  mkdirSync(join(ws, "packages/b"), { recursive: true });
  writeFileSync(
    join(ws, "packages/b/package.json"),
    JSON.stringify({ name: "@waygent/b", version: "0.0.1", main: "index.js" })
  );
  writeFileSync(
    join(ws, "packages/b/index.js"),
    "const a = require('@waygent/a'); console.log('B says:', a.value);"
  );

  spawnSync("git", ["init", "-q"], { cwd: ws });
  spawnSync("git", ["add", "."], { cwd: ws });
  spawnSync("git", ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "main"], { cwd: ws });

  return { workspace: ws, cleanup: () => rmSync(ws, { force: true, recursive: true }) };
}

dscribe("SP-2 reproduction: worker cross-package edit", () => {
  const previousFrozen = process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE;
  beforeAll(() => {
    process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE = "0";
  });
  afterAll(() => {
    if (previousFrozen === undefined) delete process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE;
    else process.env.WAYGENT_VERIFY_ISOLATION_FROZEN_LOCKFILE = previousFrozen;
  });

  it("auto-escalates to isolated and verify sees the worker's cross-package value", () => {
    const { workspace, cleanup } = buildSyntheticMain();
    try {
      const worktree = mkdtempSync(join(tmpdir(), "sp2-repro-wt-"));
      const cloneStatus = spawnSync("git", ["clone", "--quiet", workspace, worktree]);
      expect(cloneStatus.status).toBe(0);
      spawnSync("git", ["-c", "user.email=t@t", "-c", "user.name=t", "checkout", "-q", "-b", "worker"], { cwd: worktree });

      writeFileSync(join(worktree, "packages/a/index.js"), "module.exports = { value: 'worker' };");
      writeFileSync(
        join(worktree, "packages/b/index.js"),
        "const a = require('@waygent/a'); console.log('B says:', a.value, '(b-edited)');"
      );

      const prepared = prepareVerificationEnvironment({ workspace, worktree });
      try {
        expect(prepared.evidence.decision.requested).toBe("auto");
        expect(prepared.evidence.decision.resolved).toBe("isolated");
        expect(prepared.evidence.decision.reason).toBe("diff_cross_package");
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
