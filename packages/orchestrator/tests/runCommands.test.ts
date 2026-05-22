import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendEvent, runPaths, writeLatestRunId } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { buildRunEvent, explainRun, nextRunEvent, resumeRun, statusRun } from "../src/runCommands";
import { inspectRun } from "../src/runCommands";
import { initSourceCheckout } from "./support/orchestratorFixtures";

describe("Waygent run commands", () => {
  test("status reads the latest run projection", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-status-"));
    const paths = runPaths(root, "run_demo");
    writeLatestRunId(root, "run_demo");
    appendEvent(
      paths.events,
      buildRunEvent({
        run_id: "run_demo",
        sequence: 1,
        event_type: "platform.run_started",
        phase: "platform",
        outcome: "running",
        summary: "Run opened.",
        payload: {}
      })
    );
    appendEvent(
      paths.events,
      buildRunEvent({
        run_id: "run_demo",
        sequence: 2,
        event_type: "runway.verification_result",
        phase: "verify",
        outcome: "success",
        summary: "Verified.",
        payload: { task_id: "task_demo" }
      })
    );

    expect(statusRun({ root, last: true })).toMatchObject({
      run_id: "run_demo",
      status: "completed",
      total_events: 2,
      last_event_type: "runway.verification_result"
    });
  });

  test("explain uses events but resume blocks without v2 state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-explain-"));
    const paths = runPaths(root, "run_blocked");
    writeLatestRunId(root, "run_blocked");
    appendEvent(
      paths.events,
      buildRunEvent({
        run_id: "run_blocked",
        sequence: 1,
        event_type: "runway.decision_packet_created",
        phase: "runway",
        outcome: "blocked",
        summary: "Verification failed.",
        payload: { task_id: "task_verify", failure_class: "verification_failed" }
      })
    );

    const explanation = explainRun({ root, last: true });
    expect(explanation.blocked_by).toBe("state_missing");
    expect(explanation.operator_decision.primary_blocker).toMatchObject({ code: "state_missing" });
    expect(explanation.summary).toBe(explanation.operator_decision.status_summary.summary);
    expect(resumeRun({ root, last: true, dry_run: true })).toEqual({
      run_id: "run_blocked",
      allowed_actions: ["inspect_run", "human_decision"],
      dry_run: true,
      blocked_by: "missing_run_state_v2"
    });
  });

  test("next run event increments from the event journal", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-next-event-"));
    const paths = runPaths(root, "run_next");
    appendEvent(
      paths.events,
      buildRunEvent({
        run_id: "run_next",
        sequence: 1,
        event_type: "platform.run_started",
        phase: "platform",
        outcome: "running",
        summary: "Run opened.",
        payload: {}
      })
    );

    const event = nextRunEvent(paths.events, {
      run_id: "run_next",
      event_type: "runway.verification_result",
      phase: "verify",
      outcome: "success",
      summary: "Verified.",
      payload: { task_id: "task_demo" }
    });

    expect(event.sequence).toBe(2);
    expect(event.occurred_at).not.toBe("2026-05-21T00:00:00Z");
  });

  test("build run event supports deterministic timestamps only when explicit", () => {
    const event = buildRunEvent({
      run_id: "run_next_event",
      sequence: 1,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "running",
      summary: "Run opened.",
      payload: {},
      occurred_at: "2026-05-21T00:00:00Z"
    });
    expect(event.occurred_at).toBe("2026-05-21T00:00:00Z");
    expect(buildRunEvent({
      run_id: "run_runtime_time",
      sequence: 1,
      event_type: "platform.run_started",
      phase: "platform",
      outcome: "running",
      summary: "Run opened.",
      payload: {}
    }).occurred_at).not.toBe("2026-05-21T00:00:00Z");
  });

  test("inspect includes durable state and completed runs can apply verified checkpoint", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-inspect-state-"));
    await runWaygent({ root, workspace: initSourceCheckout("waygent-inspect-source-"), run_id: "run_stateful" });

    expect(inspectRun({ root, run: "run_stateful" }).state).toMatchObject({
      status: "completed",
      completion_audit: { status: "passed" }
    });
    expect(resumeRun({ root, run: "run_stateful", dry_run: true }).allowed_actions).toEqual([
      "inspect_run",
      "apply_verified_checkpoint"
    ]);
  });
});
