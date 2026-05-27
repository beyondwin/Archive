import { describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, readlinkSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildSpawnEnv, prepareCodexWorkerHomeEnv } from "../src/processAdapters";

describe("buildSpawnEnv - nested host env sanitization", () => {
  test("drops nested Claude host env vars when CLAUDECODE=1 in parent", () => {
    const parent = {
      PATH: "/usr/bin",
      CLAUDECODE: "1",
      CLAUDE_CODE_ENTRYPOINT: "cli",
      CLAUDE_PROJECT_DIR: "/host-project",
      OTHER: "kept"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CLAUDECODE).toBeUndefined();
    expect(env.CLAUDE_CODE_ENTRYPOINT).toBeUndefined();
    expect(env.CLAUDE_PROJECT_DIR).toBeUndefined();
    expect(env.PATH).toBe("/usr/bin");
    expect(env.OTHER).toBe("kept");
  });

  test("drops nested host env vars when CLAUDE_CODE_ENTRYPOINT is set in parent", () => {
    const parent = {
      PATH: "/usr/bin",
      CLAUDE_CODE_ENTRYPOINT: "vscode",
      CLAUDE_PROJECT_DIR: "/host-project"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CLAUDE_CODE_ENTRYPOINT).toBeUndefined();
    expect(env.CLAUDE_PROJECT_DIR).toBeUndefined();
  });

  test("WAYGENT_KEEP_HOST_ENV=1 preserves host env vars", () => {
    const parent = {
      PATH: "/usr/bin",
      CLAUDECODE: "1",
      CLAUDE_CODE_ENTRYPOINT: "cli",
      CLAUDE_PROJECT_DIR: "/host-project",
      WAYGENT_KEEP_HOST_ENV: "1"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CLAUDECODE).toBe("1");
    expect(env.CLAUDE_CODE_ENTRYPOINT).toBe("cli");
    expect(env.CLAUDE_PROJECT_DIR).toBe("/host-project");
  });

  test("does not strip vars when parent is not a Claude Code host", () => {
    const parent = {
      PATH: "/usr/bin",
      CLAUDE_PROJECT_DIR: "/leftover-but-no-host"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CLAUDE_PROJECT_DIR).toBe("/leftover-but-no-host");
  });

  test("merges optionEnv on top of sanitized parent env and sets PWD from cwd", () => {
    const parent = {
      PATH: "/usr/bin",
      CLAUDECODE: "1"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, { EXTRA: "value", PATH: "/override" }, "/work");
    expect(env.CLAUDECODE).toBeUndefined();
    expect(env.EXTRA).toBe("value");
    expect(env.PATH).toBe("/override");
    expect(env.PWD).toBe("/work");
  });

  test("drops nested Codex host env vars when CODEX_APP=1 in parent", () => {
    const parent = {
      PATH: "/usr/bin",
      CODEX_APP: "1",
      CODEX_CLI: "1",
      CODEX_ENTRYPOINT: "cli",
      CODEX_HOME: "/home/user/.codex",
      OTHER: "kept"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CODEX_APP).toBeUndefined();
    expect(env.CODEX_CLI).toBeUndefined();
    expect(env.CODEX_ENTRYPOINT).toBeUndefined();
    // CODEX_HOME points at credential storage and MUST survive sanitization.
    expect(env.CODEX_HOME).toBe("/home/user/.codex");
    expect(env.OTHER).toBe("kept");
  });

  test("drops nested Codex host env vars when CODEX_CLI=1 in parent", () => {
    const parent = {
      CODEX_CLI: "1",
      CODEX_HOME: "/codex-home",
      CODEX_APP: "1"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CODEX_CLI).toBeUndefined();
    expect(env.CODEX_APP).toBeUndefined();
    expect(env.CODEX_HOME).toBe("/codex-home");
  });

  test("drops nested Codex host env vars when CODEX_ENTRYPOINT is set in parent", () => {
    const parent = {
      CODEX_ENTRYPOINT: "ide",
      CODEX_APP: "1",
      CODEX_HOME: "/codex-home"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CODEX_ENTRYPOINT).toBeUndefined();
    expect(env.CODEX_APP).toBeUndefined();
    expect(env.CODEX_HOME).toBe("/codex-home");
  });

  test("WAYGENT_KEEP_HOST_ENV=1 also preserves Codex host vars", () => {
    const parent = {
      CODEX_APP: "1",
      CODEX_CLI: "1",
      CODEX_ENTRYPOINT: "cli",
      WAYGENT_KEEP_HOST_ENV: "1"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CODEX_APP).toBe("1");
    expect(env.CODEX_CLI).toBe("1");
    expect(env.CODEX_ENTRYPOINT).toBe("cli");
  });

  test("sanitizes mixed host signals (Claude + Codex parent both detected)", () => {
    const parent = {
      CLAUDECODE: "1",
      CODEX_CLI: "1",
      CLAUDE_PROJECT_DIR: "/p",
      CODEX_ENTRYPOINT: "cli",
      CODEX_HOME: "/h"
    } as NodeJS.ProcessEnv;
    const env = buildSpawnEnv(parent, undefined, undefined);
    expect(env.CLAUDECODE).toBeUndefined();
    expect(env.CODEX_CLI).toBeUndefined();
    expect(env.CLAUDE_PROJECT_DIR).toBeUndefined();
    expect(env.CODEX_ENTRYPOINT).toBeUndefined();
    expect(env.CODEX_HOME).toBe("/h");
  });

  test("prepares a minimal Codex worker home without inheriting host MCP config", () => {
    const previous = process.env.CODEX_HOME;
    const sourceHome = mkdtempSync(join(tmpdir(), "codex-source-home-"));
    writeFileSync(join(sourceHome, "auth.json"), "{}\n");
    process.env.CODEX_HOME = sourceHome;
    try {
      const prepared = prepareCodexWorkerHomeEnv({ PATH: "/usr/bin" }, "/worktree");
      expect(prepared.env.CODEX_HOME).toBeDefined();
      expect(prepared.env.CODEX_HOME).not.toBe(sourceHome);
      expect(readlinkSync(join(prepared.env.CODEX_HOME!, "auth.json"))).toBe(join(sourceHome, "auth.json"));
      const config = readFileSync(join(prepared.env.CODEX_HOME!, "config.toml"), "utf8");
      expect(config).toContain('approval_policy = "never"');
      expect(config).toContain('[projects."/worktree"]');
      expect(config).not.toContain("mcp_servers");
      const workerHome = prepared.env.CODEX_HOME!;
      prepared.cleanup();
      expect(existsSync(workerHome)).toBe(false);
    } finally {
      if (previous === undefined) delete process.env.CODEX_HOME;
      else process.env.CODEX_HOME = previous;
      rmSync(sourceHome, { force: true, recursive: true });
    }
  });

  test("does not replace an explicitly supplied Codex home", () => {
    const prepared = prepareCodexWorkerHomeEnv({
      CODEX_HOME: "/custom/codex-home",
      WAYGENT_DISABLE_CODEX_WORKER_HOME: "1"
    }, "/worktree");
    expect(prepared.env.CODEX_HOME).toBe("/custom/codex-home");
  });
});
