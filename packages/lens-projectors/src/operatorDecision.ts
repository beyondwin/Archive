import type {
  AgentLensEvent,
  ApplyReadinessProjection,
  OperatorActionId,
  OperatorAllowedAction,
  OperatorAiHandoff,
  OperatorBlockedAction,
  OperatorBlocker,
  OperatorDecisionConfidence,
  OperatorDecisionProjection,
  OperatorEvidencePacket,
  OperatorRunStatus,
  OperatorStatusSummary,
  WaygentRunStateV2
} from "@waygent/contracts";
import { projectApplyReadinessFromState } from "./apply";
import { projectOperationalMaturityFromState } from "./operationalMaturity";

type StateError =
  | { status: "missing"; reason: "missing_run_state_v2" | string }
  | { status: "unsupported"; reason: "unsupported_run_state" | string; schema?: unknown }
  | { status: "invalid"; reason: "invalid_run_state_v2" | string; error?: string };

export interface OperatorDecisionInput {
  state?: WaygentRunStateV2 | null;
  events: AgentLensEvent[];
  run_id?: string;
  state_error?: StateError | null;
}

type ActionDefinition = {
  label: string;
  defaultReason: string;
  command: (runId: string) => string | null;
  requiresApproval: boolean;
  requiresRuntimeRevalidation: boolean;
};

const projectionRefs = [
  "waygent.apply_readiness",
  "waygent.execution_explanation.v1",
  "waygent.operational_maturity.v1"
] as const;

const actionDefinitions: Record<OperatorActionId, ActionDefinition> = {
  inspect_run: {
    label: "Inspect run",
    defaultReason: "Inspection is always safe.",
    command: (runId) => `waygent inspect --run ${runId}`,
    requiresApproval: false,
    requiresRuntimeRevalidation: false
  },
  explain_run: {
    label: "Explain run",
    defaultReason: "Explanation reads projected evidence without mutating runtime state.",
    command: (runId) => `waygent explain --run ${runId}`,
    requiresApproval: false,
    requiresRuntimeRevalidation: false
  },
  open_raw_evidence: {
    label: "Open raw evidence",
    defaultReason: "Raw evidence is available as a read-only fallback.",
    command: nullCommand,
    requiresApproval: false,
    requiresRuntimeRevalidation: false
  },
  open_ai_repair_handoff: {
    label: "Open AI repair handoff",
    defaultReason: "AI can draft a repair plan from bounded evidence.",
    command: nullCommand,
    requiresApproval: false,
    requiresRuntimeRevalidation: false
  },
  request_user_input: {
    label: "Request user input",
    defaultReason: "The run is waiting for operator input.",
    command: nullCommand,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  },
  approve_recovery: {
    label: "Approve recovery",
    defaultReason: "Recovery requires explicit operator approval.",
    command: nullCommand,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  },
  resume_run: {
    label: "Resume run",
    defaultReason: "The runtime must revalidate state before resuming.",
    command: (runId) => `waygent resume --run ${runId}`,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  },
  regenerate_checkpoint: {
    label: "Regenerate checkpoint",
    defaultReason: "Regenerate checkpoint evidence from the current source basis.",
    command: nullCommand,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  },
  rebase_checkpoint: {
    label: "Rebase checkpoint",
    defaultReason: "Rebase checkpoint evidence against the current source basis.",
    command: nullCommand,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  },
  rerun_verification: {
    label: "Rerun verification",
    defaultReason: "Verification failed and can be rerun after inspection or repair.",
    command: (runId) => `waygent verify --run ${runId}`,
    requiresApproval: false,
    requiresRuntimeRevalidation: true
  },
  review_patch: {
    label: "Review patch",
    defaultReason: "Patch evidence is available for review before apply.",
    command: nullCommand,
    requiresApproval: false,
    requiresRuntimeRevalidation: false
  },
  apply_run: {
    label: "Apply run",
    defaultReason: "Apply readiness is ready; the runtime must still revalidate before applying.",
    command: (runId) => `waygent apply --run ${runId}`,
    requiresApproval: true,
    requiresRuntimeRevalidation: true
  }
};

