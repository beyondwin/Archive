import { describe, expect, it } from "bun:test";
import { createHash } from "node:crypto";
import { validateWorkerEnvelope } from "../src/workerEnvelope";
import type { DesignNormalized, WorkerEnvelopeV2 } from "../src/types";

function sha(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

const snip = "const x = 1;\n";
const design: DesignNormalized = {
  schema: "waygent.design_contract.v1",
  source_path: "d.md",
  source_sha256: "x",
  invariants: [],
  prescriptive_blocks: [{ id: "SNIP-001", language: "ts", body: snip, sha256: sha(snip) }],
  extracted_at: "2026-01-01T00:00:00Z",
  parser: "deterministic",
  extraction_confidence: "high"
};

const baseEnv: WorkerEnvelopeV2 = {
  schema: "waygent.worker_result.v2",
  task_id: "task_1",
  summary: "did stuff",
  evidence: { verification_commands: ["bun test"], key_decision: null },
  policy_ack: [],
  stale_test_candidates: [],
  prescriptive_block_outputs: [{ id: "SNIP-001", sha256: sha(snip) }]
};

describe("validateWorkerEnvelope", () => {
  it("passes when envelope is well-formed and snippets match", () => {
    const out = validateWorkerEnvelope(baseEnv, design);
    expect(out.blockers).toHaveLength(0);
  });

  it("blocks when stale_test_candidates field is absent", () => {
    const env = { ...baseEnv } as Partial<WorkerEnvelopeV2>;
    delete env.stale_test_candidates;
    const out = validateWorkerEnvelope(env as WorkerEnvelopeV2, design);
    expect(out.blockers.map((b) => b.kind)).toContain("stale_test_candidates_missing");
  });

  it("blocks on prescriptive drift", () => {
    const env: WorkerEnvelopeV2 = {
      ...baseEnv,
      prescriptive_block_outputs: [{ id: "SNIP-001", sha256: sha("const y = 2;\n") }]
    };
    const out = validateWorkerEnvelope(env, design);
    expect(out.blockers.map((b) => b.kind)).toContain("prescriptive_drift");
  });
});
