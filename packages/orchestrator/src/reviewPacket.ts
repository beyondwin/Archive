import { createHash } from "node:crypto";
import { isAbsolute, relative } from "node:path";
import type { TaskReviewArtifact, WaygentReviewPacket, WaygentRunStateV2 } from "@waygent/contracts";

export type ReviewRole = TaskReviewArtifact["role"];

export interface BuildReviewPacketInput {
  state: WaygentRunStateV2;
  task: WaygentRunStateV2["tasks"][string];
  role: ReviewRole;
  review_id: string;
  task_packet?: Record<string, unknown> | null;
  verification_refs: string[];
  worker_result_refs: string[];
  prior_review_refs: string[];
  reviewed_patch_refs: string[];
  max_chars?: number;
}

export function buildReviewPacket(input: BuildReviewPacketInput): WaygentReviewPacket {
  const maxChars = input.max_chars ?? 60_000;
  const base: Omit<WaygentReviewPacket, "context_budget" | "sha256"> = {
    schema: "waygent.review_packet.v1",
    run_id: input.state.run_id,
    task_id: input.task.id,
    review_id: input.review_id,
    role: input.role,
    task_title: nonEmpty(input.task_packet?.task_title) ?? input.task.id,
    task_packet_ref: taskPacketRef(input.state, input.task.task_packet_path),
    task_packet_sha256: input.task.task_packet_sha256,
    plan_excerpt: stringValue(input.task_packet?.plan_excerpt) ?? input.task.id,
    spec_excerpt: stringValue(input.task_packet?.spec_excerpt) ?? "",
    file_claims: input.task.file_claims,
    allowed_write_globs: [],
    forbidden_write_globs: stringArray(input.task_packet?.forbidden_write_globs) ?? [".git/**", "node_modules/**", "native/kernel/target/**"],
    verification_refs: unique(input.verification_refs),
    worker_result_refs: unique(input.worker_result_refs),
    prior_review_refs: unique(input.prior_review_refs),
    reviewed_patch_refs: unique(input.reviewed_patch_refs),
    review_instructions: reviewInstructions(input.role)
  };
  const estimatedChars = stableStringify(base).length;
  const packetWithoutHash: Omit<WaygentReviewPacket, "sha256"> = {
    ...base,
    context_budget: {
      estimated_chars: estimatedChars,
      max_chars: maxChars,
      status: estimatedChars > maxChars ? "red" : estimatedChars > maxChars * 0.7 ? "yellow" : "green"
    }
  };
  return {
    ...packetWithoutHash,
    sha256: createHash("sha256").update(stableStringify(packetWithoutHash)).digest("hex")
  };
}

function reviewInstructions(role: ReviewRole): string[] {
  if (role === "spec_reviewer") {
    return [
      "Check whether the reviewed patch satisfies the task packet and spec excerpt.",
      "Return a waygent.task_review.v1 artifact with concrete issues when the implementation does not match the requested behavior.",
      "Do not edit files during review."
    ];
  }
  return [
    "Check maintainability, local patterns, tests, and evidence quality for the reviewed patch.",
    "Return a waygent.task_review.v1 artifact with concrete issues when the implementation needs repair.",
    "Do not edit files during review."
  ];
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter((value) => value.length > 0))];
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function stringArray(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

function taskPacketRef(state: WaygentRunStateV2, taskPacketPath: string | null): string | null {
  if (!taskPacketPath) return null;
  const ref = relative(state.run_root, taskPacketPath);
  return ref.length > 0 && !ref.startsWith("..") && !isAbsolute(ref) ? ref : taskPacketPath;
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify((value as Record<string, unknown>)[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
