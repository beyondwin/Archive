import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { recordSalvageArtifact } from "../src/salvageArtifacts";
import { baseV2State } from "./support/runStateFixture";

describe("recordSalvageArtifact", () => {
  test("writes salvage result and indexes it", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-salvage-artifact-"));
    const state = baseV2State({ root, run_id: "run_salvage" });
    const result = recordSalvageArtifact({
      state,
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      failure_class: "malformed_result",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff",
      changed_files: ["a.txt"],
      reason: null,
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
    });

    expect(result.artifact.path).toBe("artifacts/salvage/task_a/attempt_task_a_1.json");
    const written = JSON.parse(readFileSync(join(state.run_root, result.artifact.path), "utf8"));
    expect(written).toMatchObject({
      schema: "waygent.salvage_result.v1",
      task_id: "task_a",
      status: "salvaged_patch",
      patch_ref: "artifacts/worker/task_a/attempt_1_patch.diff"
    });
    expect(result.nextState.artifact_index).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          ref: "artifacts/salvage/task_a/attempt_task_a_1.json",
          producer_phase: "decision",
          task_id: "task_a"
        })
      ])
    );
    expect(result.nextState.recovery).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          task_id: "task_a",
          failure_class: "malformed_result",
          action: "salvage_then_review",
          salvage_ref: "artifacts/salvage/task_a/attempt_task_a_1.json"
        })
      ])
    );
  });

  test("records unsafe patch without marking it repairable", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-salvage-unsafe-"));
    const state = baseV2State({ root, run_id: "run_salvage_unsafe" });
    const result = recordSalvageArtifact({
      state,
      task_id: "task_a",
      attempt_id: "attempt_task_a_1",
      failure_class: "malformed_result",
      status: "unsafe_patch",
      patch_ref: null,
      changed_files: ["../escape.txt"],
      reason: "unsafe_patch_scope",
      evidence_refs: ["artifacts/provider/attempt_task_a_1.stdout.txt"]
    });

    expect(result.nextState.recovery.at(-1)).toMatchObject({
      task_id: "task_a",
      action: "request_decision",
      result: "blocked",
      reason: "unsafe_patch_scope"
    });
  });
});
