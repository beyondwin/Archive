import type {
  DogfoodEvidenceProjection,
  ExecutionExplanationProjection,
  OperationalMaturityProjection,
  OperatorDecisionProjection,
  OperatorIntakeRecoverySummary,
  OperatorTimelineRow,
  ProviderLogSummary,
  ProviderReadinessProjection,
  RuntimeCostProjection
} from "@waygent/contracts";

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
  checkpointRefs: string[];
  combinedPatchRef: string | null;
}

export type RunDetailSectionId =
  | "overview"
  | "operator-decision"
  | "intake-recovery"
  | "operator-timeline"
  | "ai-handoff"
  | "raw-evidence"
  | "operational-maturity"
  | "safe-wave"
  | "execution-intelligence"
  | "timeline"
  | "trust-failure"
  | "apply-state"
  | "provider-attempts"
  | "verification-evidence"
  | "review-findings"
  | "recovery-decisions"
  | "drift";

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
  task_packets?: Array<Record<string, unknown>>;
  provider_attempts?: Array<Record<string, unknown>>;
  verification?: Array<Record<string, unknown>>;
  reviews?: Array<Record<string, unknown>>;
  recovery?: Array<Record<string, unknown>>;
  decision_packets?: Array<Record<string, unknown>>;
  drift?: { last_checked_at: string | null; records: Array<Record<string, unknown>>; unrepaired_blockers: Array<Record<string, unknown>> } | null;
  execution_explanation?: ExecutionExplanationProjection | null;
  operational_maturity?: OperationalMaturityProjection | null;
  dogfood_evidence?: DogfoodEvidenceProjection | null;
  runtime_cost?: RuntimeCostProjection | null;
  provider_readiness?: ProviderReadinessProjection | null;
  operator_decision?: OperatorDecisionProjection | null;
  apply_readiness?: {
    status: ApplyState;
    reason: string | null;
    checkpoint_refs: string[];
    combined_patch_ref: string | null;
    source: "run_state_v2" | "events";
  } | null;
  events?: Array<{
    event_id?: string;
    eventId?: string;
    agentlens_run_id?: string;
    runId?: string;
    event_type?: string;
    eventType?: string;
    sequence?: number;
    outcome?: ConsoleEvent["outcome"];
    severity?: ConsoleEvent["severity"];
    summary?: string;
  }>;
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
  task_packets: NonNullable<RealRunDetailResponse["task_packets"]>;
  provider_attempts: NonNullable<RealRunDetailResponse["provider_attempts"]>;
  verification: NonNullable<RealRunDetailResponse["verification"]>;
  reviews: NonNullable<RealRunDetailResponse["reviews"]>;
  recovery: NonNullable<RealRunDetailResponse["recovery"]>;
  decision_packets: NonNullable<RealRunDetailResponse["decision_packets"]>;
  drift: RealRunDetailResponse["drift"];
  execution_explanation: ExecutionExplanationProjection | null;
  operational_maturity: OperationalMaturityProjection | null;
  dogfood_evidence: DogfoodEvidenceProjection | null;
  runtime_cost: RuntimeCostProjection | null;
  provider_readiness: ProviderReadinessProjection | null;
  operator_decision: OperatorDecisionProjection | null;
  intake_recovery: OperatorIntakeRecoverySummary | null;
  outcome_strip: {
    display_status: string;
    primary_blocker: string | null;
    next_action: string | null;
    apply_status: string;
    confidence: string;
    summary: string;
    intake_status: string | null;
    intake_question: string | null;
  };
  operator_timeline: OperatorTimelineRow[];
  raw_evidence_refs: string[];
  provider_log_summary: ProviderLogSummary | null;
  next_action: string | null;
  apply_readiness: RealRunDetailResponse["apply_readiness"];
  sections: Array<{
    id: RunDetailSectionId;
    label: string;
  }>;
}

