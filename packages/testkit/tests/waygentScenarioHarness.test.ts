import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { loadWaygentScenario, normalizeWaygentReplay } from "../src/waygentScenarioHarness";

describe("waygent scenario harness", () => {
  test("loads scenario fixtures with operational flags", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-scenario-fixture-"));
    const path = join(root, "scenario.json");
    writeFileSync(path, JSON.stringify({
      id: "dirty-apply-block",
      title: "Dirty source blocks apply",
      provider_fixture: "fake-success",
      source_dirty_before_apply: true,
      force_missing_checkpoint: false,
      plan: "```yaml waygent-task\nid: task_demo\ntitle: Demo\ndependencies: []\nfile_claims: []\nrisk: low\nverify:\n  - printf hello\n```",
      expected: {
        run_status: "trusted",
        apply_status: "blocked",
        event_types: ["platform.run_started"]
      }
    }));

    expect(loadWaygentScenario(path)).toMatchObject({
      id: "dirty-apply-block",
      provider_fixture: "fake-success",
      source_dirty_before_apply: true,
      force_missing_checkpoint: false,
      expected: {
        apply_status: "blocked"
      }
    });
  });

  test("normalizes replay output without unstable event ids or artifact paths", () => {
    const normalized = normalizeWaygentReplay({
      run_id: "run_demo",
      events: [
        {
          id: "event_run_demo_1",
          run_id: "run_demo",
          sequence: 1,
          event_type: "platform.run_started",
          timestamp: "2026-05-21T00:00:00.000Z",
          phase: "platform",
          outcome: "running",
          summary: "Run opened.",
          payload: { plan: "/tmp/random/plan.md" }
        },
        {
          id: "event_run_demo_2",
          run_id: "run_demo",
          sequence: 2,
          event_type: "runway.verification_result",
          timestamp: "2026-05-21T00:00:01.000Z",
          phase: "verify",
          outcome: "success",
          summary: "Verification passed.",
          payload: { checkpoint_ref: "checkpoint_task_demo_candidate_task_demo" }
        }
      ],
      trust_report: { trust_status: "trusted" },
      summary: { total_events: 2 },
      projection: { safe_wave: ["task_demo"] },
      apply_state: "not_applied"
    });

    expect(normalized).toEqual({
      run_status: "trusted",
      apply_status: "not_applied",
      total_events: 2,
      safe_wave: ["task_demo"],
      event_types: ["platform.run_started", "runway.verification_result"],
      checkpoints: ["checkpoint_task_demo_candidate_task_demo"]
    });
  });

  test("marks replay failed when a worker fixture reports failure", () => {
    const normalized = normalizeWaygentReplay({
      events: [
        {
          event_type: "runway.worker_result",
          payload: {
            worker: {
              status: "failed",
              failure_class: "adapter_crashed"
            }
          }
        }
      ],
      trust_report: { trust_status: "trusted" },
      summary: { total_events: 1 },
      projection: { safe_wave: ["task_provider"] },
      apply_state: "not_applied"
    });

    expect(normalized.run_status).toBe("failed");
  });
});
