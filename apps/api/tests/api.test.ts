import { describe, expect, test } from "bun:test";
import { createApiHandler } from "../src/server";

const handler = createApiHandler();

async function get(path: string): Promise<Response> {
  return handler(new Request(`http://waygent.local${path}`));
}

describe("Waygent local API routes", () => {
  test("GET /healthz reports local API status", async () => {
    const response = await get("/healthz");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      ok: true,
      service: "waygent-local-api"
    });
  });

  test("GET /runs lists demo runs with apply and trust summaries", async () => {
    const response = await get("/runs");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.runs).toHaveLength(3);
    expect(body.runs[0]).toMatchObject({
      runId: "run_demo_trusted",
      status: "completed",
      trustVerdict: "trusted",
      applyStatus: "ready"
    });
  });

  test("GET /runs/:runId returns run detail sections for the console", async () => {
    const response = await get("/runs/run_demo_blocked");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.run.runId).toBe("run_demo_blocked");
    expect(body.tasks.map((task: { status: string }) => task.status)).toContain(
      "AWAITING_HUMAN_DECISION"
    );
    expect(body.decisionPackets[0]).toMatchObject({
      taskId: "task_verify",
      failureClass: "verification_failed"
    });
    expect(body.applyStatus).toMatchObject({
      state: "blocked",
      dirtySourceCheckout: true
    });
  });

  test("GET /runs/:runId/events returns ordered events", async () => {
    const response = await get("/runs/run_demo_trusted/events");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.events.map((event: { eventType: string }) => event.eventType)).toEqual([
      "platform.run_started",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "lens.trust_report_updated"
    ]);
  });

  test("GET /runs/:runId/trust and /failures return projections", async () => {
    const trustResponse = await get("/runs/run_demo_failed/trust");
    expect(trustResponse.status).toBe(200);
    expect(await trustResponse.json()).toMatchObject({
      trust: { verdict: "failed" }
    });

    const failuresResponse = await get("/runs/run_demo_failed/failures");
    expect(failuresResponse.status).toBe(200);
    const body = await failuresResponse.json();
    expect(body.failures[0]).toMatchObject({
      taskId: "task_worker",
      failureClass: "adapter_crashed",
      recoveryAction: "switch_provider"
    });
  });

  test("unknown routes and runs return JSON 404 responses", async () => {
    expect((await get("/missing")).status).toBe(404);

    const missingRun = await get("/runs/nope");
    expect(missingRun.status).toBe(404);
    expect(await missingRun.json()).toEqual({
      error: "run_not_found",
      runId: "nope"
    });
  });
});
