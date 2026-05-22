import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  validateContract,
  type AgentLensEvent,
  type ApplyReadinessProjection,
  type OperatorDecisionProjection,
  type RunStatus,
  type WaygentRunStateV2
} from "@waygent/contracts";
import {
  projectApplyState,
  projectExecutionExplanationFromState,
  projectFailureSummary,
  projectOperationalMaturityFromState,
  projectOperatorDecisionFromState,
  projectRunReadModel,
  projectTimeline,
  projectTrustReport
} from "@waygent/lens-projectors";
import { listRunIds, readEvents, runPaths } from "@waygent/lens-store";
import { demoRunDetails, findRun, listRuns } from "./demoData";

export type ApiHandler = (request: Request) => Response | Promise<Response>;

export interface ApiContext {
  runRoot?: string;
}

function json(value: unknown, init: ResponseInit = {}): Response {
  const headers = corsHeaders(init.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(value), { ...init, headers });
}

function notFound(value: unknown): Response {
  return json(value, { status: 404 });
}

function corsHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET, OPTIONS");
  headers.set("access-control-allow-headers", "content-type");
  return headers;
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
    headers: corsHeaders({
      "cache-control": "no-cache",
      connection: "keep-alive",
      "content-type": "text/event-stream; charset=utf-8"
    })
  });
}

export function createApiHandler(context: ApiContext = {}): ApiHandler {
  return (request: Request): Response => {
    const url = new URL(request.url);
    const segments = url.pathname.split("/").filter(Boolean);
    const runRoot = context.runRoot ?? process.env.WAYGENT_RUN_ROOT;

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

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
  operator_status: string;
  primary_blocker: string | null;
  next_action: string | null;
  operator_confidence: string;
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
  const stateResult = readRealRunStateV2Result(runRoot, runId);
  const stateV2 = stateResult.status === "ok" ? stateResult.state : null;
  const model = projectRunReadModel({
    run_id: runId,
    events,
    ...(stateResult.status === "ok" ? { state: stateResult.state } : { state_error: readModelStateBlocker(stateResult) })
  });
  const operatorDecision = projectRealOperatorDecision(runId, events, stateV2, stateResult);
  return {
    run_id: runId,
    status: model.status,
    trust_status: model.trust_status,
    apply_status: model.apply_status,
    operator_status: operatorDecision.status_summary.display_status,
    primary_blocker: operatorDecision.primary_blocker?.code ?? null,
    next_action: nextOperatorAction(operatorDecision),
    operator_confidence: operatorDecision.confidence,
    total_events: model.total_events,
    last_event_type: model.last_event_type
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
  operational_maturity: ReturnType<typeof projectOperationalMaturityFromState> | null;
  dogfood_evidence: ReturnType<typeof projectOperationalMaturityFromState>["dogfood_evidence"] | null;
  runtime_cost: ReturnType<typeof projectOperationalMaturityFromState>["runtime_cost"] | null;
  provider_readiness: ReturnType<typeof projectOperationalMaturityFromState>["provider_readiness"] | null;
  operator_decision: OperatorDecisionProjection;
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  trust: ReturnType<typeof projectTrustReport>;
  apply: ReturnType<typeof projectApplyState>;
  events: AgentLensEvent[];
}) | null {
  if (!listRunIds(runRoot).includes(runId)) return null;
  const events = readEvents(runPaths(runRoot, runId).events);
  const stateResult = readRealRunStateV2Result(runRoot, runId);
  const stateV2 = stateResult.status === "ok" ? stateResult.state : null;
  const model = projectRunReadModel({
    run_id: runId,
    events,
    ...(stateResult.status === "ok" ? { state: stateResult.state } : { state_error: readModelStateBlocker(stateResult) })
  });
  const applyReadiness = model.apply_readiness;
  const executionExplanation = model.execution_explanation;
  const operationalMaturity = model.operational_maturity;
  const operatorDecision = projectRealOperatorDecision(runId, events, stateV2, stateResult);
  const summary = summarizeRealRun(runRoot, runId);
  return {
    ...summary,
    status: model.status,
    apply_status: model.apply_status,
    safe_wave: model.safe_wave,
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
    execution_explanation: executionExplanation,
    operational_maturity: operationalMaturity,
    dogfood_evidence: operationalMaturity?.dogfood_evidence ?? null,
    runtime_cost: operationalMaturity?.runtime_cost ?? null,
    provider_readiness: operationalMaturity?.provider_readiness ?? null,
    operator_decision: operatorDecision,
    failures: model.failures,
    timeline: model.timeline,
    trust: model.trust,
    apply: projectApplyState(events),
    events
  };
}

type RealRunStateV2ReadResult =
  | { status: "ok"; state: WaygentRunStateV2 }
  | { status: "missing"; reason: "missing_run_state_v2" }
  | { status: "unsupported"; reason: "unsupported_run_state"; schema: unknown }
  | { status: "invalid"; reason: "invalid_run_state_v2"; error: string };

function readRealRunStateV2Result(runRoot: string, runId: string): RealRunStateV2ReadResult {
  try {
    const parsed = JSON.parse(readFileSync(join(runPaths(runRoot, runId).root, "state.json"), "utf8")) as {
      schema?: string;
    };
    if (parsed.schema !== "waygent.run_state.v2") return { status: "unsupported", reason: "unsupported_run_state", schema: parsed.schema };
    return { status: "ok", state: validateContract<WaygentRunStateV2>("waygent.run_state.v2", parsed) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { status: "missing", reason: "missing_run_state_v2" };
    return { status: "invalid", reason: "invalid_run_state_v2", error: error instanceof Error ? error.message : String(error) };
  }
}

function readModelStateBlocker(result: Exclude<RealRunStateV2ReadResult, { status: "ok" }>) {
  if (result.status === "unsupported") return { status: result.status, reason: result.reason, schema: result.schema };
  if (result.status === "invalid") return { status: result.status, reason: result.reason, error: result.error };
  return { status: result.status, reason: result.reason };
}

function projectRealOperatorDecision(
  runId: string,
  events: AgentLensEvent[],
  stateV2: WaygentRunStateV2 | null,
  stateResult: RealRunStateV2ReadResult
): OperatorDecisionProjection {
  if (stateResult.status === "ok") {
    return projectOperatorDecisionFromState({ state: stateV2 ?? stateResult.state, events });
  }
  return projectOperatorDecisionFromState({
    state: null,
    events,
    run_id: runId,
    state_error: stateResult
  });
}

function nextOperatorAction(operatorDecision: OperatorDecisionProjection): string | null {
  const action = operatorDecision.allowed_actions.find((candidate) =>
    !["inspect_run", "explain_run", "open_raw_evidence"].includes(candidate.id)
  ) ?? operatorDecision.allowed_actions[0];
  return action?.id ?? null;
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
