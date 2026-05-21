import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { prepareVerificationEnvironment } from "../src/verificationEnvironment";

describe("verification environment", () => {
  test("links source node_modules into the worktree for verification and cleans it up", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    writeFileSync(join(workspace, "node_modules", ".keep"), "source dependency marker\n");

    const prepared = prepareVerificationEnvironment({ workspace, worktree });

    expect(prepared.evidence.status).toBe("prepared");
    expect(prepared.evidence.strategy).toBe("inherit_node_modules");
    expect(existsSync(join(worktree, "node_modules"))).toBe(true);

    prepared.cleanup();
    expect(existsSync(join(worktree, "node_modules"))).toBe(false);
  });

  test("does not overwrite an existing worktree node_modules", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    mkdirSync(join(worktree, "node_modules"));

    const prepared = prepareVerificationEnvironment({ workspace, worktree });

    expect(prepared.evidence.status).toBe("skipped");
    expect(prepared.evidence.reason).toBe("worktree_node_modules_exists");
    prepared.cleanup();
    expect(existsSync(join(worktree, "node_modules"))).toBe(true);
  });

  test("skips dependency inheritance when disabled", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));

    const prepared = prepareVerificationEnvironment({ workspace, worktree, disabled: true });

    expect(prepared.evidence.status).toBe("skipped");
    expect(prepared.evidence.reason).toBe("disabled");
    expect(existsSync(join(worktree, "node_modules"))).toBe(false);
  });

  test("records cleanup failures without throwing from cleanup", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    const prepared = prepareVerificationEnvironment({ workspace, worktree });
    rmSync(join(worktree, "node_modules"), { force: true, recursive: true });
    symlinkSync(join(workspace, "node_modules"), join(worktree, "node_modules"));

    prepared.cleanup();

    expect(prepared.evidence.cleanup_status).toBe("removed");
  });

  test("does not report cleanup removed when the inherited dependency link was replaced", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-verify-env-source-"));
    const worktree = mkdtempSync(join(tmpdir(), "waygent-verify-env-worktree-"));
    mkdirSync(join(workspace, "node_modules"));
    const prepared = prepareVerificationEnvironment({ workspace, worktree });
    const inheritedPath = join(worktree, "node_modules");

    rmSync(inheritedPath, { force: true, recursive: true });
    mkdirSync(inheritedPath);

    prepared.cleanup();

    expect(existsSync(inheritedPath)).toBe(true);
    expect(prepared.evidence.cleanup_status).toBe("failed");
    expect(prepared.evidence.reason).toContain("not a symbolic link");
  });
});
