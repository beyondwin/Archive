import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  validateContract,
  type AgentLensEvent,
  type ApplyReadinessProjection,
  type RunStatus,
  type WaygentRunStateV2
} from "@waygent/contracts";
import {
  projectApplyReadinessFromState,
  projectApplyState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectTimeline,
  projectTrustReport
} from "@waygent/lens-projectors";
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

function streamEvents(events: unknown[], runs: unknown[], scopedRunId?: string, scopedTaskId?: string): Response {
  const frames = [
    sseFrame("lens.snapshot", {
      service: "waygent-local-api",
      runId: scopedRunId ?? null,
      taskId: scopedTaskId ?? null,
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
      const scopedTaskId = url.searchParams.get("taskId") ?? undefined;
      if (runRoot) {
        const runs = scopedRunId
          ? listRealRuns(runRoot).filter((run) => run.run_id === scopedRunId)
          : listRealRuns(runRoot);
        if (scopedRunId && runs.length === 0) {
          return notFound({ error: "run_not_found", runId: scopedRunId });
        }
        const events = filterEventsByTask(scopedRunId
          ? readEvents(runPaths(runRoot, scopedRunId).events)
          : listRunIds(runRoot).flatMap((runId) => readEvents(runPaths(runRoot, runId).events)), scopedTaskId);
        return streamEvents(events, runs, scopedRunId, scopedTaskId);
      }
      const scopedDetail = scopedRunId ? findRun(scopedRunId) : undefined;
      if (scopedRunId && !scopedDetail) {
        return notFound({ error: "run_not_found", runId: scopedRunId });
      }
      const events = filterEventsByTask(scopedDetail
        ? scopedDetail.events
        : demoRunDetails.flatMap((detail) => detail.events), scopedTaskId);
      const runs = scopedRunId ? listRuns().filter((run) => run.runId === scopedRunId) : listRuns();
      return streamEvents(events, runs, scopedRunId, scopedTaskId);
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
          const taskId = url.searchParams.get("taskId") ?? undefined;
          return json({ runId, run_id: runId, task_id: taskId ?? null, events: filterEventsByTask(detail.events, taskId) });
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
        const taskId = url.searchParams.get("taskId") ?? undefined;
        return json({ runId, task_id: taskId ?? null, events: filterEventsByTask(detail.events, taskId) });
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

interface TaskPacketMetadata {
  task_id: string;
  status: string;
  risk: string;
  task_packet_path: string | null;
  task_packet_sha256: string | null;
  unit_manifest: Record<string, unknown> | null;
  checkpoint_refs: string[];
  file_claims: unknown[];
  decision_packet_ref: string | null;
}

interface DecisionPacketMetadata {
  task_id: string;
  failure_class: string | null;
  decision_packet_ref: string;
}

function listRealRuns(runRoot: string): RealRunSummary[] {
  return listRunIds(runRoot).map((runId) => summarizeRealRun(runRoot, runId));
}

function summarizeRealRun(runRoot: string, runId: string): RealRunSummary {
  const events = readEvents(runPaths(runRoot, runId).events);
  const summary = rebuildRunSummary(events);
  const trust = projectTrustReport(events);
  const stateV2 = tryReadRunStateV2(runRoot, runId);
  const applyReadiness = stateV2 ? projectApplyReadinessFromState(stateV2) : null;
  return {
    run_id: runId,
    status: statusFromEvents(events, trust.trust_status),
    trust_status: trust.trust_status,
    apply_status: applyReadiness?.status ?? "not_ready",
    total_events: summary.total_events,
    last_event_type: summary.last_event_type
  };
}

function readRealRunDetail(runRoot: string, runId: string): (RealRunSummary & {
  safe_wave: string[];
  safe_waves: WaygentRunStateV2["safe_waves"];
  run_state_v2: WaygentRunStateV2 | null;
  task_packets: TaskPacketMetadata[];
  provider_attempts: WaygentRunStateV2["provider_attempts"];
  verification: WaygentRunStateV2["verification"];
  reviews: WaygentRunStateV2["reviews"];
  recovery: WaygentRunStateV2["recovery"];
  decision_packets: DecisionPacketMetadata[];
  drift: WaygentRunStateV2["drift"] | null;
  apply_readiness: ApplyReadinessProjection | null;
  execution_explanation: ReturnType<typeof projectExecutionExplanationFromState> | null;
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  trust: ReturnType<typeof projectTrustReport>;
  apply: ReturnType<typeof projectApplyState>;
  events: AgentLensEvent[];
}) | null {
  if (!listRunIds(runRoot).includes(runId)) return null;
  const events = readEvents(runPaths(runRoot, runId).events);
  const stateV2 = tryReadRunStateV2(runRoot, runId);
  const applyReadiness = stateV2 ? projectApplyReadinessFromState(stateV2) : null;
  const summary = summarizeRealRun(runRoot, runId);
  return {
    ...summary,
    status: stateV2 ? runStatusFromV2(stateV2.status) : summary.status,
    apply_status: applyReadiness?.status ?? summary.apply_status,
    safe_wave: safeWaveFromEvents(events),
    safe_waves: stateV2?.safe_waves ?? [],
    run_state_v2: stateV2,
    task_packets: stateV2 ? taskPacketMetadata(stateV2) : [],
    provider_attempts: stateV2?.provider_attempts ?? [],
    verification: stateV2?.verification ?? [],
    reviews: stateV2?.reviews ?? [],
    recovery: stateV2?.recovery ?? [],
    decision_packets: stateV2 ? decisionPacketMetadata(stateV2) : [],
    drift: stateV2?.drift ?? null,
    apply_readiness: applyReadiness,
    execution_explanation: stateV2 ? projectExecutionExplanationFromState(stateV2) : null,
    failures: projectFailureSummary(events),
    timeline: projectTimeline(events),
    trust: projectTrustReport(events),
    apply: projectApplyState(events),
    events
  };
}

function tryReadRunStateV2(runRoot: string, runId: string): WaygentRunStateV2 | null {
  try {
    const parsed = JSON.parse(readFileSync(join(runPaths(runRoot, runId).root, "state.json"), "utf8")) as {
      schema?: string;
    };
    if (parsed.schema !== "waygent.run_state.v2") return null;
    return validateContract<WaygentRunStateV2>("waygent.run_state.v2", parsed);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if (error instanceof SyntaxError) return null;
    return null;
  }
}

function taskPacketMetadata(state: WaygentRunStateV2): TaskPacketMetadata[] {
  return Object.values(state.tasks).map((task) => ({
    task_id: task.id,
    status: task.status,
    risk: task.risk,
    task_packet_path: task.task_packet_path,
    task_packet_sha256: task.task_packet_sha256,
    unit_manifest: task.unit_manifest,
    checkpoint_refs: task.checkpoint_refs,
    file_claims: task.file_claims,
    decision_packet_ref: task.decision_packet_ref
  }));
}

function decisionPacketMetadata(state: WaygentRunStateV2): DecisionPacketMetadata[] {
  return Object.values(state.tasks)
    .filter((task) => task.decision_packet_ref)
    .map((task) => ({
      task_id: task.id,
      failure_class: task.latest_failure_class,
      decision_packet_ref: task.decision_packet_ref as string
    }));
}

function runStatusFromV2(status: WaygentRunStateV2["status"]): RunStatus {
  if (status === "initializing") return "pending";
  if (status === "applying") return "running";
  return status;
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

function filterEventsByTask<T extends { payload?: Record<string, unknown> }>(events: T[], taskId?: string): T[] {
  if (!taskId) return events;
  return events.filter((event) => eventMatchesTask(event, taskId));
}

function eventMatchesTask(event: { payload?: Record<string, unknown> }, taskId: string): boolean {
  const payload = event.payload ?? {};
  const candidates = [
    payload.task_id,
    payload.taskId,
    objectValue(payload.worker, "task_id"),
    objectValue(payload.worker, "taskId"),
    objectValue(payload.kernel, "task_id"),
    objectValue(payload.kernel, "taskId")
  ].filter((value): value is string | number => typeof value === "string" || typeof value === "number");

  if (candidates.some((value) => String(value) === taskId)) return true;

  const taskIds = payload.task_ids ?? payload.taskIds ?? payload.safe_wave;
  return Array.isArray(taskIds) && taskIds.map(String).includes(taskId);
}

function objectValue(value: unknown, key: string): unknown {
  return value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined;
}

if (import.meta.main) {
  const port = Number(Bun.env.PORT ?? 8787);
  Bun.serve({
    port,
    fetch: createApiHandler()
  });
  console.log(`waygent-local-api listening on http://127.0.0.1:${port}`);
}
