import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { runLegacyCheck } from "../src/legacyCheck";

function fixtureRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "waygent-legacy-check-"));
  for (const dir of ["apps", "packages", "native", "tests", "docs/architecture", "docs/operations", "docs/migration", "skills"]) {
    mkdirSync(join(root, dir), { recursive: true });
  }
  writeFileSync(join(root, "AGENTS.md"), "Waygent owns execution.\n");
  writeFileSync(join(root, "CLAUDE.md"), "Use Waygent CLI.\n");
  writeFileSync(join(root, "GEMINI.md"), "Use Waygent CLI.\n");
  writeFileSync(join(root, "skills/README.md"), "| waygent | active runtime |\n");
  return root;
}

describe("legacy check", () => {
  test("rejects active AgentRunway routing references", () => {
    const root = fixtureRoot();
    writeFileSync(join(root, "AGENTS.md"), "Use skills/agent-runway/SKILL.md for execution.\n");

    const result = runLegacyCheck(root);

    expect(result.passed).toBe(false);
    expect(result.violations).toContain("AGENTS.md: active AgentRunway routing reference");
  });

  test("allows historical migration references outside active routing", () => {
    const root = fixtureRoot();
    writeFileSync(join(root, "docs/migration/history.md"), "Removed skills/agent-runway after parity.\n");

    expect(runLegacyCheck(root)).toEqual({ passed: true, violations: [] });
  });
});
