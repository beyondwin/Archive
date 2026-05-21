import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { readProjectionCache, rebuildProjectionCache } from "../src";
import { demoEvent } from "../../lens-projectors/tests/support";

describe("SQLite projection cache", () => {
  test("is rebuilt from filesystem events", () => {
    const dbPath = join(mkdtempSync(join(tmpdir(), "waygent-cache-")), "projection.sqlite");
    const events = [demoEvent({ sequence: 1 }), demoEvent({ sequence: 2, event_type: "kernel.exec_completed" })];
    expect(rebuildProjectionCache(dbPath, events).total_events).toBe(2);
    expect(readProjectionCache(dbPath).last_event_type).toBe("kernel.exec_completed");
  });
});
