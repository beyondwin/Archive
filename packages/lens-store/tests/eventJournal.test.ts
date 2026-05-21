import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { appendEvent, nextSequence, readEvents } from "../src";
import { demoEvent } from "../../lens-projectors/tests/support";

describe("event journal", () => {
  test("appends and reads ordered AgentLens events", () => {
    const path = join(mkdtempSync(join(tmpdir(), "waygent-journal-")), "events.jsonl");
    appendEvent(path, demoEvent({ sequence: 1, event_type: "platform.run_started" }));
    appendEvent(path, demoEvent({ sequence: 2, event_type: "runway.worker_result" }));
    const events = readEvents(path);
    expect(events.map((event) => event.event_type)).toEqual(["platform.run_started", "runway.worker_result"]);
    expect(nextSequence(events)).toBe(3);
  });
});