const blockerPriority: Record<string, number> = {
  state_missing: 10,
  state_invalid: 10,
  checkpoint_digest_mismatch: 20,
  unsafe_apply: 20,
  runtime_active: 30,
  needs_user_input: 40,
  needs_approval: 40,
  verification_failed: 50,
  checkpoint_dry_run_failed: 60,
  needs_rebase: 60,
  checkpoint_missing: 70,
  artifact_missing: 70,
  evidence_incomplete: 80,
  provider_not_ready: 90,
  apply_blocked: 100,
  unknown_failure: 110
};

export function projectOperatorDecisionFromState(input: OperatorDecisionInput): OperatorDecisionProjection {
  const runId = runIdFromInput(input);
  const generatedAt = generatedAtFromInput(input);

  if (!input.state) {
    return missingStateProjection(input, runId, generatedAt);
  }

  const state = input.state;
  let applyReadiness: ApplyReadinessProjection;
  try {
    applyReadiness = projectApplyReadinessFromState(state);
  } catch (error) {
    return invalidStateProjection(input, runId, generatedAt, error);
  }

  const evidencePacket = evidencePacketFromState(state, input.events, applyReadiness);
  const blockers = blockersFromState(state, input.events, applyReadiness, evidencePacket);
  const sortedBlockers = [...blockers].sort((left, right) => priority(left) - priority(right));
  const primaryBlocker = sortedBlockers[0] ?? null;
  const secondaryBlockers = primaryBlocker ? sortedBlockers.slice(1) : sortedBlockers;
  const displayStatus = displayStatusFromState(state, applyReadiness, primaryBlocker);
  const allowedActions = allowedActionsFor({ runId, state, applyReadiness, primaryBlocker, evidencePacket });
  const blockedActions = blockedActionsFor({ applyReadiness, primaryBlocker, evidencePacket, allowedActions });
  const confidence = confidenceFor(input.state, primaryBlocker, evidencePacket);
  const unknownReasons = unknownReasonsFor(confidence, primaryBlocker, evidencePacket);
  const statusSummary = statusSummaryFromState(state, displayStatus, applyReadiness, primaryBlocker);
  const aiHandoff = aiHandoffFromDecision({
    runId,
    displayStatus,
    primaryBlocker,
    secondaryBlockers,
    allowedActions,
    blockedActions,
    evidencePacket
  });

  return {
    schema: "waygent.operator_decision.v1",
    run_id: runId,
    generated_at: generatedAt,
    status_summary: statusSummary,
    primary_blocker: primaryBlocker,
    secondary_blockers: secondaryBlockers,
    allowed_actions: allowedActions,
    blocked_actions: blockedActions,
    evidence_packet: evidencePacket,
    ai_handoff: aiHandoff,
    confidence,
    unknown_reasons: unknownReasons,
    source_projection_refs: {
      run_state_v2: stateRef(state),
      apply_readiness: "waygent.apply_readiness",
      execution_explanation: "waygent.execution_explanation.v1",
      operational_maturity: "waygent.operational_maturity.v1"
    }
  };
}

