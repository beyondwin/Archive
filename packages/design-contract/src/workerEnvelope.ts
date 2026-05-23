import type { DesignNormalized, DesignContractBlockerKind, WorkerEnvelopeV2 } from "./types";

export interface EnvelopeBlocker {
  kind: DesignContractBlockerKind;
  detail: string;
}

export interface EnvelopeValidationResult {
  blockers: EnvelopeBlocker[];
}

export function validateWorkerEnvelope(
  env: WorkerEnvelopeV2,
  design: DesignNormalized
): EnvelopeValidationResult {
  const blockers: EnvelopeBlocker[] = [];
  if (!Array.isArray((env as { stale_test_candidates?: unknown }).stale_test_candidates)) {
    blockers.push({
      kind: "stale_test_candidates_missing",
      detail: `task ${env.task_id} envelope missing stale_test_candidates array`
    });
  }
  const outputs = Array.isArray(env.prescriptive_block_outputs) ? env.prescriptive_block_outputs : [];
  const outputById = new Map(outputs.map((o) => [o.id, o.sha256]));
  for (const block of design.prescriptive_blocks) {
    const got = outputById.get(block.id);
    if (got === undefined) continue;
    if (got !== block.sha256) {
      blockers.push({
        kind: "prescriptive_drift",
        detail: `snippet ${block.id} expected ${block.sha256.slice(0, 12)} got ${got.slice(0, 12)}`
      });
    }
  }
  return { blockers };
}