export interface RealRunSummaryResponse {
  run_id: string;
  status: string;
  trust_status: string;
  apply_status: string;
  total_events: number;
  last_event_type: string | null;
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
        checkpointRef: "ckpt_worker",
        checkpointRefs: ["ckpt_worker"],
        combinedPatchRef: null
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
        checkpointRef: "ckpt_profile",
        checkpointRefs: ["ckpt_profile"],
        combinedPatchRef: null
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
        checkpointRef: "ckpt_worker",
        checkpointRefs: ["ckpt_worker"],
        combinedPatchRef: null
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
  const runs = [...snapshot.runs].sort(compareRunsByOperatorUrgency);
  const firstRun = runs[0];
  if (!firstRun) {
    throw new Error("console snapshot requires at least one run");
  }

  const selectedRun = runs.find((run) => run.runId === selectedRunId) ?? firstRun;
  const eventFamilies = Array.from(
    new Set(selectedRun.events.map((item) => item.eventType.split(".")[0] ?? "unknown"))
  );

  return {
    generatedAt: snapshot.generatedAt,
    runs,
    selectedRun,
    eventFamilies,
    sections: consoleSections
  };
}

export function buildRunDetailModel(response: RealRunDetailResponse): RunDetailModel {
  const operatorDecision = response.operator_decision ?? null;
  const outcomeStrip = outcomeStripFromDecision(response);

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
    task_packets: response.task_packets ?? [],
    provider_attempts: response.provider_attempts ?? [],
    verification: response.verification ?? [],
    reviews: response.reviews ?? [],
    recovery: response.recovery ?? [],
    decision_packets: response.decision_packets ?? [],
    drift: response.drift ?? null,
    execution_explanation: response.execution_explanation ?? null,
    operational_maturity: response.operational_maturity ?? null,
    dogfood_evidence: response.dogfood_evidence ?? response.operational_maturity?.dogfood_evidence ?? null,
    runtime_cost: response.runtime_cost ?? response.operational_maturity?.runtime_cost ?? null,
    provider_readiness: response.provider_readiness ?? response.operational_maturity?.provider_readiness ?? null,
    operator_decision: operatorDecision,
    intake_recovery: operatorDecision?.intake_recovery ?? null,
    outcome_strip: outcomeStrip,
    operator_timeline: operatorTimelineFromResponse(response),
    raw_evidence_refs: rawEvidenceRefsFromDecision(operatorDecision),
    provider_log_summary: providerLogSummaryFromAttempts(response.provider_attempts ?? []),
    next_action: response.operational_maturity?.next_action ?? response.execution_explanation?.recommended_next_actions[0] ?? null,
    apply_readiness: response.apply_readiness ?? null,
    sections: detailSectionsFor(operatorDecision)
  };
}

function outcomeStripFromDecision(response: RealRunDetailResponse): RunDetailModel["outcome_strip"] {
  const decision = response.operator_decision ?? null;
  const fallbackSummary = response.timeline.at(-1)?.summary ?? response.last_event_type ?? response.status;
  const intakeRecovery = decision?.intake_recovery ?? null;

  return {
    display_status: decision?.status_summary.display_status ?? response.status,
    primary_blocker: decision?.primary_blocker?.code ?? null,
    next_action: decision?.allowed_actions[0]?.id
      ?? response.operational_maturity?.next_action
      ?? response.execution_explanation?.recommended_next_actions[0]
      ?? null,
    apply_status: decision?.status_summary.apply_status ?? response.apply_status,
    confidence: decision?.confidence ?? "unknown",
    summary: decision?.status_summary.summary ?? fallbackSummary,
    intake_status: intakeRecovery?.status ?? null,
    intake_question: intakeRecovery?.question ?? null
  };
}

function operatorTimelineFromResponse(response: RealRunDetailResponse): OperatorTimelineRow[] {
  return response.timeline.map((item) => ({
    id: `timeline_${response.run_id}_${item.sequence}`,
    sequence: item.sequence,
    timestamp: null,
    actor: item.phase || item.event_type.split(".")[0] || "unknown",
    row_type: operatorTimelineRowType(item.event_type),
    title: item.summary || item.event_type,
    outcome: operatorTimelineOutcome(item.outcome),
    severity: operatorTimelineSeverity(item.outcome),
    task_id: null,
    evidence_refs: [],
    metadata: {
      phase: item.phase,
      event_type: item.event_type,
      summary: item.summary
    }
  }));
}