function missingStateProjection(
  input: OperatorDecisionInput,
  runId: string,
  generatedAt: string
): OperatorDecisionProjection {
  const status = input.state_error?.status ?? "missing";
  const code = status === "missing" ? "state_missing" : "state_invalid";
  const blocker = makeBlocker({
    code,
    title: status === "missing" ? "Run state is missing" : "Run state is unavailable",
    summary: input.state_error?.reason ?? "waygent.run_state.v2 is unavailable.",
    severity: "critical",
    evidenceRefs: eventRefs(input.events),
    missingRefs: ["run_state_v2"],
    recommendedActionIds: ["inspect_run", "open_raw_evidence"]
  });
  const evidencePacket = evidencePacketForMissingState(input.events);
  const allowedActions = ["inspect_run", "open_raw_evidence"].map((id) =>
    allowedAction(id as OperatorActionId, runId, evidencePacket.event_refs)
  );
  const blockedActions = [
    blockedAction(
      "apply_run",
      "Apply is blocked because waygent.run_state.v2 is unavailable.",
      evidencePacket.event_refs,
      "A valid run_state.v2 is available and apply readiness passes."
    )
  ];

  return {
    schema: "waygent.operator_decision.v1",
    run_id: runId,
    generated_at: generatedAt,
    status_summary: {
      display_status: "blocked",
      runtime_status: status === "missing" ? "missing" : status === "unsupported" ? "unsupported" : "invalid",
      lifecycle_outcome: null,
      current_phase: null,
      active_tasks: 0,
      completed_tasks: 0,
      blocked_tasks: 0,
      apply_status: "unknown",
      summary: `${runId} cannot be classified because run_state.v2 is ${status}.`
    },
    primary_blocker: blocker,
    secondary_blockers: [],
    allowed_actions: allowedActions,
    blocked_actions: blockedActions,
    evidence_packet: evidencePacket,
    ai_handoff: aiHandoffFromDecision({
      runId,
      displayStatus: "blocked",
      primaryBlocker: blocker,
      secondaryBlockers: [],
      allowedActions,
      blockedActions,
      evidencePacket
    }),
    confidence: "unknown",
    unknown_reasons: [input.state_error?.reason ?? "missing_run_state_v2"],
    source_projection_refs: {
      run_state_v2: null,
      apply_readiness: null,
      execution_explanation: null,
      operational_maturity: null
    }
  };
}

function invalidStateProjection(
  input: OperatorDecisionInput,
  runId: string,
  generatedAt: string,
  error: unknown
): OperatorDecisionProjection {
  return missingStateProjection({
    ...input,
    state: null,
    state_error: {
      status: "invalid",
      reason: "invalid_run_state_v2",
      error: error instanceof Error ? error.message : String(error)
    }
  }, runId, generatedAt);
}

function evidencePacketFromState(
  state: WaygentRunStateV2,
  events: AgentLensEvent[],
  applyReadiness: ApplyReadinessProjection
): OperatorEvidencePacket {
  const verificationRefs = verificationRefsFromState(state);
  const checkpointRefs = unique([...checkpointRefsFromTasks(state), ...applyReadiness.checkpoint_refs]);
  const artifactRefs = artifactRefsFromState(state, applyReadiness);
  const missingRefs = missingRefsFromState(state, checkpointRefs);

  return {
    state_refs: [stateRef(state)],
    event_refs: eventRefs(events),
    artifact_refs: artifactRefs,
    verification_refs: verificationRefs,
    checkpoint_refs: checkpointRefs,
    projection_refs: [...projectionRefs],
    missing_refs: missingRefs,
    redaction_notes: []
  };
}

function evidencePacketForMissingState(events: AgentLensEvent[]): OperatorEvidencePacket {
  return {
    state_refs: [],
    event_refs: eventRefs(events),
    artifact_refs: artifactRefsFromEvents(events),
    verification_refs: [],
    checkpoint_refs: [],
    projection_refs: [],
    missing_refs: ["run_state_v2"],
    redaction_notes: []
  };
}

