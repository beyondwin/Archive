export type TrustVerdict = "trusted" | "failed" | "insufficient_evidence";
export type ApplyState = "ready" | "blocked" | "not_ready" | "applied";

export interface ConsoleEvent {
  eventId: string;
  runId: string;
  eventType: string;
  sequence: number;
  outcome: "success" | "failed" | "blocked" | "running";
  severity: "info" | "warning" | "error";
  summary: string;
}

export interface ConsoleTask {
  taskId: string;
  title: string;
  status: string;
  owner: string;
  checkpoint: string;
}

export interface ConsoleFailure {
  taskId: string;
  failureClass: string;
  recoveryAction: string;
  summary: string;
}

export interface ConsoleDecisionPacket {
  taskId: string;
  failureClass: string;
  allowedActions: string[];
  blockedActions: string[];
  summary: string;
}

export interface ConsoleApplyStatus {
  state: ApplyState;
  canApply: boolean;
  dirtySourceCheckout: boolean;
  reason: string;
  checkpointRef: string;
}

export interface RealRunDetailResponse {
  run_id: string;
  status: string;
  trust_status: string;
  apply_status: string;
  total_events: number;
  last_event_type: string | null;
  safe_wave: string[];
  failures: Array<{ task_id: string; failure_class: string; count: number; recovery_action?: string }>;
  timeline: Array<{ sequence: number; phase: string; event_type: string; outcome: string; summary: string }>;
}

export interface RunDetailModel {
  header: {
    run_id: string;
    status: string;
    trust_status: string;
    apply_status: string;
    total_events: number;
    last_event_type: string | null;
  };
  safe_wave: string[];
  failures: RealRunDetailResponse["failures"];
  timeline: RealRunDetailResponse["timeline"];
  sections: Array<{
    id: "overview" | "safe-wave" | "timeline" | "trust-failure" | "apply-state";
    label: string;
  }>;
}

export interface ConsoleRun {
  runId: string;
  title: string;
  status: "completed" | "failed" | "blocked";
  trust: {
    verdict: TrustVerdict;
    score: number;
    reasons: string[];
  };
  tasks: ConsoleTask[];
  events: ConsoleEvent[];
  failures: ConsoleFailure[];
  decisionPackets: ConsoleDecisionPacket[];
  applyStatus: ConsoleApplyStatus;
}

export interface ConsoleSnapshot {
  generatedAt: string;
  runs: ConsoleRun[];
}

export interface ConsoleSection {
  id:
    | "run-list"
    | "run-detail"
    | "task-timeline"
    | "event-timeline"
    | "trust-report"
    | "failure-barriers"
    | "decision-packets"
    | "apply-status";
  label: string;
}

export interface ConsoleUiModel {
  generatedAt: string;
  runs: ConsoleRun[];
  selectedRun: ConsoleRun;
  eventFamilies: string[];
  sections: ConsoleSection[];
}

export const demoConsoleSnapshot: ConsoleSnapshot = {
  generatedAt: "2026-05-21T06:40:00Z",
  runs: [
    {
      runId: "run_demo_trusted",
      title: "Trusted local demo run",
      status: "completed",
      trust: {
        verdict: "trusted",
        score: 0.92,
        reasons: ["worker evidence passed", "verification gate passed"]
      },
      tasks: [
        {
          taskId: "task_plan",
          title: "Resolve execution profile",
          status: "MERGED",
          owner: "main",
          checkpoint: "ckpt_profile"
        },
        {
          taskId: "task_worker",
          title: "Run bounded worker",
          status: "MERGED",
          owner: "subagent",
          checkpoint: "ckpt_worker"
        }
      ],
      events: [
        event("run_demo_trusted", 1, "platform.run_started", "Waygent run opened."),
        event("run_demo_trusted", 2, "runway.safe_wave_selected", "Safe wave released."),
        event("run_demo_trusted", 3, "runway.worker_result", "Worker returned bounded evidence."),
        event("run_demo_trusted", 4, "lens.trust_report_updated", "Trust report marked run trusted.")
      ],
      failures: [],
      decisionPackets: [],
      applyStatus: {
        state: "ready",
        canApply: true,
        dirtySourceCheckout: false,
        reason: "accepted checkpoint is ready",
        checkpointRef: "ckpt_worker"
      }
    },
    {
      runId: "run_demo_failed",
      title: "Failed adapter demo run",
      status: "failed",
      trust: {
        verdict: "failed",
        score: 0.08,
        reasons: ["adapter crashed", "worker result artifact missing"]
      },
      tasks: [
        {
          taskId: "task_worker",
          title: "Run bounded worker",
          status: "FAILED_TERMINAL",
          owner: "subagent",
          checkpoint: "ckpt_profile"
        }
      ],
      events: [
        event("run_demo_failed", 1, "platform.run_started", "Waygent run opened."),
        event("run_demo_failed", 2, "runway.safe_wave_selected", "Safe wave released."),
        event("run_demo_failed", 3, "runway.failure_barrier", "Adapter crashed before result.", {
          outcome: "failed",
          severity: "error"
        }),
        event("run_demo_failed", 4, "lens.trust_report_updated", "Trust report marked run failed.", {
          outcome: "failed",
          severity: "error"
        })
      ],
      failures: [
        {
          taskId: "task_worker",
          failureClass: "adapter_crashed",
          recoveryAction: "switch_provider",
          summary: "Provider adapter exited before a typed worker result was sealed."
        }
      ],
      decisionPackets: [],
      applyStatus: {
        state: "not_ready",
        canApply: false,
        dirtySourceCheckout: false,
        reason: "no accepted checkpoint exists",
        checkpointRef: "ckpt_profile"
      }
    },
    {
      runId: "run_demo_blocked",
      title: "Blocked verification demo run",
      status: "blocked",
      trust: {
        verdict: "insufficient_evidence",
        score: 0.46,
        reasons: ["verification failed", "operator decision required"]
      },
      tasks: [
        {
          taskId: "task_worker",
          title: "Run bounded worker",
          status: "MERGED",
          owner: "subagent",
          checkpoint: "ckpt_worker"
        },
        {
          taskId: "task_verify",
          title: "Verify checkpoint",
          status: "AWAITING_HUMAN_DECISION",
          owner: "operator",
          checkpoint: "ckpt_worker"
        }
      ],
      events: [
        event("run_demo_blocked", 1, "platform.run_started", "Waygent run opened."),
        event("run_demo_blocked", 2, "runway.worker_result", "Worker returned bounded evidence."),
        event("run_demo_blocked", 3, "runway.decision_packet_created", "Verification needs operator decision.", {
          outcome: "blocked",
          severity: "warning"
        }),
        event("run_demo_blocked", 4, "lens.trust_report_updated", "Evidence is insufficient until decision.", {
          outcome: "blocked",
          severity: "warning"
        })
      ],
      failures: [
        {
          taskId: "task_verify",
          failureClass: "verification_failed",
          recoveryAction: "operator_decision",
          summary: "Verification failed and generated a recovery decision packet."
        }
      ],
      decisionPackets: [
        {
          taskId: "task_verify",
          failureClass: "verification_failed",
          allowedActions: ["rerun_verification", "update_plan"],
          blockedActions: ["apply_to_source"],
          summary: "Resolve verification before source apply."
        }
      ],
      applyStatus: {
        state: "blocked",
        canApply: false,
        dirtySourceCheckout: true,
        reason: "dirty_source_checkout",
        checkpointRef: "ckpt_worker"
      }
    }
  ]
};

