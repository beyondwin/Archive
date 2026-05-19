import { http, HttpResponse } from "msw";

import type { DoctorReport } from "@/api/doctor";
import type { Meta } from "@/api/meta";
import type { Failure, RunDetail, RunRow } from "@/api/runs";
import type { WorkspaceSummary } from "@/api/workspaces";

type ApiArtifact = {
  path?: string;
  sha256?: string;
  downloadable?: boolean;
};

export const falseSuccessRun: RunRow = {
  run_id: "run_false_success",
  workspace_id: "ws_demo",
  parent_run_id: null,
  started_at: "2026-01-01T00:00:00Z",
  ended_at: "2026-01-01T00:00:12Z",
  agent_name: "codex",
  agent_mode: "cli",
  recording_mode: "full",
  agent_outcome: "success",
  eval_status: "failed",
  sealed_phase: "final",
  display_title: null,
  usage: null,
  import_state: null,
};

export const defaultMeta: Meta = {
  agentlens_version: "0.1.0",
  schema_version: "v1",
  store_path: "/tmp/agentlens",
  store_exists: true,
  demo_mode: true,
};

export const falseSuccessFailure: Failure = {
  run_id: falseSuccessRun.run_id,
  workspace_id: falseSuccessRun.workspace_id,
  category: "UNACKNOWLEDGED_FAILED_COMMAND",
  severity: "high",
  blame_scope: "agent",
  summary: "The run claimed success after a command exited non-zero.",
  confidence: 0.91,
  recoverability: "rerun",
  evidence: ["sha256:abc123"],
};

export const falseSuccessDetail: RunDetail = {
  run_id: falseSuccessRun.run_id,
  agent: "codex",
  agent_name: falseSuccessRun.agent_name,
  agent_mode: falseSuccessRun.agent_mode,
  started_at: falseSuccessRun.started_at,
  ended_at: falseSuccessRun.ended_at,
  agent_outcome: falseSuccessRun.agent_outcome,
  eval_status: falseSuccessRun.eval_status,
  sealed_phase: falseSuccessRun.sealed_phase,
  workspace_id: falseSuccessRun.workspace_id,
  workspace_short: "demo",
  summary: "Agent reported success, evaluator found failed command evidence.",
  display_title: null,
  usage: null,
  import_state: null,
  failures: [falseSuccessFailure],
  risks: [],
  manifest_seal: {
    phase: "final",
    manifest_digest: "sha256:manifestdigest",
    integrity: "ok",
    mismatches_count: 0,
  },
};

export const falseSuccessEvents: Record<string, unknown>[] = [
  {
    type: "command.started",
    command: "npm test",
  },
  {
    type: "command.finished",
    command: "npm test",
    exit_code: 1,
    evidence_sha: "sha256:abc123",
  },
  {
    type: "run.finalized",
    agent_outcome: "success",
  },
];

export const falseSuccessArtifacts: ApiArtifact[] = [
  {
    path: "artifacts/report.json",
    sha256: "sha256:report",
    downloadable: true,
  },
  {
    path: "run.json",
    sha256: "sha256:run",
    downloadable: false,
  },
];

export const defaultWorkspaces: WorkspaceSummary[] = [
  {
    workspace_id: falseSuccessRun.workspace_id,
    workspace_short: "demo",
    id_basis: "path",
    run_count: 1,
    latest_started_at: falseSuccessRun.started_at,
  },
];

export const defaultDoctor: DoctorReport = {
  integrations: {},
  paths: {},
  warnings: [],
};

type HandlerOptions = {
  meta?: Meta;
  runs?: RunRow[];
  detail?: RunDetail;
  events?: Record<string, unknown>[];
  failures?: Failure[];
  artifacts?: ApiArtifact[];
  workspaces?: WorkspaceSummary[];
  doctor?: DoctorReport;
};

function ndjson(events: Record<string, unknown>[]) {
  return new HttpResponse(`${events.map((event) => JSON.stringify(event)).join("\n")}\n`, {
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

function filteredRuns(runs: RunRow[], request: Request): RunRow[] {
  const params = new URL(request.url).searchParams;
  const agent = params.get("agent");
  const evalStatus = params.get("eval_status");
  const agentOutcome = params.get("agent_outcome");
  const workspaceId = params.get("workspace_id");
  const sinceDays = params.get("since_days");

  let items = runs;
  if (agent) items = items.filter((run) => run.agent_name === agent);
  if (evalStatus) items = items.filter((run) => run.eval_status === evalStatus);
  if (agentOutcome) items = items.filter((run) => run.agent_outcome === agentOutcome);
  if (workspaceId) items = items.filter((run) => run.workspace_id === workspaceId);
  if (sinceDays) {
    const days = Number(sinceDays);
    if (Number.isFinite(days)) {
      const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
      items = items.filter((run) => {
        const startedAt = Date.parse(run.started_at);
        return Number.isNaN(startedAt) || startedAt >= cutoff;
      });
    }
  }
  return items;
}

export function agentLensApiHandlers({
  meta = defaultMeta,
  runs = [falseSuccessRun],
  detail = falseSuccessDetail,
  events = falseSuccessEvents,
  failures = [falseSuccessFailure],
  artifacts = falseSuccessArtifacts,
  workspaces = defaultWorkspaces,
  doctor = defaultDoctor,
}: HandlerOptions = {}) {
  return [
    http.get("/api/v1/meta", () => HttpResponse.json(meta)),
    http.get("/api/v1/doctor", () => HttpResponse.json(doctor)),
    http.get("/api/v1/workspaces", () => HttpResponse.json(workspaces)),
    http.get("/api/v1/runs", ({ request }) =>
      HttpResponse.json({
        items: filteredRuns(runs, request),
        next_cursor: null,
      }),
    ),
    http.get("/api/v1/runs/:runId/events", () => ndjson(events)),
    http.get("/api/v1/runs/:runId/failures", () => HttpResponse.json(failures)),
    http.get("/api/v1/runs/:runId/artifacts", ({ params }) => {
      if (params.runId !== detail.run_id) {
        return HttpResponse.json({ detail: "Run not found" }, { status: 404 });
      }
      return HttpResponse.json(artifacts);
    }),
    http.get("/api/v1/runs/:runId", ({ params }) => {
      if (params.runId !== detail.run_id) {
        return HttpResponse.json({ detail: "Run not found" }, { status: 404 });
      }
      return HttpResponse.json(detail);
    }),
  ];
}
