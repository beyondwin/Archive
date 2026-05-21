import { describe, expect, test } from "bun:test";
import { projectTrustReport } from "../src";
import * as projectors from "../src";
import { demoEvent } from "./support";

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
});