function blockersFromState(
  state: WaygentRunStateV2,
  events: AgentLensEvent[],
  applyReadiness: ApplyReadinessProjection,
  evidencePacket: OperatorEvidencePacket
): OperatorBlocker[] {
  const blockers: OperatorBlocker[] = [];
  const taskFailure = firstTaskFailure(state);
  const applyReason = state.apply.reason ?? applyReadiness.reason ?? null;

  if (state.status === "initializing" || state.status === "running" || state.status === "applying") {
    blockers.push(makeBlocker({
      code: "runtime_active",
      title: "Runtime is active",
      summary: `${state.run_id} is still ${state.status}; mutating actions are unsafe until runtime settles.`,
      severity: "blocking",
      evidenceRefs: evidencePacket.state_refs,
      recommendedActionIds: ["inspect_run", "explain_run", "open_raw_evidence"]
    }));
  }

  if (taskFailure?.failureClass === "verification_failed" || verificationFailed(state, events)) {
    const taskId = taskFailure?.task.id ?? failedVerificationTaskId(state) ?? eventTaskId(events, "runway.verification_result");
    blockers.push(makeBlocker({
      code: "verification_failed",
      title: "Verification failed",
      summary: taskId ? `${taskId} failed verification.` : "Verification failed for the run.",
      severity: "blocking",
      taskId,
      evidenceRefs: verificationEvidenceRefs(taskId, events, evidencePacket),
      recommendedActionIds: ["rerun_verification", "open_ai_repair_handoff"]
    }));
  }

  if (taskFailure?.failureClass === "needs_rebase" || applyReason === "needs_rebase" || driftFailureClass(state) === "needs_rebase") {
    const taskId = taskFailure?.task.id;
    blockers.push(makeBlocker({
      code: "needs_rebase",
      title: "Checkpoint needs rebase",
      summary: "Checkpoint evidence no longer applies cleanly to the current source basis.",
      severity: "blocking",
      taskId,
      evidenceRefs: unique([...evidencePacket.state_refs, ...driftEvidenceRefs(state)]),
      recommendedActionIds: ["regenerate_checkpoint", "rebase_checkpoint", "open_ai_repair_handoff"]
    }));
  }

  if (taskFailure?.failureClass === "unsafe_apply" || applyReason === "unsafe_apply") {
    blockers.push(makeBlocker({
      code: "checkpoint_digest_mismatch",
      title: "Checkpoint safety failed",
      summary: "Apply safety evidence is blocked by unsafe checkpoint state.",
      severity: "blocking",
      taskId: taskFailure?.task.id,
      evidenceRefs: evidencePacket.state_refs,
      recommendedActionIds: ["open_raw_evidence", "open_ai_repair_handoff"]
    }));
  }

  if (checkpointMissing(state, evidencePacket)) {
    blockers.push(makeBlocker({
      code: "checkpoint_missing",
      title: "Checkpoint evidence is missing",
      summary: "A verified or completed task is missing checkpoint refs required for apply readiness.",
      severity: "blocking",
      evidenceRefs: evidencePacket.state_refs,
      missingRefs: ["checkpoint_refs"],
      recommendedActionIds: ["regenerate_checkpoint", "open_ai_repair_handoff"]
    }));
  }

  const artifactMissing = state.drift.unrepaired_blockers.some((blocker) => failureClassOf(blocker) === "artifact_missing");
  if (artifactMissing) {
    blockers.push(makeBlocker({
      code: "artifact_missing",
      title: "Artifact evidence is missing",
      summary: "Reconciliation found missing artifact evidence.",
      severity: "blocking",
      evidenceRefs: unique([...evidencePacket.state_refs, ...driftEvidenceRefs(state)]),
      missingRefs: ["artifact_refs"],
      recommendedActionIds: ["open_raw_evidence", "open_ai_repair_handoff"]
    }));
  }

  if (applyReadiness.status === "blocked" && blockers.length === 0) {
    blockers.push(makeBlocker({
      code: "apply_blocked",
      title: "Apply is blocked",
      summary: `Apply readiness is blocked by ${applyReadiness.reason ?? "unknown_reason"}.`,
      severity: "blocking",
      evidenceRefs: evidencePacket.state_refs,
      recommendedActionIds: ["inspect_run", "explain_run", "open_raw_evidence", "open_ai_repair_handoff"]
    }));
  }

  const providerBlocker = providerReadinessBlocker(state, events, evidencePacket);
  if (providerBlocker) blockers.push(providerBlocker);

  if (evidencePacket.missing_refs.length > 0 && blockers.length === 0) {
    blockers.push(makeBlocker({
      code: "evidence_incomplete",
      title: "Evidence is incomplete",
      summary: "Projection inputs are missing evidence expected by the operator decision.",
      severity: "warning",
      evidenceRefs: evidencePacket.state_refs,
      missingRefs: evidencePacket.missing_refs,
      recommendedActionIds: ["inspect_run", "open_raw_evidence"]
    }));
  }

  if ((state.status === "failed" || state.lifecycle_outcome === "failed") && blockers.length === 0) {
    blockers.push(makeBlocker({
      code: taskFailure?.failureClass ?? "unknown_failure",
      title: "Run failed",
      summary: taskFailure ? `${taskFailure.task.id} failed by ${taskFailure.failureClass}.` : `${state.run_id} failed without a classified blocker.`,
      severity: "blocking",
      taskId: taskFailure?.task.id,
      evidenceRefs: evidencePacket.state_refs,
      recommendedActionIds: ["inspect_run", "explain_run", "open_raw_evidence", "open_ai_repair_handoff"]
    }));
  }

  return blockers;
}

