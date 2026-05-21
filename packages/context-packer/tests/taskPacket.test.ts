import { describe, expect, test } from "bun:test";
import { buildTaskPacket } from "../src/taskPacket";

describe("Waygent task packets", () => {
  test("builds bounded provider context from task, spec, and failure evidence", () => {
    const packet = buildTaskPacket({
      run_id: "run_packet",
      task: {
        id: "task_a",
        title: "Update README",
        dependencies: [],
        file_claims: [{ path: "README.md", mode: "owned" }],
        risk: "low",
        verification_commands: ["test -f README.md"]
      },
      role: "implement",
      plan_excerpt: "Update README",
      spec_excerpt: "README must exist",
      previous_failures: [
        { failure_class: "verification_failed", evidence_refs: ["kernel/verify.json"], summary: "test failed" }
      ]
    });

    expect(packet.schema).toBe("waygent.task_packet.v1");
    expect(packet.allowed_write_globs).toEqual(["README.md"]);
    expect(packet.forbidden_write_globs).toContain(".git/**");
    expect(packet.previous_failures[0]?.failure_class).toBe("verification_failed");
    expect(packet.sha256).toMatch(/^[a-f0-9]{64}$/);
  });

  test("includes dependency checkpoint refs in task packets", () => {
    const packet = buildTaskPacket({
      run_id: "run_packet",
      task: {
        id: "task_dependent",
        title: "Use base checkpoint",
        dependencies: ["task_base"],
        file_claims: [{ path: "dependent.txt", mode: "owned" }],
        risk: "low",
        verification_commands: ["test -f dependent.txt"]
      },
      role: "implement",
      plan_excerpt: "Use base checkpoint",
      spec_excerpt: "",
      checkpoint_inputs: ["artifacts/checkpoints/task_base/candidate_task_base.json"]
    });

    expect(packet.checkpoint_inputs).toEqual(["artifacts/checkpoints/task_base/candidate_task_base.json"]);
  });
});
