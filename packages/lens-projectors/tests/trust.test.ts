import { describe, expect, test } from "bun:test";
import { projectTrustReport } from "../src";
import * as projectors from "../src";
import { demoEvent } from "./support";

type ProjectorModule = typeof projectors & {
  projectRunwayProjection?: (events: Parameters<typeof projectTrustReport>[0], safe_wave?: string[]) => {
    schema: "lens.runway_projection.v1";
    run_id: string;
    status: string;
    safe_wave: string[];
    trust_status: string;
    event_count: number;
    legacy_source: "agentrunway" | null;
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

  test("projects runway status and preserves event inputs", () => {
    const projectRunwayProjection = (projectors as ProjectorModule).projectRunwayProjection;
    expect(projectRunwayProjection).toBeFunction();

    const projection = projectRunwayProjection!(
      [
        demoEvent({ event_type: "agentrunway.worker_started", outcome: "running", sequence: 1 }),
        demoEvent({ event_type: "kernel.execution_result", outcome: "success", sequence: 2 })
      ],
      ["task_demo"]
    );

    expect(projection).toEqual({
      schema: "lens.runway_projection.v1",
      run_id: "run_demo",
      status: "completed",
      safe_wave: ["task_demo"],
      trust_status: "trusted",
      event_count: 2,
      legacy_source: "agentrunway"
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