function operatorTimelineRowType(eventType: string): OperatorTimelineRow["row_type"] {
  if (eventType.includes("safe_wave")) return "safe_wave";
  if (eventType.includes("task_packet")) return "task_packet";
  if (eventType.includes("provider")) return "provider_attempt";
  if (eventType.includes("worker_result")) return "worker_result";
  if (eventType.includes("verification")) return "verification_result";
  if (eventType.includes("checkpoint") || eventType.includes("dry_run")) return "checkpoint";
  if (eventType.includes("review")) return "review_finding";
  if (eventType.includes("recovery") || eventType.includes("decision_packet")) return "recovery_decision";
  if (eventType.includes("apply")) return "apply_readiness";
  if (eventType.includes("artifact")) return "artifact_health";
  if (eventType.includes("readiness")) return "provider_readiness";
  return "raw_event";
}

function operatorTimelineOutcome(value: string): OperatorTimelineRow["outcome"] {
  if (value === "success" || value === "failed" || value === "blocked" || value === "cancelled" || value === "running") return value;
  return "unknown";
}

function operatorTimelineSeverity(value: string): OperatorTimelineRow["severity"] {
  if (value === "failed") return "error";
  if (value === "blocked" || value === "cancelled") return "warning";
  return "info";
}

function rawEvidenceRefsFromDecision(decision: OperatorDecisionProjection | null): string[] {
  if (!decision) return [];
  return uniqueStrings([
    ...decision.evidence_packet.state_refs,
    ...decision.evidence_packet.event_refs
  ]);
}

function detailSectionsFor(operatorDecision: OperatorDecisionProjection | null): RunDetailModel["sections"] {
  const sections: RunDetailModel["sections"] = [
    { id: "overview", label: "Overview" },
    { id: "operational-maturity", label: "Operational maturity" },
    { id: "safe-wave", label: "Safe wave" },
    { id: "execution-intelligence", label: "Execution intelligence" },
    { id: "timeline", label: "Timeline" },
    { id: "trust-failure", label: "Trust and failure" },
    { id: "apply-state", label: "Apply state" },
    { id: "provider-attempts", label: "Provider attempts" },
    { id: "verification-evidence", label: "Verification evidence" },
    { id: "review-findings", label: "Review findings" },
    { id: "recovery-decisions", label: "Recovery decisions" },
    { id: "drift", label: "Drift" }
  ];

  if (!operatorDecision) return sections;

  const intakeSection: RunDetailModel["sections"] = operatorDecision.intake_recovery
    ? [{ id: "intake-recovery", label: "Intake recovery" }]
    : [];

  return [
    sections[0]!,
    { id: "operator-decision", label: "Operator decision" },
    ...intakeSection,
    { id: "operator-timeline", label: "Operator timeline" },
    { id: "ai-handoff", label: "AI handoff" },
    { id: "raw-evidence", label: "Raw evidence" },
    ...sections.slice(1)
  ];
}

function compareRunsByOperatorUrgency(left: ConsoleRun, right: ConsoleRun): number {
  const priority = operatorUrgencyPriority(left) - operatorUrgencyPriority(right);
  if (priority !== 0) return priority;
  return left.runId.localeCompare(right.runId);
}

function operatorUrgencyPriority(run: ConsoleRun): number {
  if (run.status === "blocked") return 0;
  if (run.status === "failed") return 1;
  return 2;
}

