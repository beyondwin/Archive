import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { deleteResolvedOrphan, scanOrphanRuns } from "../src/orphanRuns";

describe("orphan run advisory", () => {
  test("lists invalid run directories without deleting them", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-orphans-"));
    mkdirSync(join(root, "stale_run"), { recursive: true });

    const advisory = scanOrphanRuns({ root });

    expect(advisory.orphans).toEqual([expect.objectContaining({ id: "stale_run", kind: "run_dir" })]);
  });

  test("deletes exactly one validated orphan when confirmed", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-orphans-delete-"));
    mkdirSync(join(root, "stale_run"), { recursive: true });
    writeFileSync(join(root, "valid_state"), "not a run\n");
    const advisory = scanOrphanRuns({ root });

    const deleted = deleteResolvedOrphan({ root, id: "stale_run", yes: true, advisory });

    expect(deleted.deleted).toBe(true);
    expect(scanOrphanRuns({ root }).orphans.map((item) => item.id)).not.toContain("stale_run");
  });
});
