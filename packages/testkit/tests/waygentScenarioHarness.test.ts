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
      checkpoint_dry_run_conflict: false,
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
      checkpoint_dry_run_conflict: false,
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
          payload: {
            checkpoint_ref: "artifacts/checkpoints/task_demo/candidate_task_demo.json",
            patch_ref: "artifacts/checkpoints/task_demo/candidate_task_demo.patch"
          }
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
      checkpoints: [
        "artifacts/checkpoints/task_demo/candidate_task_demo.json",
        "artifacts/checkpoints/task_demo/candidate_task_demo.patch"
      ]
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

  test("prefers v2 state over successful-looking events for run and apply status", () => {
    const normalized = normalizeWaygentReplay({
      events: [
        {
          event_type: "runway.verification_result",
          outcome: "success",
          payload: {
            checkpoint_ref: "legacy_checkpoint_task_a",
            patch_ref: "artifacts/checkpoints/task_a/candidate_task_a.patch"
          }
        }
      ],
      trust_report: { trust_status: "trusted" },
      summary: { total_events: 1 },
      projection: { safe_wave: ["task_a"] },
      apply_state: "not_applied",
      run_state_v2: {
        status: "completed",
        completion_audit: { status: "failed" },
        apply: { status: "not_applied" },
        drift: { unrepaired_blockers: [] },
        tasks: {
          task_a: {
            checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"]
          }
        },
        provider_attempts: []
      } as any
    });

    expect(normalized.run_status).toBe("failed");
    expect(normalized.apply_status).toBe("not_ready");
    expect(normalized.checkpoints).toEqual(["artifacts/checkpoints/task_a/candidate_task_a.json"]);
    expect(normalized.combined_patch_ref).toBeNull();
  });

  test("normalizes checkpoint dry-run conflict fixtures as needs_rebase blockers", () => {
    const normalized = normalizeWaygentReplay({
      events: [{ event_type: "runway.apply_dry_run_result", outcome: "blocked", payload: {} }],
      trust_report: { trust_status: "trusted" },
      summary: { total_events: 1 },
      projection: { safe_wave: ["task_conflict"] },
      run_state_v2: {
        status: "blocked",
        completion_audit: { status: "failed" },
        apply: { status: "blocked", reason: "needs_rebase" },
        drift: { unrepaired_blockers: [] },
        tasks: {
          task_conflict: {
            checkpoint_refs: [],
            latest_failure_class: "needs_rebase"
          }
        },
        provider_attempts: []
      } as any
    }, { blockers: ["checkpoint_dry_run_conflict"] });

    expect(normalized.run_status).toBe("failed");
    expect(normalized.apply_status).toBe("blocked");
    expect(normalized.checkpoints).toEqual([]);
    expect(normalized.failure_classes).toEqual(["needs_rebase"]);
    expect(normalized.blockers).toEqual(["checkpoint_dry_run_conflict"]);
  });

  test("normalizes v2 state checkpoint refs, combined patch evidence, and provider attempts", () => {
    const normalized = normalizeWaygentReplay({
      events: [
        {
          event_type: "runway.worker_result",
          payload: {
            worker: { status: "success" }
          }
        }
      ],
      trust_report: { trust_status: "trusted" },
      summary: { total_events: 1 },
      projection: { safe_wave: ["task_a"] },
      run_state_v2: {
        status: "completed",
        completion_audit: {
          status: "passed",
          combined_apply_evidence: {
            status: "passed",
            checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"],
            patch_ref: "artifacts/checkpoints/apply/run_ready.patch",
            patch_sha256: "a".repeat(64),
            patch_byte_length: 12,
            evidence_ref: "artifacts/checkpoints/apply-dry-run.json"
          }
        },
        apply: { status: "not_applied" },
        drift: { unrepaired_blockers: [] },
        tasks: {
          task_a: {
            checkpoint_refs: ["artifacts/checkpoints/task_a/candidate_task_a.json"]
          }
        },
        provider_attempts: [
          {
            attempt_id: "attempt_task_a_1",
            task_id: "task_a",
            provider: "fake",
            stdout_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
            stderr_ref: "artifacts/provider/attempt_task_a_1.stderr.txt",
            worker_result_ref: "artifacts/provider/attempt_task_a_1.worker.json",
            exit_code: 0,
            timed_out: false
          }
        ]
      } as any
    });

    expect(normalized.run_status).toBe("trusted");
    expect(normalized.apply_status).toBe("ready");
    expect(normalized.checkpoints).toEqual(["artifacts/checkpoints/task_a/candidate_task_a.json"]);
    expect(normalized.combined_patch_ref).toBe("artifacts/checkpoints/apply/run_ready.patch");
    expect(normalized.provider_attempts).toEqual([
      {
        attempt_id: "attempt_task_a_1",
        task_id: "task_a",
        provider: "fake",
        stdout_ref: "artifacts/provider/attempt_task_a_1.stdout.txt",
        stderr_ref: "artifacts/provider/attempt_task_a_1.stderr.txt",
        worker_result_ref: "artifacts/provider/attempt_task_a_1.worker.json",
        exit_code: 0,
        timed_out: false,
        failure_class: null
      }
    ]);
  });
});