export function realRunSummaryToConsoleRun(summary: RealRunSummaryResponse): ConsoleRun {
  return {
    runId: summary.run_id,
    title: summary.run_id,
    status: consoleStatus(summary.status),
    trust: {
      verdict: trustVerdict(summary.trust_status),
      score: trustScore(summary.trust_status),
      reasons: [`trust status: ${summary.trust_status}`]
    },
    tasks: [],
    events: summary.last_event_type
      ? [event(summary.run_id, 1, summary.last_event_type, "Latest API event.")]
      : [],
    failures: [],
    decisionPackets: [],
    applyStatus: {
      state: applyState(summary.apply_status),
      canApply: summary.apply_status === "ready",
      dirtySourceCheckout: false,
      reason: summary.apply_status,
      checkpointRef: "",
      checkpointRefs: [],
      combinedPatchRef: null
    }
  };
}

export function realRunDetailToConsoleRun(response: RealRunDetailResponse): ConsoleRun {
  const detail = buildRunDetailModel(response);
  const applyReadiness = detail.apply_readiness;
  const readinessStatus = applyState(applyReadiness?.status ?? response.apply_status);
  const readinessCheckpointRefs = applyReadiness?.checkpoint_refs ?? [];
  const taskIds = Array.from(new Set([
    ...detail.safe_wave,
    ...detail.task_packets.map((packet) => stringValue(packet.task_id)).filter(Boolean),
    ...detail.provider_attempts.map((attempt) => stringValue(attempt.task_id)).filter(Boolean),
    ...detail.verification.map((verification) => stringValue(verification.task_id)).filter(Boolean)
  ]));

  return {
    runId: response.run_id,
    title: response.run_id,
    status: consoleStatus(response.status),
    trust: {
      verdict: trustVerdict(response.trust_status),
      score: trustScore(response.trust_status),
      reasons: [`trust status: ${response.trust_status}`]
    },
    tasks: taskIds.map((taskId) => ({
      taskId,
      title: taskTitle(detail.task_packets, taskId),
      status: taskStatus(detail.task_packets, taskId, response.status),
      owner: providerOwner(detail.provider_attempts, taskId),
      checkpoint: checkpointRef(detail.task_packets, taskId)
    })),
    events: eventsFromRealDetail(response),
    failures: response.failures.map((failure) => ({
      taskId: failure.task_id,
      failureClass: failure.failure_class,
      recoveryAction: failure.recovery_action ?? "inspect_run",
      summary: `${failure.failure_class} occurred ${failure.count} time${failure.count === 1 ? "" : "s"}.`
    })),
    decisionPackets: [
      ...detail.recovery.map((record) => ({
        taskId: stringValue(record.task_id) || "run",
        failureClass: stringValue(record.failure_class) || "recovery_required",
        allowedActions: stringArray(record.allowed_actions),
        blockedActions: stringArray(record.blocked_actions),
        summary: stringValue(record.recommended_next_action) || "Recovery decision is required."
      })),
      ...detail.decision_packets.map((packet) => ({
        taskId: stringValue(packet.task_id) || "run",
        failureClass: stringValue(packet.failure_class) || "decision_required",
        allowedActions: [],
        blockedActions: [],
        summary: stringValue(packet.decision_packet_ref) || "Decision packet is available."
      }))
    ],
    applyStatus: {
      state: readinessStatus,
      canApply: readinessStatus === "ready",
      dirtySourceCheckout: hasDirtySourceBlock(detail),
      reason: applyReadiness?.reason ?? response.apply_status,
      checkpointRef: readinessCheckpointRefs.join(", "),
      checkpointRefs: readinessCheckpointRefs,
      combinedPatchRef: applyReadiness?.combined_patch_ref ?? null
    }
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
    })),
    apply_readiness: {
      status: run.applyStatus.state,
      reason: run.applyStatus.reason,
      checkpoint_refs: run.applyStatus.checkpointRefs,
      combined_patch_ref: run.applyStatus.combinedPatchRef,
      source: "events"
    }
  };
}

