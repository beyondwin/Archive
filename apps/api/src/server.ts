import { demoRunDetails, findRun, listRuns, type RunEvent } from "./demoData";

export type ApiHandler = (request: Request) => Response | Promise<Response>;

function json(value: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(value), { ...init, headers });
}

function notFound(value: unknown): Response {
  return json(value, { status: 404 });
}

function sseFrame(eventName: string, data: unknown): string {
  return `event: ${eventName}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamEvents(events: RunEvent[], scopedRunId?: string): Response {
  const runs = scopedRunId ? listRuns().filter((run) => run.runId === scopedRunId) : listRuns();
  const frames = [
    sseFrame("lens.snapshot", {
      service: "waygent-local-api",
      runId: scopedRunId ?? null,
      runs
    }),
    ...events.map((event) => sseFrame("agentlens.event.v3", event))
  ];

  return new Response(frames.join(""), {
    headers: {
      "cache-control": "no-cache",
      connection: "keep-alive",
      "content-type": "text/event-stream; charset=utf-8"
    }
  });
}

export function createApiHandler(): ApiHandler {
  return (request: Request): Response => {
    const url = new URL(request.url);
    const segments = url.pathname.split("/").filter(Boolean);

    if (request.method !== "GET") {
      return json({ error: "method_not_allowed" }, { status: 405 });
    }

    if (url.pathname === "/healthz") {
      return json({ ok: true, service: "waygent-local-api" });
    }

    if (url.pathname === "/runs") {
      return json({ runs: listRuns() });
    }

    if (url.pathname === "/events/stream") {
      const scopedRunId = url.searchParams.get("runId") ?? undefined;
      const scopedDetail = scopedRunId ? findRun(scopedRunId) : undefined;
      if (scopedRunId && !scopedDetail) {
        return notFound({ error: "run_not_found", runId: scopedRunId });
      }
      const events = scopedDetail
        ? scopedDetail.events
        : demoRunDetails.flatMap((detail) => detail.events);
      return streamEvents(events, scopedRunId);
    }

    if (segments[0] === "runs" && segments[1]) {
      const runId = segments[1];
      const detail = findRun(runId);
      if (!detail) {
        return notFound({ error: "run_not_found", runId });
      }

      if (segments.length === 2) {
        return json(detail);
      }

      if (segments.length === 3 && segments[2] === "events") {
        return json({ runId, events: detail.events });
      }

      if (segments.length === 3 && segments[2] === "trust") {
        return json({ runId, trust: detail.trust });
      }

      if (segments.length === 3 && segments[2] === "failures") {
        return json({ runId, failures: detail.failures });
      }
    }

    return notFound({ error: "not_found", path: url.pathname });
  };
}

if (import.meta.main) {
  const port = Number(Bun.env.PORT ?? 8787);
  Bun.serve({
    port,
    fetch: createApiHandler()
  });
  console.log(`waygent-local-api listening on http://127.0.0.1:${port}`);
}
