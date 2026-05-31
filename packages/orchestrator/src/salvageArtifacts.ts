import type { ArtifactReference, SalvageResult, WaygentRunStateV2 } from "@waygent/contracts";
import { writeArtifact } from "@waygent/lens-store";
import { artifactIndexEntry, mergeArtifactIndex } from "./artifactIndex";

export interface RecordSalvageArtifactInput {
  state: WaygentRunStateV2;
  task_id: string;
  attempt_id: string;
  failure_class: string;
  status: SalvageResult["status"];
  patch_ref: string | null;
  changed_files: string[];
  reason: string | null;
  evidence_refs: string[];
}

export interface RecordSalvageArtifactResult {
  nextState: WaygentRunStateV2;
  artifact: ArtifactReference;
  salvage: SalvageResult;
}

export function recordSalvageArtifact(input: RecordSalvageArtifactInput): RecordSalvageArtifactResult {
  const salvage: SalvageResult = {
    schema: "waygent.salvage_result.v1",
    task_id: input.task_id,
    attempt_id: input.attempt_id,
    status: input.status,
    patch_ref: input.patch_ref,
    changed_files: [...new Set(input.changed_files)],
    reason: input.reason,
    evidence_refs: [...new Set(input.evidence_refs)]
  };
  const artifact = writeArtifact(
    input.state.run_root,
    `salvage/${input.task_id}/${input.attempt_id}.json`,
    `${JSON.stringify(salvage, null, 2)}\n`,
    "application/json"
  );
  const blocked = input.status !== "salvaged_patch";
  const nextState: WaygentRunStateV2 = {
    ...input.state,
    artifact_index: mergeArtifactIndex(input.state.artifact_index, [
      artifactIndexEntry({ artifact, producer_phase: "decision", task_id: input.task_id })
    ]),
    recovery: [
      ...input.state.recovery,
      {
        task_id: input.task_id,
        failure_class: input.failure_class,
        action: blocked ? "request_decision" : "salvage_then_review",
        automatic: !blocked,
        result: blocked ? "blocked" : "scheduled",
        reason: input.reason,
        salvage_ref: artifact.path,
        patch_ref: input.patch_ref,
        evidence_refs: salvage.evidence_refs
      }
    ]
  };
  return { nextState, artifact, salvage };
}
