import type { AgentLensEvent, RunStatus } from "@waygent/contracts";
import { projectApplyState, projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { listRunIds, readEvents, rebuildRunSummary, runPaths } from "@waygent/lens-store";
import { demoRunDetails, findRun, listRuns } from "./demoData";

export type ApiHandler = (request: Request) => Response | Promise<Response>;

export interface ApiContext {
  runRoot?: string;
}

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

function streamEvents(events: unknown[], runs: unknown[], scopedRunId?: string): Response {
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

export function createApiHandler(context: ApiContext = {}): ApiHandler {
  return (request: Request): Response => {
    const url = new URL(request.url);
    const segments = url.pathname.split("/").filter(Boolean);
    const runRoot = context.runRoot ?? process.env.WAYGENT_RUN_ROOT;

    if (request.method !== "GET") {
      return json({ error: "method_not_allowed" }, { status: 405 });
    }

    if (url.pathname === "/healthz") {
      return json({ ok: true, service: "waygent-local-api" });
    }

    if (url.pathname === "/runs") {
      if (runRoot) {
        return json({ runs: listRealRuns(runRoot) });
      }
      return json({ runs: listRuns() });
    }

    if (url.pathname === "/events/stream") {
      const scopedRunId = url.searchParams.get("runId") ?? undefined;
      if (runRoot) {
        const runs = scopedRunId
          ? listRealRuns(runRoot).filter((run) => run.run_id === scopedRunId)
          : listRealRuns(runRoot);
        if (scopedRunId && runs.length === 0) {
          return notFound({ error: "run_not_found", runId: scopedRunId });
        }
        const events = scopedRunId
          ? readEvents(runPaths(runRoot, scopedRunId).events)
          : listRunIds(runRoot).flatMap((runId) => readEvents(runPaths(runRoot, runId).events));
        return streamEvents(events, runs, scopedRunId);
      }
      const scopedDetail = scopedRunId ? findRun(scopedRunId) : undefined;
      if (scopedRunId && !scopedDetail) {
        return notFound({ error: "run_not_found", runId: scopedRunId });
      }
      const events = scopedDetail
        ? scopedDetail.events
        : demoRunDetails.flatMap((detail) => detail.events);
      const runs = scopedRunId ? listRuns().filter((run) => run.runId === scopedRunId) : listRuns();
      return streamEvents(events, runs, scopedRunId);
    }

    if (segments[0] === "runs" && segments[1]) {
      const runId = segments[1];
      if (runRoot) {
        const detail = readRealRunDetail(runRoot, runId);
        if (!detail) {
          return notFound({ error: "run_not_found", runId });
        }

        if (segments.length === 2) {
          return json(detail);
        }

        if (segments.length === 3 && segments[2] === "events") {
          return json({ runId, run_id: runId, events: detail.events });
        }

        if (segments.length === 3 && segments[2] === "trust") {
          return json({ runId, run_id: runId, trust: detail.trust });
        }

        if (segments.length === 3 && segments[2] === "failures") {
          return json({ runId, run_id: runId, failures: detail.failures });
        }
      }
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

export function handler(request: Request, context: ApiContext = {}): Response | Promise<Response> {
  return createApiHandler(context)(request);
}

interface RealRunSummary {
  run_id: string;
  status: RunStatus;
  trust_status: string;
  apply_status: string;
  total_events: number;
  last_event_type: string | null;
}

function listRealRuns(runRoot: string): RealRunSummary[] {
  return listRunIds(runRoot).map((runId) => summarizeRealRun(runRoot, runId));
}

function summarizeRealRun(runRoot: string, runId: string): RealRunSummary {
  const events = readEvents(runPaths(runRoot, runId).events);
  const summary = rebuildRunSummary(events);
  const trust = projectTrustReport(events);
  const apply = projectApplyState(events);
  return {
    run_id: runId,
    status: statusFromEvents(events, trust.trust_status),
    trust_status: trust.trust_status,
    apply_status: apply.status,
    total_events: summary.total_events,
    last_event_type: summary.last_event_type
  };
}

function readRealRunDetail(runRoot: string, runId: string): (RealRunSummary & {
  safe_wave: string[];
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  trust: ReturnType<typeof projectTrustReport>;
  apply: ReturnType<typeof projectApplyState>;
  events: AgentLensEvent[];
}) | null {
  if (!listRunIds(runRoot).includes(runId)) return null;
  const events = readEvents(runPaths(runRoot, runId).events);
  return {
    ...summarizeRealRun(runRoot, runId),
    safe_wave: safeWaveFromEvents(events),
    failures: projectFailureSummary(events),
    timeline: projectTimeline(events),
    trust: projectTrustReport(events),
    apply: projectApplyState(events),
    events
  };
}

function statusFromEvents(events: AgentLensEvent[], trustStatus: string): RunStatus {
  if (events.some((event) => event.event_type === "runway.apply_completed")) return "applied";
  if (events.some((event) => event.outcome === "blocked")) return "blocked";
  if (events.some((event) => event.outcome === "failed")) return "failed";
  return trustStatus === "trusted" ? "completed" : "running";
}

function safeWaveFromEvents(events: AgentLensEvent[]): string[] {
  const selected = [...events].reverse().find((event) => event.event_type === "runway.safe_wave_selected");
  const safeWave = selected?.payload.safe_wave;
  return Array.isArray(safeWave) ? safeWave.map(String) : [];
}

if (import.meta.main) {
  const port = Number(Bun.env.PORT ?? 8787);
  Bun.serve({
    port,
    fetch: createApiHandler()
  });
  console.log(`waygent-local-api listening on http://127.0.0.1:${port}`);
}