function eventsFromRealDetail(response: RealRunDetailResponse): ConsoleEvent[] {
  if (response.events && response.events.length > 0) {
    return response.events.map((item, index) => ({
      eventId: item.event_id ?? item.eventId ?? `event_${response.run_id}_${index + 1}`,
      runId: item.agentlens_run_id ?? item.runId ?? response.run_id,
      eventType: item.event_type ?? item.eventType ?? "unknown.event",
      sequence: item.sequence ?? index + 1,
      outcome: item.outcome ?? "success",
      severity: item.severity ?? "info",
      summary: item.summary ?? ""
    }));
  }

  return response.timeline.map((item) => ({
    eventId: `event_${response.run_id}_${item.sequence}`,
    runId: response.run_id,
    eventType: item.event_type,
    sequence: item.sequence,
    outcome: consoleOutcome(item.outcome),
    severity: item.outcome === "failed" ? "error" : item.outcome === "blocked" ? "warning" : "info",
    summary: item.summary
  }));
}

function consoleStatus(status: string): ConsoleRun["status"] {
  if (status === "failed") return "failed";
  if (status === "blocked") return "blocked";
  return "completed";
}

function trustVerdict(value: string): TrustVerdict {
  if (value === "trusted" || value === "failed" || value === "insufficient_evidence") return value;
  return "insufficient_evidence";
}

function trustScore(value: string): number {
  if (value === "trusted") return 0.9;
  if (value === "failed") return 0.1;
  return 0.45;
}

function applyState(value: string | undefined): ApplyState {
  if (value === "ready" || value === "blocked" || value === "not_ready" || value === "applied") return value;
  if (value === "not_applied") return "not_ready";
  return "not_ready";
}

function consoleOutcome(value: string): ConsoleEvent["outcome"] {
  if (value === "success" || value === "failed" || value === "blocked" || value === "running") return value;
  return "success";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function uniqueStrings(items: string[]): string[] {
  return Array.from(new Set(items));
}

function taskTitle(taskPackets: Array<Record<string, unknown>>, taskId: string): string {
  const packet = taskPackets.find((item) => item.task_id === taskId);
  const manifest = packet?.unit_manifest;
  if (manifest && typeof manifest === "object") {
    const title = (manifest as Record<string, unknown>).title;
    if (typeof title === "string") return title;
  }
  return taskId;
}

function taskStatus(taskPackets: Array<Record<string, unknown>>, taskId: string, fallback: string): string {
  const packet = taskPackets.find((item) => item.task_id === taskId);
  return stringValue(packet?.status) || fallback;
}

function providerOwner(providerAttempts: Array<Record<string, unknown>>, taskId: string): string {
  const attempt = providerAttempts.find((item) => item.task_id === taskId);
  return stringValue(attempt?.provider) || "waygent";
}

function checkpointRef(taskPackets: Array<Record<string, unknown>>, taskId: string): string {
  const packet = taskPackets.find((item) => item.task_id === taskId);
  const checkpointRefs = packet?.checkpoint_refs;
  return Array.isArray(checkpointRefs) ? checkpointRefs.map(String).join(", ") : "";
}

function hasDirtySourceBlock(detail: RunDetailModel): boolean {
  return detail.recovery.some((record) => record.failure_class === "dirty_source_checkout")
    || detail.drift?.unrepaired_blockers.some((record) => record.failure_class === "dirty_source_checkout") === true;
}

function providerLogSummaryFromAttempts(attempts: Array<Record<string, unknown>>): ProviderLogSummary | null {
  for (const attempt of attempts) {
    const process = attempt.process;
    if (!process || typeof process !== "object") continue;
    const summary = (process as Record<string, unknown>).stderr_summary;
    if (isProviderLogSummary(summary)) return summary;
  }
  return null;
}

function isProviderLogSummary(value: unknown): value is ProviderLogSummary {
  if (!value || typeof value !== "object") return false;
  const summary = value as Partial<ProviderLogSummary>;
  const counts = summary.counts;
  return typeof summary.total_lines === "number"
    && counts !== undefined
    && typeof counts.error === "number"
    && typeof counts.warning === "number"
    && typeof counts.mcp === "number"
    && typeof counts.plugin_manifest === "number"
    && typeof counts.skill_loader === "number"
    && typeof counts.other === "number"
    && Array.isArray(summary.samples);
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
