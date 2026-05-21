import { describe, expect, test } from "bun:test";
import { createApiHandler } from "../src/server";

describe("Waygent local API event stream", () => {
  test("GET /events/stream returns server-sent event frames for demo runs", async () => {
    const handler = createApiHandler();
    const response = await handler(new Request("http://waygent.local/events/stream"));

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/event-stream");

    const body = await response.text();
    const frames = body.trim().split("\n\n");

    expect(frames[0]).toStartWith("event: lens.snapshot\n");
    expect(frames.some((frame) => frame.includes("event: agentlens.event.v3"))).toBe(true);
    expect(body).toContain("\"eventType\":\"runway.worker_result\"");
    expect(body).toContain("\"runId\":\"run_demo_blocked\"");
  });

  test("GET /events/stream can be scoped to a single run", async () => {
    const handler = createApiHandler();
    const response = await handler(
      new Request("http://waygent.local/events/stream?runId=run_demo_failed")
    );

    expect(response.status).toBe(200);
    const body = await response.text();

    expect(body).toContain("\"runId\":\"run_demo_failed\"");
    expect(body).not.toContain("\"runId\":\"run_demo_trusted\"");
  });
});
