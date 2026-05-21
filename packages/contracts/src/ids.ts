const ID_PATTERN = /^[a-z][a-z0-9_:-]{2,127}$/;

export type WaygentId =
  | RunId
  | TaskId
  | CandidateId
  | CheckpointId
  | EventId
  | ArtifactId
  | RequestId;

export type RunId = string & { readonly __brand: "RunId" };
export type TaskId = string & { readonly __brand: "TaskId" };
export type CandidateId = string & { readonly __brand: "CandidateId" };
export type CheckpointId = string & { readonly __brand: "CheckpointId" };
export type EventId = string & { readonly __brand: "EventId" };
export type ArtifactId = string & { readonly __brand: "ArtifactId" };
export type RequestId = string & { readonly __brand: "RequestId" };

export function assertWaygentId(value: string, label = "id"): string {
  if (!ID_PATTERN.test(value)) {
    throw new Error(`${label} must match ${ID_PATTERN.source}`);
  }
  return value;
}

export function runId(value: string): RunId {
  return assertWaygentId(value, "run id") as RunId;
}

export function taskId(value: string): TaskId {
  return assertWaygentId(value, "task id") as TaskId;
}

export function candidateId(value: string): CandidateId {
  return assertWaygentId(value, "candidate id") as CandidateId;
}

export function checkpointId(value: string): CheckpointId {
  return assertWaygentId(value, "checkpoint id") as CheckpointId;
}

export function eventId(value: string): EventId {
  return assertWaygentId(value, "event id") as EventId;
}

export function artifactId(value: string): ArtifactId {
  return assertWaygentId(value, "artifact id") as ArtifactId;
}

export function requestId(value: string): RequestId {
  return assertWaygentId(value, "request id") as RequestId;
}

export function timestamp(value = new Date()): string {
  const iso = value.toISOString();
  if (!iso.endsWith("Z")) {
    throw new Error("timestamp must be UTC");
  }
  return iso;
}
