import { describe, expect, test } from "bun:test";
import type { WaygentTaskPacket } from "@waygent/contracts";
import { evaluateContextBudget } from "../src/contextBudgetGate";

function packet(status: "green" | "yellow" | "red"): WaygentTaskPacket {
  return {
    schema: "waygent.task_packet.v1",
    run_id: "run_context_gate",
    task_id: "task_context_gate",
    role: "implement",
    task_title: "Task",
    plan_excerpt: "Plan",
    spec_excerpt: "Spec",
    file_claims: [],
    allowed_write_globs: [],
    forbidden_write_globs: [],
    dependencies: [],
    checkpoint_inputs: [],
    acceptance_commands: ["printf hello"],
    verification_commands: ["printf hello"],
    risk: "low",
    previous_failures: [],
    decisions: [],
    context_budget: { estimated_chars: 1, max_chars: 10, status },
    sha256: "hash"
  };
}

describe("evaluateContextBudget", () => {
  test("allows green packets", () => {
    expect(evaluateContextBudget(packet("green"))).toMatchObject({ status: "allow", failure_class: null });
  });

  test("warns on yellow packets", () => {
    expect(evaluateContextBudget(packet("yellow"))).toMatchObject({ status: "warn", failure_class: null });
  });

  test("blocks red packets with context_missing", () => {
    const decision = evaluateContextBudget(packet("red"));

    expect(decision.status).toBe("block");
    expect(decision.failure_class).toBe("context_missing");
    expect(decision.shrink_actions).toContain("replace_full_spec_with_mapped_sections");
  });
});
