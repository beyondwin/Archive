import type { AgentLensEvent, TaskVerificationResolution, WaygentRunStateV2 } from "@waygent/contracts";

interface VerificationCandidate {
  task_id: string;
  status: "passed" | "failed";
  ref: string;
  order: number;
}

export function resolveTaskVerifications(
  state: WaygentRunStateV2,
  events: AgentLensEvent[] = []
): Record<string, TaskVerificationResolution> {
  const byTask = new Map<string, VerificationCandidate[]>();

  for (const [index, record] of state.verification.entries()) {
    const taskId = stringValue(record.task_id);
    if (!taskId) continue;
    const status = verificationStatus(record.status ?? record.outcome);
    if (!status) continue;
    pushCandidate(byTask, {
      task_id: taskId,
      status,
      ref: verificationRecordRef(record, index),
      order: verificationRecordOrder(record, index)
    });
  }

  for (const event of events) {
    if (event.event_type !== "runway.verification_result") continue;
    const taskId = stringValue(event.payload.task_id);
    if (!taskId) continue;
    const status = event.outcome === "success" ? "passed" : event.outcome === "failed" ? "failed" : null;
    if (!status) continue;
    pushCandidate(byTask, {
      task_id: taskId,
      status,
      ref: `event:${event.event_id}`,
      order: eventOrder(event)
    });
  }

  const out: Record<string, TaskVerificationResolution> = {};
  for (const task of Object.values(state.tasks)) {
    const candidates = [...(byTask.get(task.id) ?? [])].sort((left, right) => left.order - right.order);
    const latest = candidates.at(-1);
    out[task.id] = {
      task_id: task.id,
      latest_status: latest?.status ?? "missing",
      latest_verification_ref: latest?.ref ?? null,
      stale_failure_refs: candidates
        .slice(0, -1)
        .filter((candidate) => candidate.status === "failed")
        .map((candidate) => candidate.ref)
    };
  }
  return out;
}

export function projectVerificationResolutions(
  state: WaygentRunStateV2,
  events: AgentLensEvent[] = []
): Record<string, TaskVerificationResolution> {
  return resolveTaskVerifications(state, events);
}

export function hasActiveVerificationFailure(
  state: WaygentRunStateV2,
  events: AgentLensEvent[] = []
): { task_id: string; evidence_refs: string[] } | null {
  const resolutions = resolveTaskVerifications(state, events);
  for (const task of Object.values(state.tasks)) {
    const resolution = resolutions[task.id];
    if (resolution?.latest_status === "failed") {
      return {
        task_id: task.id,
        evidence_refs: [resolution.latest_verification_ref].filter((ref): ref is string => typeof ref === "string")
      };
    }
  }
  return null;
}

export function hasRecoveredFailure(state: WaygentRunStateV2, taskId?: string): boolean {
  return recoveredFailureRecords(state).some((record) => !taskId || record.task_id === taskId);
}

export function staleVerificationFailureRefs(state: WaygentRunStateV2, events: AgentLensEvent[] = []): string[] {
  const refs = new Set<string>();
  for (const resolution of Object.values(resolveTaskVerifications(state, events))) {
    for (const ref of resolution.stale_failure_refs) refs.add(ref);
  }
  return [...refs];
}

export function recoveredFailureRecords(state: WaygentRunStateV2): Array<{
  task_id: string;
  failure_class: string;
  evidence_refs: string[];
}> {
  const records = new Map<string, { task_id: string; failure_class: string; evidence_refs: string[] }>();

  for (const record of state.recovered_failures ?? []) {
    const key = `${record.task_id}:${String(record.failure_class)}`;
    records.set(key, {
      task_id: record.task_id,
      failure_class: String(record.failure_class),
      evidence_refs: record.evidence_refs
    });
  }

  for (const [index, record] of state.recovery.entries()) {
    const taskId = stringValue(record.task_id);
    const failureClass = stringValue(record.failure_class);
    if (!taskId || !failureClass) continue;
    const key = `${taskId}:${failureClass}`;
    if (records.has(key)) continue;
    records.set(key, {
      task_id: taskId,
      failure_class: failureClass,
      evidence_refs: evidenceRefsFromRecoveryRecord(record, index)
    });
  }

  return [...records.values()];
}

function pushCandidate(map: Map<string, VerificationCandidate[]>, candidate: VerificationCandidate): void {
  const existing = map.get(candidate.task_id) ?? [];
  existing.push(candidate);
  map.set(candidate.task_id, existing);
}

function verificationStatus(value: unknown): "passed" | "failed" | null {
  const status = String(value ?? "");
  if (status === "passed" || status === "success") return "passed";
  if (status === "failed") return "failed";
  return null;
}

function verificationRecordRef(record: Record<string, unknown>, index: number): string {
  return stringValue(record.kernel_result_ref) ??
    stringValue(record.verification_ref) ??
    stringValue(record.evidence_ref) ??
    prefixedValue("verification_id", record.verification_id) ??
    `verification_state:${index}`;
}

function verificationRecordOrder(record: Record<string, unknown>, index: number): number {
  const verifiedAt = parseTime(record.verified_at);
  if (verifiedAt !== null) return verifiedAt;
  const completedAt = parseTime(record.completed_at);
  if (completedAt !== null) return completedAt;
  return index;
}

function eventOrder(event: AgentLensEvent): number {
  const occurredAt = parseTime(event.occurred_at);
  return occurredAt ?? event.sequence;
}

function parseTime(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function prefixedValue(prefix: string, value: unknown): string | null {
  const raw = stringValue(value);
  return raw ? `${prefix}:${raw}` : null;
}

function evidenceRefsFromRecoveryRecord(record: Record<string, unknown>, index: number): string[] {
  const refs = record.evidence_refs;
  if (Array.isArray(refs)) return refs.filter((ref): ref is string => typeof ref === "string" && ref.length > 0);
  const ref = stringValue(record.ref);
  return ref ? [ref] : [`recovery:${index}`];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
