import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { writeArtifact } from "@waygent/lens-store";
import { reviewRun } from "../src/runCommands";
import { readRunStateV2, writeRunStateV2 } from "../src/runState";
import { baseV2State } from "./support/runStateFixture";

describe("manual review command", () => {
  test("writes review packets and task review artifacts for required tasks", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-review-run-"));
    const state = baseV2State({ root, run_id: "run_review_manual" });
    const packetArtifact = writeArtifact(state.run_root, "task_packets/task_a.json", `${JSON.stringify({
      schema: "waygent.task_packet.v1",
      run_id: state.run_id,
      task_id: "task_a",
      task_title: "Task A",
      plan_excerpt: "Implement task A",
      spec_excerpt: "Spec A",
      allowed_write_globs: ["a.txt"],
      forbidden_write_globs: [".git/**"]
    }, null, 2)}\n`);
    state.tasks.task_a = {
      ...state.tasks.task_a!,
      status: "verified",
      risk: "high",
      task_packet_path: join(state.run_root, packetArtifact.path),
      task_packet_sha256: packetArtifact.sha256,
      checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
      review_required: true,
      review_status: "pending"
    };
    state.verification = [{
      task_id: "task_a",
      kernel_result_ref: "artifacts/kernel/task_a.json",
      status: "passed"
    }];
    writeRunStateV2(root, state);

    const result = reviewRun({ root, run: state.run_id });

    expect(result).toMatchObject({
      command: "review",
      run_id: state.run_id,
      status: "passed",
      total_reviews: 2
    });
    expect(result.review_packet_refs).toHaveLength(2);
    const next = readRunStateV2(root, state.run_id);
    expect(next.tasks.task_a?.status).toBe("verified");
    expect(next.tasks.task_a?.review_status).toBe("passed");
    expect(next.reviews).toEqual([
      expect.objectContaining({ schema: "waygent.task_review.v1", role: "spec_reviewer", verdict: "approved" }),
      expect.objectContaining({ schema: "waygent.task_review.v1", role: "quality_reviewer", verdict: "approved" })
    ]);
    const packet = JSON.parse(readFileSync(join(state.run_root, result.review_packet_refs[0]!), "utf8")) as {
      schema: string;
      role: string;
      reviewed_patch_refs: string[];
      allowed_write_globs: string[];
    };
    expect(packet).toMatchObject({
      schema: "waygent.review_packet.v1",
      role: "spec_reviewer",
      reviewed_patch_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
      allowed_write_globs: []
    });
  });

  test("honors role filters and blocks budget-paused runs", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-review-role-"));
    const state = baseV2State({ root, run_id: "run_review_role" });
    state.tasks.task_a = {
      ...state.tasks.task_a!,
      status: "verified",
      risk: "high",
      checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.patch"],
      review_required: true,
      review_status: "pending"
    };
    writeRunStateV2(root, state);

    expect(reviewRun({ root, run: state.run_id, task: "task_a", role: "quality_reviewer" })).toMatchObject({
      status: "passed",
      total_reviews: 1,
      role: "quality_reviewer"
    });

    const paused = readRunStateV2(root, state.run_id);
    paused.apply = { status: "blocked", reason: "budget_paused" };
    writeRunStateV2(root, paused);

    expect(reviewRun({ root, run: state.run_id, task: "task_a" })).toMatchObject({
      status: "blocked",
      reason: "budget_paused"
    });
  });
});
