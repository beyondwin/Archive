import type { WorkerResult } from "@waygent/contracts";

const REPAIR_EXCERPT_BYTES = 16_384;
const REPAIR_EXCERPT_HALF = 8_192;
const TRUNCATION_MARKER = "\n---<truncated>---\n";

const SCOPE_LOCK = [
  "You are the Waygent repair worker.",
  "The worktree already contains a prior worker's diff (see git status).",
  "A subset of verifications failed; their evidence is in the task packet.",
  "",
  "Your task:",
  "- Read failed_verifications carefully — especially stdout/stderr excerpts.",
  "- Make the smallest changes needed to make the failed verifications pass.",
  "- Do NOT add new features, refactor unrelated code, or change passing verifications.",
  "- Do NOT revert prior changes unless a specific change directly caused a failure.",
  "- Honor the worktree's task_packet write policy.",
  "- Return runway.worker_result.v1 with status=completed and a short summary describing the fix.",
].join("\n");

export function excerptForRepair(text: string, capBytes: number): string {
  if (Buffer.byteLength(text) <= capBytes) return text;
  const head = text.slice(0, REPAIR_EXCERPT_HALF);
  const tail = text.slice(-REPAIR_EXCERPT_HALF);
  return head + TRUNCATION_MARKER + tail;
}

export interface RepairPacketVerificationInput {
  verification_id: string;
  command: string;
  exit_code: number | null;
  timed_out: boolean;
  stdout: string;
  stderr: string;
  status: "passed" | "failed";
}

export interface BuildRepairPacketInput {
  task_id: string;
  attempt_id: string;
  prior_worker_result: WorkerResult;
  verifications: RepairPacketVerificationInput[];
  operator_instruction?: string;
  evidence_filter?: string[];
}

export interface RepairTaskPacketFailedVerification {
  verification_id: string;
  command: string;
  exit_code: number | null;
  timed_out: boolean;
  stdout_excerpt: string;
  stderr_excerpt: string;
}

export interface RepairTaskPacketPassedVerification {
  verification_id: string;
  command: string;
}

export interface RepairTaskPacket {
  schema: "runway.repair_task_packet.v1";
  task_id: string;
  attempt_id: string;
  role: "repair";
  prior_diff_ref: string;
  prior_worker_summary: string;
  failed_verifications: RepairTaskPacketFailedVerification[];
  passed_verifications: RepairTaskPacketPassedVerification[];
  operator_instruction?: string;
  scope_lock_instruction: string;
}

export function buildRepairPacket(
  input: BuildRepairPacketInput,
): RepairTaskPacket {
  const priorDiffRef = String(
    input.prior_worker_result.evidence?.patch_ref ?? "",
  );

  const filter = input.evidence_filter;
  const failed: RepairTaskPacketFailedVerification[] = [];
  const passed: RepairTaskPacketPassedVerification[] = [];

  for (const v of input.verifications) {
    const isFailed =
      v.status === "failed" && (!filter || filter.includes(v.verification_id));
    if (isFailed) {
      failed.push({
        verification_id: v.verification_id,
        command: v.command,
        exit_code: v.exit_code,
        timed_out: v.timed_out,
        stdout_excerpt: excerptForRepair(v.stdout, REPAIR_EXCERPT_BYTES),
        stderr_excerpt: excerptForRepair(v.stderr, REPAIR_EXCERPT_BYTES),
      });
    } else {
      passed.push({
        verification_id: v.verification_id,
        command: v.command,
      });
    }
  }

  const packet: RepairTaskPacket = {
    schema: "runway.repair_task_packet.v1",
    task_id: input.task_id,
    attempt_id: input.attempt_id,
    role: "repair",
    prior_diff_ref: priorDiffRef,
    prior_worker_summary: input.prior_worker_result.summary,
    failed_verifications: failed,
    passed_verifications: passed,
    scope_lock_instruction: SCOPE_LOCK,
  };

  if (input.operator_instruction !== undefined) {
    packet.operator_instruction = input.operator_instruction;
  }

  return packet;
}
