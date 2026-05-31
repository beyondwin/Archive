import { describe, expect, test } from "bun:test";
import { projectTrustReport } from "../src";
import * as projectors from "../src";
import { demoEvent, stateFixture } from "./support";

const historicalRunwayEventType = ["agent", "runway"].join("") + ".worker_started";

type ProjectorModule = typeof projectors & {
  projectRunwayProjection?: (events: Parameters<typeof projectTrustReport>[0], safe_wave?: string[]) => {
    schema: "lens.runway_projection.v1";
    run_id: string;
    status: string;
    safe_wave: string[];
    trust_status: string;
    event_count: number;
  };
};

describe("trust projector", () => {
  test("requires verification or kernel evidence", () => {
    expect(projectTrustReport([demoEvent({ event_type: "runway.worker_result" })]).trust_status).toBe("insufficient_evidence");
  });

  test("trusts verified runs and fails failed evidence", () => {
    expect(projectTrustReport([demoEvent()]).trust_status).toBe("trusted");
    expect(projectTrustReport([demoEvent({ outcome: "failed" })]).trust_status).toBe("failed");
  });

  test("runway projection does not expose legacy source metadata", () => {
    const projectRunwayProjection = (projectors as ProjectorModule).projectRunwayProjection;
    expect(projectRunwayProjection).toBeFunction();

    const projection = projectRunwayProjection!([
      demoEvent({ event_type: historicalRunwayEventType, outcome: "running", sequence: 1 })
    ]);

    expect(projection).toEqual({
      schema: "lens.runway_projection.v1",
      run_id: "run_demo",
      status: "running",
      safe_wave: [],
      trust_status: "insufficient_evidence",
      event_count: 1
    });
  });

  test("projects blocked, failed, and running runway states", () => {
    const projectRunwayProjection = (projectors as ProjectorModule).projectRunwayProjection;
    expect(projectRunwayProjection).toBeFunction();

    expect(projectRunwayProjection!([demoEvent({ outcome: "blocked" })]).status).toBe("blocked");
    expect(projectRunwayProjection!([demoEvent({ outcome: "failed" })]).status).toBe("failed");
    expect(projectRunwayProjection!([demoEvent({ event_type: "runway.worker_result" })]).status).toBe("running");
  });

  test("keeps stale verification failures recovered when latest verification passed", () => {
    const state = stateFixture({
      verification: [
        {
          verification_id: "verify_task_demo_1",
          task_id: "task_demo",
          command: "bun test",
          status: "failed",
          verified_at: "2026-05-26T00:00:00.000Z"
        },
        {
          verification_id: "verify_task_demo_2",
          task_id: "task_demo",
          command: "bun test",
          status: "passed",
          verified_at: "2026-05-26T00:01:00.000Z"
        }
      ],
      recovery: [{ task_id: "task_demo", failure_class: "verification_failed" }],
      completion_audit: {
        status: "failed",
        residual_risk: ["review_evidence:recovery_attempted"]
      }
    });

    const report = projectTrustReport([
      demoEvent({
        event_id: "event_failed",
        sequence: 1,
        outcome: "failed",
        payload: { task_id: "task_demo", verification_id: "verify_task_demo_1" }
      }),
      demoEvent({
        event_id: "event_passed",
        sequence: 2,
        outcome: "success",
        payload: { task_id: "task_demo", verification_id: "verify_task_demo_2" }
      })
    ], state);

    expect(report).toMatchObject({
      trust_status: "needs_review",
      active_failure_count: 0,
      recovered_failure_count: 1
    });
  });

  test("trusts recovered failure history after review and audit evidence", () => {
    const state = stateFixture({
      verification: [{
        verification_id: "verify_task_demo_2",
        task_id: "task_demo",
        command: "bun test",
        status: "passed",
        verified_at: "2026-05-26T00:01:00.000Z"
      }],
      recovery: [{ task_id: "task_demo", failure_class: "verification_failed" }],
      reviews: [{
        schema: "runway.review_result.v1",
        run_id: "run_demo",
        task_id: "task_demo",
        attempt_id: "review_task_demo_1",
        provider: "codex",
        verdict: "pass",
        spec_score: 1,
        quality_score: 1,
        findings: [],
        residual_risk: [],
        summary: "Review passed."
      }],
      completion_audit: {
        status: "passed",
        review_evidence: [{ task_id: "task_demo", status: "passed" }]
      }
    });

    const report = projectTrustReport([
      demoEvent({
        event_id: "event_passed",
        sequence: 2,
        outcome: "success",
        payload: { task_id: "task_demo", verification_id: "verify_task_demo_2" }
      })
    ], state);

    expect(report).toMatchObject({
      trust_status: "trusted",
      active_failure_count: 0,
      recovered_failure_count: 1
    });
  });
});