function providerReadinessBlocker(
  state: WaygentRunStateV2,
  events: AgentLensEvent[],
  evidencePacket: OperatorEvidencePacket
): OperatorBlocker | null {
  try {
    const maturity = projectOperationalMaturityFromState({ state, events });
    if (maturity.provider_readiness.status === "ready" || maturity.provider_readiness.status === "unknown") return null;
    return makeBlocker({
      code: "provider_not_ready",
      title: "Provider is not ready",
      summary: maturity.provider_readiness.recommended_next_action,
      severity: "warning",
      evidenceRefs: unique([...evidencePacket.state_refs, ...maturity.provider_readiness.attempt_refs.map((ref) => `attempt:${ref}`)]),
      recommendedActionIds: ["inspect_run", "open_raw_evidence"]
    });
  } catch {
    return null;
  }
}

function allowedActionsFor(input: {
  runId: string;
  state: WaygentRunStateV2;
  applyReadiness: ApplyReadinessProjection;
  primaryBlocker: OperatorBlocker | null;
  evidencePacket: OperatorEvidencePacket;
}): OperatorAllowedAction[] {
  const ids: OperatorActionId[] = ["inspect_run", "explain_run", "open_raw_evidence"];
  if (input.primaryBlocker || input.applyReadiness.status !== "ready") ids.push("open_ai_repair_handoff");

  if (input.applyReadiness.status === "ready" && input.primaryBlocker === null) {
    ids.push("review_patch", "apply_run");
  } else if (input.primaryBlocker?.code === "verification_failed") {
    ids.push("rerun_verification");
  } else if (input.primaryBlocker?.code === "needs_rebase") {
    ids.push("regenerate_checkpoint", "rebase_checkpoint");
  } else if (input.primaryBlocker?.code === "checkpoint_missing") {
    ids.push("regenerate_checkpoint");
  } else if (input.primaryBlocker?.code === "needs_user_input") {
    ids.push("request_user_input");
  } else if (input.primaryBlocker?.code === "needs_approval") {
    ids.push("approve_recovery");
  }

  return unique(ids).map((id) => allowedAction(id, input.runId, evidenceRefsForAction(id, input.evidencePacket)));
}

function blockedActionsFor(input: {
  applyReadiness: ApplyReadinessProjection;
  primaryBlocker: OperatorBlocker | null;
  evidencePacket: OperatorEvidencePacket;
  allowedActions: OperatorAllowedAction[];
}): OperatorBlockedAction[] {
  const allowedIds = new Set(input.allowedActions.map((action) => action.id));
  const blocked: OperatorBlockedAction[] = [];

  if (!allowedIds.has("apply_run")) {
    const blockerCode = input.primaryBlocker?.code ?? input.applyReadiness.reason ?? input.applyReadiness.status;
    blocked.push(blockedAction(
      "apply_run",
      `Apply readiness is ${input.applyReadiness.status} by ${blockerCode}.`,
      input.primaryBlocker?.evidence_refs ?? input.evidencePacket.state_refs,
      "Verification, checkpoint evidence, and apply readiness pass."
    ));
  }

  if (input.evidencePacket.missing_refs.length > 0 && !allowedIds.has("open_ai_repair_handoff")) {
    blocked.push(blockedAction(
      "open_ai_repair_handoff",
      "AI repair handoff is blocked because required evidence is missing.",
      input.evidencePacket.state_refs,
      "The missing evidence refs are restored."
    ));
  }

  return blocked;
}

function allowedAction(
  id: OperatorActionId,
  runId: string,
  evidenceRefs: string[],
  reason = actionDefinitions[id].defaultReason
): OperatorAllowedAction {
  const definition = actionDefinitions[id];
  return {
    id,
    label: definition.label,
    reason,
    evidence_refs: evidenceRefs,
    requires_approval: definition.requiresApproval,
    requires_runtime_revalidation: definition.requiresRuntimeRevalidation,
    command: definition.command(runId)
  };
}

