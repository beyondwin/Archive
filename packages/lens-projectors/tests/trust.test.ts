import { describe, expect, test } from "bun:test";
import { projectTrustReport } from "../src";
import { demoEvent } from "./support";

describe("trust projector", () => {
  test("requires verification or kernel evidence", () => {
    expect(projectTrustReport([demoEvent({ event_type: "runway.worker_result" })]).trust_status).toBe("insufficient_evidence");
  });

  test("trusts verified runs and fails failed evidence", () => {
    expect(projectTrustReport([demoEvent()]).trust_status).toBe("trusted");
    expect(projectTrustReport([demoEvent({ outcome: "failed" })]).trust_status).toBe("failed");
  });
});