export const consoleSections: ConsoleSection[] = [
  { id: "run-list", label: "Runs" },
  { id: "run-detail", label: "Run detail" },
  { id: "task-timeline", label: "Tasks" },
  { id: "event-timeline", label: "Events" },
  { id: "trust-report", label: "Trust" },
  { id: "failure-barriers", label: "Failures" },
  { id: "decision-packets", label: "Decisions" },
  { id: "apply-status", label: "Apply" }
];

function event(
  runId: string,
  sequence: number,
  eventType: string,
  summary: string,
  overrides: Partial<ConsoleEvent> = {}
): ConsoleEvent {
  return {
    eventId: `event_${runId}_${sequence}`,
    runId,
    eventType,
    sequence,
    outcome: "success",
    severity: "info",
    summary,
    ...overrides
  };
}

export function buildConsoleUiModel(
  snapshot: ConsoleSnapshot,
  selectedRunId?: string
): ConsoleUiModel {
  const firstRun = snapshot.runs[0];
  if (!firstRun) {
    throw new Error("console snapshot requires at least one run");
  }

  const selectedRun = snapshot.runs.find((run) => run.runId === selectedRunId) ?? firstRun;
  const eventFamilies = Array.from(
    new Set(selectedRun.events.map((item) => item.eventType.split(".")[0] ?? "unknown"))
  );

  return {
    generatedAt: snapshot.generatedAt,
    runs: snapshot.runs,
    selectedRun,
    eventFamilies,
    sections: consoleSections
  };
}

export function buildRunDetailModel(response: RealRunDetailResponse): RunDetailModel {
  return {
    header: {
      run_id: response.run_id,
      status: response.status,
      trust_status: response.trust_status,
      apply_status: response.apply_status,
      total_events: response.total_events,
      last_event_type: response.last_event_type
    },
    safe_wave: response.safe_wave,
    failures: response.failures,
    timeline: response.timeline,
    sections: [
      { id: "overview", label: "Overview" },
      { id: "safe-wave", label: "Safe wave" },
      { id: "timeline", label: "Timeline" },
      { id: "trust-failure", label: "Trust and failure" },
      { id: "apply-state", label: "Apply state" }
    ]
  };
}

export function consoleRunToRealDetail(run: ConsoleRun): RealRunDetailResponse {
  const lastEvent = run.events.at(-1);
  return {
    run_id: run.runId,
    status: run.status,
    trust_status: run.trust.verdict,
    apply_status: run.applyStatus.state,
    total_events: run.events.length,
    last_event_type: lastEvent?.eventType ?? null,
    safe_wave: run.tasks.map((task) => task.taskId),
    failures: run.failures.map((failure) => ({
      task_id: failure.taskId,
      failure_class: failure.failureClass,
      recovery_action: failure.recoveryAction,
      count: 1
    })),
    timeline: run.events.map((event) => ({
      sequence: event.sequence,
      phase: event.eventType.split(".")[0] ?? "unknown",
      event_type: event.eventType,
      outcome: event.outcome,
      summary: event.summary
    }))
  };
}

export function renderConsoleSnapshot(model: ConsoleUiModel): string {
  const run = model.selectedRun;
  const decisions = run.decisionPackets
    .map((packet) => `decision: ${packet.taskId} ${packet.failureClass}`)
    .join("\n");
  const allowed = run.decisionPackets
    .map((packet) => `allowed: ${packet.allowedActions.join(", ")}`)
    .join("\n");
  const failures = run.failures
    .map((failure) => `${failure.taskId} ${failure.failureClass} ${failure.recoveryAction}`)
    .join("\n");

  return [
    `run: ${run.runId}`,
    `trust: ${run.trust.verdict}`,
    `families: ${model.eventFamilies.join(", ")}`,
    failures,
    decisions,
    allowed,
    `apply: ${run.applyStatus.state} ${run.applyStatus.reason}`
  ]
    .filter(Boolean)
    .join("\n");
}