function blockedAction(
  id: OperatorActionId,
  reason: string,
  evidenceRefs: string[],
  unblocksWhen: string
): OperatorBlockedAction {
  return {
    id,
    label: actionDefinitions[id].label,
    reason,
    evidence_refs: evidenceRefs,
    unblocks_when: unblocksWhen
  };
}

function aiHandoffFromDecision(input: {
  runId: string;
  displayStatus: OperatorRunStatus;
  primaryBlocker: OperatorBlocker | null;
  secondaryBlockers: OperatorBlocker[];
  allowedActions: OperatorAllowedAction[];
  blockedActions: OperatorBlockedAction[];
  evidencePacket: OperatorEvidencePacket;
}): OperatorAiHandoff {
  const blockerCode = input.primaryBlocker?.code ?? null;
  return {
    purpose: blockerCode ? "draft_repair_plan" : "summarize_blocker",
    prompt_summary: blockerCode
      ? `Draft a repair plan for ${blockerCode} using bounded evidence.`
      : `Summarize the operator decision for ${input.runId} using bounded evidence.`,
    run_id: input.runId,
    current_status: input.displayStatus,
    primary_blocker: blockerCode,
    secondary_blockers: input.secondaryBlockers.map((blocker) => blocker.code),
    allowed_action_ids: input.allowedActions.map((action) => action.id),
    blocked_action_ids: input.blockedActions.map((action) => action.id),
    constraints: [
      "Do not apply patches.",
      "Do not mutate source.",
      "Do not resume execution.",
      "Do not override Waygent runtime policy."
    ],
    evidence_refs: unique([
      ...input.evidencePacket.state_refs,
      ...input.evidencePacket.verification_refs,
      ...input.evidencePacket.checkpoint_refs,
      ...input.evidencePacket.artifact_refs
    ]),
    missing_evidence: input.evidencePacket.missing_refs,
    raw_fallback_refs: unique([...input.evidencePacket.state_refs, ...input.evidencePacket.event_refs]),
    safety_notes: ["Waygent runtime remains apply authority."]
  };
}

function statusSummaryFromState(
  state: WaygentRunStateV2,
  displayStatus: OperatorRunStatus,
  applyReadiness: ApplyReadinessProjection,
  primaryBlocker: OperatorBlocker | null
): OperatorStatusSummary {
  const tasks = Object.values(state.tasks);
  const activeTasks = tasks.filter((task) => ["pending", "ready", "running", "needs_fix"].includes(task.status)).length;
  const completedTasks = tasks.filter((task) => task.status === "verified" || task.status === "applied").length;
  const blockedTasks = tasks.filter((task) => task.status === "blocked" || task.status === "failed").length;
  const summary = primaryBlocker
    ? `${state.run_id} is ${displayStatus} by ${primaryBlocker.code}.`
    : `${state.run_id} is ${displayStatus}.`;

  return {
    display_status: displayStatus,
    runtime_status: state.status,
    lifecycle_outcome: state.lifecycle_outcome,
    current_phase: state.current_phase,
    active_tasks: activeTasks,
    completed_tasks: completedTasks,
    blocked_tasks: blockedTasks,
    apply_status: applyReadiness.status,
    summary
  };
}

function displayStatusFromState(
  state: WaygentRunStateV2,
  applyReadiness: ApplyReadinessProjection,
  primaryBlocker: OperatorBlocker | null
): OperatorRunStatus {
  if (applyReadiness.status === "ready" && primaryBlocker === null) return "ready_to_apply";
  if (state.status === "applied" || applyReadiness.status === "applied") return "done";
  if (state.status === "failed" || state.lifecycle_outcome === "failed") return "failed";
  if (state.current_phase === "recover" && state.status === "running") return "recovering";
  if (state.status === "running" || state.status === "initializing" || state.status === "applying") return "running";
  if (primaryBlocker?.code === "needs_user_input") return "needs_input";
  if (primaryBlocker?.code === "needs_approval") return "needs_approval";
  if (state.status === "blocked" || state.lifecycle_outcome === "blocked" || primaryBlocker) return "blocked";
  return "done";
}

