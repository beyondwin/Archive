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

describe("tool guidance files", () => {
  test("CLAUDE.md keeps only Claude deltas", () => {
    const text = readRepoFile("CLAUDE.md");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).toContain("Subagents do not write Lens events");
    expect(text).toContain("Keep `.claude/` out of git");
    expect(text).not.toContain("bun run check");
    expect(text).not.toContain("bun run platform:demo");
    expect(text).not.toContain("components/agentlens");
  });

  test("GEMINI.md is a pointer", () => {
    const text = readRepoFile("GEMINI.md");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).not.toContain("apps/cli");
    expect(text).not.toContain("bun run");
  });

  test("cursor rules keep alwaysApply and point at AGENTS.md", () => {
    const text = readRepoFile(".cursor/rules/archive.mdc");
    expect(text).toContain("alwaysApply: true");
    expect(text).toContain("Read `AGENTS.md` first");
    expect(text).not.toContain("packages/orchestrator");
  });

  test("copilot instructions are a pointer", () => {
    const text = readRepoFile(".github/copilot-instructions.md");
    expect(text).toContain("Read `AGENTS.md`");
    expect(text).not.toContain("packages/lens-store");
  });

  test("codex README keeps config facts and points at AGENTS.md", () => {
    const text = readRepoFile(".codex/README.md");
    expect(text).toContain("config.toml");
    expect(text).toContain("docs/operations/codex-local-setup.md");
    expect(text).toContain("AGENTS.md");
    expect(text).not.toContain("Product surfaces:");
  });
});

describe("current docs map", () => {
  test("Lens architecture page is lens.md", () => {
    expect(existsSync(join(root, "docs/architecture/lens.md"))).toBe(true);
    expect(readRepoFile("docs/architecture/lens.md")).toContain("# Lens");
    expect(readRepoFile("docs/architecture/lens.md")).toContain(
      "agentlens.event.v3",
    );
  });

  test("current docs do not link to architecture/agentlens.md", () => {
    for (const path of ["docs/README.md", "docs/architecture/waygent.md"]) {
      const text = readRepoFile(path);
      expect(text).not.toContain("architecture/agentlens.md");
      expect(text).not.toContain("./agentlens.md");
    }
  });

  test("docs/README.md labels superpowers as executable plan/spec paths", () => {
    const text = readRepoFile("docs/README.md");
    expect(text).toContain("docs/superpowers/plans/");
    expect(text).toContain("docs/superpowers/specs/");
    expect(text).not.toMatch(/Design scratch/i);
  });

  test("runtime.md does not list default gate commands", () => {
    const text = readRepoFile("docs/architecture/runtime.md");
    expect(text).not.toContain("## Default gates");
    expect(text).not.toContain("bun run check");
    expect(text).toContain("operations/verification.md");
  });

  test("roadmap does not call superpowers mere proposals", () => {
    expect(readRepoFile("docs/roadmap/README.md")).not.toContain(
      "are proposals until",
    );
  });

  test("root README does not restate apply or live-provider policy", () => {
    const text = readRepoFile("README.md");
    expect(text).toContain("docs/getting-started.md");
    expect(text).toContain("docs/README.md");
    expect(text).not.toContain("WAYGENT_LIVE_PROVIDER");
    expect(text).not.toContain("waygent apply");
    expect(text).not.toContain("## Layout");
  });
});

