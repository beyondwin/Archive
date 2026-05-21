import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { classifySourceCheckout } from "../src/sourceCheckout";

describe("source checkout classification", () => {
  test("classifies dirty files against task file claims", () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-source-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "clean\n");
    writeFileSync(join(workspace, "notes.md"), "clean\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "dirty\n");
    mkdirSync(join(workspace, "tmp"), { recursive: true });
    writeFileSync(join(workspace, "tmp", "scratch.txt"), "scratch\n");

    expect(classifySourceCheckout(workspace, [{ path: "README.md", mode: "owned" }])).toMatchObject({
      status: "dirty_related",
      related: ["README.md"]
    });
    expect(classifySourceCheckout(workspace, [{ path: "src/app.ts", mode: "owned" }])).toMatchObject({
      status: "dirty_unrelated"
    });
  });
});
