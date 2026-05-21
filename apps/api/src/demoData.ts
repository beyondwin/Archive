export type RunStatus = "running" | "blocked" | "failed" | "completed" | "applied";
export type TrustVerdict = "trusted" | "failed" | "insufficient_evidence";
export type ApplyState = "ready" | "blocked" | "not_ready" | "applied";

export interface RunSummary {
  runId: string;
  title: string;
  status: RunStatus;
  startedAt: string;
  updatedAt: string;
  trustVerdict: TrustVerdict;
  applyStatus: ApplyState;
}

export interface RunEvent {
  eventId: string;
  runId: string;
  eventType: string;
  occurredAt: string;
  sequence: number;
  phase: string;
  outcome: "success" | "failed" | "blocked" | "running";
  severity: "info" | "warning" | "error";
  trustImpact: "supports_success" | "supports_failure" | "requires_review" | "neutral";
  summary: string;
  payload: Record<string, unknown>;
}

export interface TaskTimelineItem {
  taskId: string;
  title: string;
  status: string;
  owner: "main" | "subagent" | "kernel" | "operator";
  checkpoint: string;
  latestEventType: string;
}

export interface TrustReport {
  verdict: TrustVerdict;
  score: number;
  reasons: string[];
  evidenceRefs: string[];
  updatedAt: string;
}

export interface FailureBarrier {
  taskId: string;
  failureClass: string;
  severity: "warning" | "error";
  recoveryAction: string;
  evidenceRefs: string[];
  summary: string;
}

export interface DecisionPacket {
  taskId: string;
  failureClass: string;
  allowedActions: string[];
  blockedActions: string[];
  summary: string;
  evidenceRefs: string[];
}

export interface ApplyStatus {
  state: ApplyState;
  canApply: boolean;
  dirtySourceCheckout: boolean;
  reason: string;
  checkpointRef: string;
}

export interface RunDetail {
  run: RunSummary;
  tasks: TaskTimelineItem[];
  events: RunEvent[];
  trust: TrustReport;
  failures: FailureBarrier[];
  decisionPackets: DecisionPacket[];
  applyStatus: ApplyStatus;
}

const now = "2026-05-21T06:40:00Z";

const baseTasks: TaskTimelineItem[] = [
  {
    taskId: "task_plan",
    title: "Resolve execution profile",
    status: "MERGED",
    owner: "main",
    checkpoint: "ckpt_profile",
    latestEventType: "runway.safe_wave_selected"
  },
  {
    taskId: "task_worker",
    title: "Run bounded worker",
    status: "MERGED",
    owner: "subagent",
    checkpoint: "ckpt_worker",
    latestEventType: "runway.worker_result"
  }
];

function event(
  runId: string,
  sequence: number,
  eventType: string,
  summary: string,
  overrides: Partial<RunEvent> = {}
): RunEvent {
  return {
    eventId: `event_${runId}_${sequence}`,
    runId,
    eventType,
    occurredAt: `2026-05-21T06:4${sequence}:00Z`,
    sequence,
    phase: eventType.split(".")[0] ?? "platform",
    outcome: "success",
    severity: "info",
    trustImpact: "neutral",
    summary,
    payload: {},
    ...overrides
  };
}

