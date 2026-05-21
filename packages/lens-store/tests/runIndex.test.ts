import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readLatestRunId, writeLatestRunId } from "../src/runIndex";

describe("run index", () => {
  test("writes and reads the latest run id", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-index-"));

    writeLatestRunId(root, "run_demo");

    expect(readLatestRunId(root)).toBe("run_demo");
    expect(readFileSync(join(root, "latest"), "utf8")).toBe("run_demo\n");
  });

  test("returns null when no latest pointer exists", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-index-empty-"));

    expect(readLatestRunId(root)).toBeNull();
  });

  test("returns null when latest pointer is empty", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-index-empty-file-"));
    writeFileSync(join(root, "latest"), "\n");

    expect(readLatestRunId(root)).toBeNull();
  });
});
