import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { watchRun } from "../src/watchRun";

describe("watch run", () => {
  test("reads existing events as JSONL lines without mutating state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-watch-"));
    const runRoot = join(root, "run_watch");
    mkdirSync(runRoot, { recursive: true });
    writeFileSync(join(runRoot, "events.jsonl"), `${JSON.stringify({
      schema: "agentlens.event.v3",
      event_id: "event_1",
      event_type: "platform.run_started",
      orchestrator_run_id: "run_watch",
      occurred_at: "2026-05-22T00:00:00.000Z",
      sequence: 1,
      phase: "platform",
      outcome: "running",
      severity: "info",
      trust_impact: "neutral",
      summary: "Run opened.",
      payload: {}
    })}\n`);
    writeFileSync(join(runRoot, "state.json"), JSON.stringify({ schema: "waygent.run_state.v2", status: "completed" }));

    const result = watchRun({ root, run: "run_watch", json: true, timeout_ms: 1, filter: "all" });

    expect(result.lines).toHaveLength(1);
    expect(result.lines[0]).toContain("platform.run_started");
  });
});
