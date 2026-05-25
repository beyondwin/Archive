import { describe, expect, test } from "bun:test";
import { buildRepairPacket, excerptForRepair } from "../src/repairPacket";

describe("excerptForRepair", () => {
  test("returns input unchanged when under cap", () => {
    expect(excerptForRepair("short", 16384)).toBe("short");
  });

  test("returns head + marker + tail when over cap", () => {
    const head = "H".repeat(8192);
    const tail = "T".repeat(8192);
    const oversized = head + "MIDDLE".repeat(2000) + tail;
    const out = excerptForRepair(oversized, 16384);
    expect(out.startsWith("H".repeat(8192))).toBe(true);
    expect(out.endsWith("T".repeat(8192))).toBe(true);
    expect(out).toContain("---<truncated>---");
    expect(Buffer.byteLength(out)).toBeLessThan(Buffer.byteLength(oversized));
  });
});

describe("buildRepairPacket", () => {
  test("composes packet with prior diff ref, failed and passed verifications, scope_lock", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_task_x_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: ["a.ts"],
        summary: "first pass implementation",
        evidence: {
          patch_ref: "artifacts/worker/task_x/attempt_1_patch.diff",
          patch_sha256: "deadbeef".padEnd(64, "0"),
          patch_byte_length: 1234,
        },
      },
      verifications: [
        {
          verification_id: "v1",
          command: "tsc",
          exit_code: 2,
          timed_out: false,
          stdout: "TS error",
          stderr: "",
          status: "failed",
        },
        {
          verification_id: "v2",
          command: "bun test",
          exit_code: 0,
          timed_out: false,
          stdout: "5 pass",
          stderr: "",
          status: "passed",
        },
      ],
    });
    expect(packet.schema).toBe("runway.repair_task_packet.v1");
    expect(packet.task_id).toBe("task_x");
    expect(packet.role).toBe("repair");
    expect(packet.prior_diff_ref).toBe(
      "artifacts/worker/task_x/attempt_1_patch.diff",
    );
    expect(packet.prior_worker_summary).toBe("first pass implementation");
    expect(packet.failed_verifications).toHaveLength(1);
    expect(packet.failed_verifications[0]!.verification_id).toBe("v1");
    expect(packet.failed_verifications[0]!.stdout_excerpt).toBe("TS error");
    expect(packet.passed_verifications).toEqual([
      { verification_id: "v2", command: "bun test" },
    ]);
    expect(packet.scope_lock_instruction).toContain("smallest changes");
  });

  test("operator_instruction included when provided", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: [],
        summary: "s",
        evidence: { patch_ref: "p", patch_sha256: "x", patch_byte_length: 1 },
      },
      verifications: [
        {
          verification_id: "v1",
          command: "c",
          exit_code: 1,
          timed_out: false,
          stdout: "",
          stderr: "",
          status: "failed",
        },
      ],
      operator_instruction: "check line 138",
    });
    expect(packet.operator_instruction).toBe("check line 138");
  });

  test("evidence_filter narrows failed_verifications to listed ids", () => {
    const packet = buildRepairPacket({
      task_id: "task_x",
      attempt_id: "attempt_2",
      prior_worker_result: {
        schema: "runway.worker_result.v1",
        task_id: "task_x",
        candidate_id: "cand_x",
        status: "completed",
        changed_files: [],
        summary: "s",
        evidence: { patch_ref: "p", patch_sha256: "x", patch_byte_length: 1 },
      },
      verifications: [
        {
          verification_id: "v1",
          command: "c1",
          exit_code: 1,
          timed_out: false,
          stdout: "",
          stderr: "",
          status: "failed",
        },
        {
          verification_id: "v2",
          command: "c2",
          exit_code: 1,
          timed_out: false,
          stdout: "",
          stderr: "",
          status: "failed",
        },
      ],
      evidence_filter: ["v1"],
    });
    expect(packet.failed_verifications.map((v) => v.verification_id)).toEqual([
      "v1",
    ]);
    expect(packet.passed_verifications.map((v) => v.verification_id)).toEqual([
      "v2",
    ]);
  });
});
