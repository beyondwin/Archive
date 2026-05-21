import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readEvents, runPaths } from "@waygent/lens-store";
import { createRunExecutionContext } from "../src/runExecutionContext";
import { buildRunEvent } from "../src/runEvents";
import { readRunStateV2 } from "../src/runState";
import { baseV2State } from "./support/runStateFixture";

describe("RunExecutionContext", () => {
  test("serializes event sequence allocation and state mutation", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-context-"));
    const state = baseV2State({ root, run_id: "run_context" });
    const context = createRunExecutionContext({ root, state, next_sequence: 1 });

    context.appendEvent((sequence) =>
      buildRunEvent({
        run_id: "run_context",
        sequence,
        event_type: "platform.run_started",
        phase: "platform",
        outcome: "running",
        summary: "started",
        payload: {}
      })
    );
    context.mutateState((draft) => {
      draft.current_phase = "dispatch";
      draft.tasks.task_a!.status = "running";
    });
    context.appendEvent((sequence) =>
      buildRunEvent({
        run_id: "run_context",
        sequence,
        event_type: "runway.worker_result",
        phase: "worker",
        outcome: "success",
        summary: "worker",
        payload: {}
      })
    );
    context.flushState();

    expect(readEvents(runPaths(root, "run_context").events).map((event) => event.sequence)).toEqual([1, 2]);
    expect(context.state.tasks.task_a?.status).toBe("running");
    expect(readRunStateV2(root, "run_context").current_phase).toBe("dispatch");
  });

  test("allocates explicit sequence numbers through the same cursor", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-run-context-"));
    const state = baseV2State({ root, run_id: "run_context_sequences" });
    const context = createRunExecutionContext({ root, state, next_sequence: 7 });

    expect(context.nextSequence()).toBe(7);
    expect(context.appendEvent((sequence) =>
      buildRunEvent({
        run_id: "run_context_sequences",
        sequence,
        event_type: "platform.run_started",
        phase: "platform",
        outcome: "running",
        summary: "started",
        payload: {}
      })
    ).sequence).toBe(8);
  });
});