export const demoRunDetails: RunDetail[] = [
  {
    run: {
      runId: "run_demo_trusted",
      title: "Trusted local demo run",
      status: "completed",
      startedAt: "2026-05-21T06:40:00Z",
      updatedAt: now,
      trustVerdict: "trusted",
      applyStatus: "ready"
    },
    tasks: baseTasks,
    events: [
      event("run_demo_trusted", 1, "platform.run_started", "Waygent run opened."),
      event("run_demo_trusted", 2, "runway.safe_wave_selected", "Safe wave released.", {
        payload: { safeWave: ["task_worker"] }
      }),
      event("run_demo_trusted", 3, "runway.worker_result", "Worker returned bounded evidence.", {
        payload: { taskId: "task_worker" },
        trustImpact: "supports_success"
      }),
      event("run_demo_trusted", 4, "lens.trust_report_updated", "Trust report marked run trusted.", {
        trustImpact: "supports_success"
      })
    ],
    trust: {
      verdict: "trusted",
      score: 0.92,
      reasons: ["worker evidence passed", "verification gate passed"],
      evidenceRefs: ["artifact://trust/run_demo_trusted"],
      updatedAt: now
    },
    failures: [],
    decisionPackets: [],
    applyStatus: {
      state: "ready",
      canApply: true,
      dirtySourceCheckout: false,
      reason: "accepted checkpoint is ready for explicit source apply",
      checkpointRef: "ckpt_worker"
    }
  },
  {
    run: {
      runId: "run_demo_failed",
      title: "Failed adapter demo run",
      status: "failed",
      startedAt: "2026-05-21T06:40:00Z",
      updatedAt: now,
      trustVerdict: "failed",
      applyStatus: "not_ready"
    },
    tasks: [
      baseTasks[0]!,
      {
        taskId: "task_worker",
        title: "Run bounded worker",
        status: "FAILED_TERMINAL",
        owner: "subagent",
        checkpoint: "ckpt_profile",
        latestEventType: "runway.failure_barrier"
      }
    ],
    events: [
      event("run_demo_failed", 1, "platform.run_started", "Waygent run opened."),
      event("run_demo_failed", 2, "runway.safe_wave_selected", "Safe wave released."),
      event("run_demo_failed", 3, "runway.failure_barrier", "Adapter crashed before result.", {
        outcome: "failed",
        severity: "error",
        trustImpact: "supports_failure",
        payload: { taskId: "task_worker", failureClass: "adapter_crashed" }
      }),
      event("run_demo_failed", 4, "lens.trust_report_updated", "Trust report marked run failed.", {
        outcome: "failed",
        severity: "error",
        trustImpact: "supports_failure"
      })
    ],
    trust: {
      verdict: "failed",
      score: 0.08,
      reasons: ["adapter crashed", "worker result artifact missing"],
      evidenceRefs: ["artifact://failure/run_demo_failed"],
      updatedAt: now
    },
    failures: [
      {
        taskId: "task_worker",
        failureClass: "adapter_crashed",
        severity: "error",
        recoveryAction: "switch_provider",
        evidenceRefs: ["event_run_demo_failed_3"],
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
    run: {
      runId: "run_demo_blocked",
      title: "Blocked verification demo run",
      status: "blocked",
      startedAt: "2026-05-21T06:40:00Z",
      updatedAt: now,
      trustVerdict: "insufficient_evidence",
      applyStatus: "blocked"
    },
    tasks: [
      ...baseTasks,
      {
        taskId: "task_verify",
        title: "Verify checkpoint",
        status: "AWAITING_HUMAN_DECISION",
        owner: "operator",
        checkpoint: "ckpt_worker",
        latestEventType: "runway.decision_packet_created"
      }
    ],
    events: [
      event("run_demo_blocked", 1, "platform.run_started", "Waygent run opened."),
      event("run_demo_blocked", 2, "runway.worker_result", "Worker returned bounded evidence.", {
        payload: { taskId: "task_worker" },
        trustImpact: "supports_success"
      }),
      event("run_demo_blocked", 3, "runway.decision_packet_created", "Verification needs operator decision.", {
        outcome: "blocked",
        severity: "warning",
        trustImpact: "requires_review",
        payload: { taskId: "task_verify", failureClass: "verification_failed" }
      }),
      event("run_demo_blocked", 4, "lens.trust_report_updated", "Evidence is insufficient until decision.")
    ],
    trust: {
      verdict: "insufficient_evidence",
      score: 0.46,
      reasons: ["verification failed", "operator decision required"],
      evidenceRefs: ["artifact://decision/run_demo_blocked"],
      updatedAt: now
    },
    failures: [
      {
        taskId: "task_verify",
        failureClass: "verification_failed",
        severity: "warning",
        recoveryAction: "operator_decision",
        evidenceRefs: ["event_run_demo_blocked_3"],
        summary: "Verification failed and generated a recovery decision packet."
      }
    ],
    decisionPackets: [
      {
        taskId: "task_verify",
        failureClass: "verification_failed",
        allowedActions: ["rerun_verification", "update_plan"],
        blockedActions: ["apply_to_source"],
        summary: "Resolve verification before source apply.",
        evidenceRefs: ["event_run_demo_blocked_3"]
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
];

export function listRuns(): RunSummary[] {
  return demoRunDetails.map((detail) => detail.run);
}

export function findRun(runId: string): RunDetail | undefined {
  return demoRunDetails.find((detail) => detail.run.runId === runId);
}
