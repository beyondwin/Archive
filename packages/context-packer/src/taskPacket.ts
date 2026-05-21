import { createHash } from "node:crypto";
import type { FailureClass, ProviderRole, RiskLevel, WaygentTaskPacket } from "@waygent/contracts";
import type { FileClaim } from "@waygent/runway-control";

export interface TaskPacketTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verification_commands: string[];
}

export interface BuildTaskPacketInput {
  run_id: string;
  task: TaskPacketTaskInput;
  role: ProviderRole;
  plan_excerpt: string;
  spec_excerpt: string;
  checkpoint_inputs?: string[];
  previous_failures?: Array<{ failure_class: FailureClass; evidence_refs: string[]; summary: string }>;
  decisions?: Array<{ decision_id: string; summary: string }>;
  max_chars?: number;
}

export function buildTaskPacket(input: BuildTaskPacketInput): WaygentTaskPacket {
  const maxChars = input.max_chars ?? 60000;
  const base: Omit<WaygentTaskPacket, "context_budget" | "sha256"> = {
    schema: "waygent.task_packet.v1",
    run_id: input.run_id,
    task_id: input.task.id,
    role: input.role,
    task_title: input.task.title,
    plan_excerpt: input.plan_excerpt,
    spec_excerpt: input.spec_excerpt,
    file_claims: input.task.file_claims,
    allowed_write_globs: input.task.file_claims.filter((claim) => claim.mode !== "read_only").map((claim) => claim.path),
    forbidden_write_globs: [".git/**", "node_modules/**", "native/kernel/target/**", "components/agentlens/.venv/**"],
    dependencies: input.task.dependencies,
    checkpoint_inputs: input.checkpoint_inputs ?? [],
    acceptance_commands: input.task.verification_commands,
    verification_commands: input.task.verification_commands,
    risk: input.task.risk,
    previous_failures: input.previous_failures ?? [],
    decisions: input.decisions ?? []
  };
  const estimatedChars = stableStringify(base).length;
  const packetWithoutHash: Omit<WaygentTaskPacket, "sha256"> = {
    ...base,
    context_budget: {
      estimated_chars: estimatedChars,
      max_chars: maxChars,
      status: estimatedChars > maxChars ? "red" : estimatedChars > maxChars * 0.7 ? "yellow" : "green"
    }
  };
  const sha256 = createHash("sha256").update(stableStringify(packetWithoutHash)).digest("hex");
  return { ...packetWithoutHash, sha256 };
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
