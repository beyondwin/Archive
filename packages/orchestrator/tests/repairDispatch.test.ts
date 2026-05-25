import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { prepareRepairWorktree } from "../src/repairDispatch";

function makeRepoWithPatchArtifact(): { root: string; patchPath: string } {
  const root = mkdtempSync(join(tmpdir(), "waygent-repair-disp-"));
  spawnSync("git", ["init", "-q", "-b", "main"], { cwd: root });
  spawnSync("git", ["config", "user.email", "test@test"], { cwd: root });
  spawnSync("git", ["config", "user.name", "test"], { cwd: root });
  writeFileSync(join(root, "a.txt"), "v1\n");
  spawnSync("git", ["add", "a.txt"], { cwd: root });
  spawnSync("git", ["commit", "-q", "-m", "init"], { cwd: root });
  const wt = join(root, ".tmpwt");
  spawnSync("git", ["worktree", "add", "-b", "scratch", wt, "main"], { cwd: root });
  writeFileSync(join(wt, "a.txt"), "v1\nv2\n");
  const patch = spawnSync("git", ["diff", "main", "--binary"], { cwd: wt, encoding: "utf8" }).stdout;
  spawnSync("git", ["worktree", "remove", "--force", wt], { cwd: root });
  spawnSync("git", ["branch", "-D", "scratch"], { cwd: root });
  const patchPath = join(root, "patch.diff");
  writeFileSync(patchPath, patch);
  return { root, patchPath };
}

describe("prepareRepairWorktree", () => {
  test("creates a fresh worktree at the requested path and applies the prior patch", () => {
    const { root, patchPath } = makeRepoWithPatchArtifact();
    const dest = join(root, "wt", "repair_1");
    try {
      const result = prepareRepairWorktree({
        source_repo: root,
        destination: dest,
        base_branch: "main",
        prior_patch_path: patchPath
      });
      expect(result.status).toBe("ready");
      expect(existsSync(dest)).toBe(true);
      const status = spawnSync("git", ["status", "--porcelain"], { cwd: dest, encoding: "utf8" }).stdout;
      expect(status.length).toBeGreaterThan(0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  test("returns blocked status when prior patch fails to apply", () => {
    const { root } = makeRepoWithPatchArtifact();
    const dest = join(root, "wt", "repair_bad");
    const bogus = join(root, "bogus.diff");
    writeFileSync(bogus, "not a real patch\n");
    try {
      const result = prepareRepairWorktree({
        source_repo: root,
        destination: dest,
        base_branch: "main",
        prior_patch_path: bogus
      });
      expect(result.status).toBe("blocked");
      if (result.status === "blocked") {
        expect(result.reason).toBe("prior_patch_apply_failed");
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