function confidenceFor(
  state: WaygentRunStateV2 | null,
  primaryBlocker: OperatorBlocker | null,
  evidencePacket: OperatorEvidencePacket
): OperatorDecisionConfidence {
  if (!state) return "unknown";
  if (primaryBlocker?.code === "state_invalid" || primaryBlocker?.code === "state_missing") return "unknown";
  if (evidencePacket.missing_refs.length > 0) return "partial";
  return "deterministic";
}

function unknownReasonsFor(
  confidence: OperatorDecisionConfidence,
  primaryBlocker: OperatorBlocker | null,
  evidencePacket: OperatorEvidencePacket
): string[] {
  if (confidence === "deterministic") return [];
  if (confidence === "partial") return evidencePacket.missing_refs.map((ref) => `missing:${ref}`);
  return [primaryBlocker?.code ?? "unknown_projection_state"];
}

function missingRefsFromState(state: WaygentRunStateV2, checkpointRefs: string[]): string[] {
  const missing = new Set<string>();
  if (checkpointRefs.length === 0 && expectsCheckpointEvidence(state)) missing.add("checkpoint_refs");
  if (!state.artifact_index && expectsCheckpointEvidence(state)) missing.add("artifact_index");
  return [...missing];
}

function checkpointMissing(state: WaygentRunStateV2, evidencePacket: OperatorEvidencePacket): boolean {
  return expectsCheckpointEvidence(state) && evidencePacket.checkpoint_refs.length === 0;
}

function expectsCheckpointEvidence(state: WaygentRunStateV2): boolean {
  const hasVerifiedTask = Object.values(state.tasks).some((task) => task.status === "verified" || task.status === "applied");
  return hasVerifiedTask || state.status === "completed" || state.completion_audit?.status === "passed";
}

function firstTaskFailure(state: WaygentRunStateV2): { task: WaygentRunStateV2["tasks"][string]; failureClass: string } | null {
  for (const task of Object.values(state.tasks)) {
    if ((task.status === "blocked" || task.status === "failed" || state.status === "blocked" || state.status === "failed") &&
      typeof task.latest_failure_class === "string" &&
      task.latest_failure_class.length > 0) {
      return { task, failureClass: task.latest_failure_class };
    }
  }
  return null;
}

function verificationFailed(state: WaygentRunStateV2, events: AgentLensEvent[]): boolean {
  return failedVerificationTaskId(state) !== null ||
    events.some((event) => event.event_type === "runway.verification_result" && event.outcome === "failed");
}

function failedVerificationTaskId(state: WaygentRunStateV2): string | null {
  for (const verification of state.verification) {
    if (String(verification.status ?? verification.outcome ?? "") === "failed") {
      return typeof verification.task_id === "string" ? verification.task_id : null;
    }
  }
  return null;
}

function verificationEvidenceRefs(
  taskId: string | null | undefined,
  events: AgentLensEvent[],
  evidencePacket: OperatorEvidencePacket
): string[] {
  const refs = [...evidencePacket.state_refs];
  if (taskId) refs.push(`verification:${taskId}`);
  for (const event of events) {
    if (event.event_type === "runway.verification_result") refs.push(`event:${event.event_id}`);
  }
  return unique(refs);
}

function verificationRefsFromState(state: WaygentRunStateV2): string[] {
  const refs = new Set<string>();
  for (const verification of state.verification) {
    const taskId = typeof verification.task_id === "string" ? verification.task_id : null;
    const verificationId = typeof verification.verification_id === "string" ? verification.verification_id : null;
    if (taskId) refs.add(`verification:${taskId}`);
    if (verificationId) refs.add(`verification_id:${verificationId}`);
  }
  return [...refs];
}

function checkpointRefsFromTasks(state: WaygentRunStateV2): string[] {
  const refs: string[] = [];
  for (const task of Object.values(state.tasks)) refs.push(...task.checkpoint_refs);
  return unique(refs.filter((ref) => ref.length > 0));
}

function artifactRefsFromState(state: WaygentRunStateV2, applyReadiness: ApplyReadinessProjection): string[] {
  const refs = new Set<string>();
  for (const artifact of state.artifact_index ?? []) refs.add(artifact.ref);
  if (applyReadiness.combined_patch_ref) refs.add(applyReadiness.combined_patch_ref);
  for (const ref of applyReadiness.checkpoint_refs) refs.add(ref);
  const combined = state.completion_audit?.combined_apply_evidence;
  if (combined && typeof combined === "object") {
    const evidenceRef = (combined as Record<string, unknown>).evidence_ref;
    if (typeof evidenceRef === "string" && evidenceRef.length > 0) refs.add(evidenceRef);
  }
  return [...refs];
}

