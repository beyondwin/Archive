import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";

const root = process.cwd();

function readRepoFile(path: string): string {
  return readFileSync(join(root, path), "utf8");
}

function markdownH2(markdown: string): string[] {
  return [...markdown.matchAll(/^## (.+)$/gm)].map((match) => match[1]!);
}

describe("AGENTS.md guidance IA", () => {
  test("has only Invariants, Map, and Done sections", () => {
    expect(markdownH2(readRepoFile("AGENTS.md"))).toEqual([
      "Invariants",
      "Map",
      "Done",
    ]);
  });

  test("map names every current package and app", () => {
    const text = readRepoFile("AGENTS.md");
    for (const path of [
      "apps/cli",
      "apps/api",
      "apps/console",
      "packages/orchestrator",
      "packages/runway-control",
      "packages/provider-adapters",
      "native/kernel",
      "packages/kernel-client",
      "packages/policy",
      "packages/lens-store",
      "packages/lens-projectors",
      "packages/contracts",
      "packages/design-contract",
      "packages/context-packer",
      "packages/testkit",
    ]) {
      expect(text).toContain(path);
    }
  });

  test("does not keep ceremony sections", () => {
    const text = readRepoFile("AGENTS.md");
    expect(text).not.toContain("## Preflight");
    expect(text).not.toContain("## Prompts");
    expect(text).not.toContain("## Safety");
    expect(text).not.toContain("## Git");
    expect(text).not.toContain("git add -A");
    expect(text).not.toContain("Claude Code then reads");
  });

  test("keeps the Lens prohibition in do-not form", () => {
    expect(readRepoFile("AGENTS.md")).toContain(
      "Do not recreate `components/agentlens`",
    );
  });
});