function artifactRefsFromEvents(events: AgentLensEvent[]): string[] {
  const refs = new Set<string>();
  for (const event of events) {
    for (const artifact of event.artifacts ?? []) refs.add(artifact.path);
  }
  return [...refs];
}

function eventRefs(events: AgentLensEvent[]): string[] {
  return events.map((event) => `event:${event.event_id}`);
}

function driftFailureClass(state: WaygentRunStateV2): string | null {
  for (const blocker of state.drift.unrepaired_blockers) {
    const failureClass = failureClassOf(blocker);
    if (failureClass) return failureClass;
  }
  for (const record of state.drift.records) {
    const failureClass = failureClassOf(record);
    if (failureClass) return failureClass;
  }
  return null;
}

function driftEvidenceRefs(state: WaygentRunStateV2): string[] {
  const refs = new Set<string>();
  if (state.drift.last_checked_at) refs.add(`drift:${state.drift.last_checked_at}`);
  for (const record of [...state.drift.records, ...state.drift.unrepaired_blockers]) {
    const ref = typeof record.ref === "string" ? record.ref : null;
    if (ref) refs.add(ref);
  }
  return [...refs];
}

function failureClassOf(record: Record<string, unknown>): string | null {
  const failureClass = record.failure_class ?? record.type;
  return typeof failureClass === "string" && failureClass.length > 0 ? failureClass : null;
}

function eventTaskId(events: AgentLensEvent[], eventType: string): string | null {
  const event = [...events].reverse().find((candidate) => candidate.event_type === eventType);
  const taskId = event?.payload.task_id;
  return typeof taskId === "string" ? taskId : null;
}

function evidenceRefsForAction(id: OperatorActionId, evidencePacket: OperatorEvidencePacket): string[] {
  if (id === "open_raw_evidence") return unique([...evidencePacket.state_refs, ...evidencePacket.event_refs]);
  if (id === "rerun_verification") return unique([...evidencePacket.state_refs, ...evidencePacket.verification_refs]);
  if (id === "regenerate_checkpoint" || id === "rebase_checkpoint" || id === "review_patch" || id === "apply_run") {
    return unique([...evidencePacket.state_refs, ...evidencePacket.checkpoint_refs, ...evidencePacket.artifact_refs]);
  }
  return evidencePacket.state_refs.length > 0 ? evidencePacket.state_refs : evidencePacket.event_refs;
}

function makeBlocker(input: {
  code: string;
  title: string;
  summary: string;
  severity: OperatorBlocker["severity"];
  taskId?: string | null | undefined;
  evidenceRefs?: string[];
  missingRefs?: string[];
  recommendedActionIds: OperatorActionId[];
}): OperatorBlocker {
  return {
    code: input.code,
    title: input.title,
    summary: input.summary,
    severity: input.severity,
    ...(input.taskId ? { task_id: input.taskId } : {}),
    evidence_refs: unique(input.evidenceRefs ?? []),
    missing_refs: unique(input.missingRefs ?? []),
    recommended_action_ids: input.recommendedActionIds
  };
}

function stateRef(state: WaygentRunStateV2): string {
  return `state:${state.state_path}`;
}

function runIdFromInput(input: OperatorDecisionInput): string {
  return input.run_id ?? input.state?.run_id ?? input.events[0]?.orchestrator_run_id ?? input.events[0]?.agentlens_run_id ?? "run_unknown";
}

function generatedAtFromInput(input: OperatorDecisionInput): string {
  return input.state?.timestamps.updated_at ?? input.events.at(-1)?.occurred_at ?? "1970-01-01T00:00:00.000Z";
}

function priority(blocker: OperatorBlocker): number {
  return blockerPriority[blocker.code] ?? 999;
}

function unique<T>(items: T[]): T[] {
  return [...new Set(items)];
}

function nullCommand(): null {
  return null;
}
