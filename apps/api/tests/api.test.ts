import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { appendEvent, runPaths } from "@waygent/lens-store";
import { buildRunEvent, inspectRun, readRunStateV2, runWaygentDemo, writeRunStateV2 } from "@waygent/orchestrator";
import { buildRunDetailModel } from "../../console/src/uiModel";
import { createApiHandler } from "../src/server";

const handler = createApiHandler();

async function get(path: string): Promise<Response> {
  return handler(new Request(`http://waygent.local${path}`));
}

describe("Waygent local API routes", () => {
  test("GET /healthz reports local API status", async () => {
    const response = await get("/healthz");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      ok: true,
      service: "waygent-local-api"
    });
  });

  test("GET /runs lists demo runs with apply and trust summaries", async () => {
    const response = await get("/runs");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.runs).toHaveLength(3);
    expect(body.runs[0]).toMatchObject({
      runId: "run_demo_trusted",
      status: "completed",
      trustVerdict: "trusted",
      applyStatus: "ready"
    });
  });

  test("GET /runs reads real Waygent run roots when runRoot is set", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-runs-"));
    await runWaygentDemo({ root, run_id: "run_api_real", workspace: initSourceCheckout("waygent-api-source-") });
    const realHandler = createApiHandler({ runRoot: root });

    const response = await realHandler(new Request("http://waygent.local/runs"));

    expect(await response.json()).toMatchObject({
      runs: [
        {
          run_id: "run_api_real",
          trust_status: "trusted",
          apply_status: "ready"
        }
      ]
    });
  });

  test("GET /runs/:runId exposes execution explanation for real v2 runs", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-explanation-"));
    await runWaygentDemo({ root, run_id: "run_api_explanation", workspace: initSourceCheckout("waygent-api-source-") });
    const realHandler = createApiHandler({ runRoot: root });

    const response = await realHandler(new Request("http://waygent.local/runs/run_api_explanation"));
    const detail = await response.json();

    expect(detail.execution_explanation).toMatchObject({
      schema: "waygent.execution_explanation.v1",
      run_id: "run_api_explanation"
    });
    expect(detail.operational_maturity).toMatchObject({
      schema: "waygent.operational_maturity.v1",
      dogfood_evidence: { schema: "waygent.dogfood_evidence.v1" },
      runtime_cost: { schema: "waygent.runtime_cost.v1" },
      provider_readiness: { schema: "waygent.provider_readiness.v1" }
    });
    expect(detail.dogfood_evidence).toEqual(detail.operational_maturity.dogfood_evidence);
    expect(detail.runtime_cost).toEqual(detail.operational_maturity.runtime_cost);
    expect(detail.provider_readiness).toEqual(detail.operational_maturity.provider_readiness);
    expect(Array.isArray(detail.execution_explanation.waves)).toBe(true);
    expect(Array.isArray(detail.execution_explanation.recommended_next_actions)).toBe(true);
  });

  test("GET /runs/:runId and console detail stay in parity with inspect v2 projection facts", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-parity-"));
    const runId = "run_api_parity";
    await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-source-") });
    appendEvent(runPaths(root, runId).events, buildRunEvent({
      run_id: runId,
      sequence: 999,
      event_type: "runway.safe_wave_selected",
      phase: "schedule",
      outcome: "success",
      summary: "Stale safe-wave event appended after state was written.",
      payload: { safe_wave: ["stale_event_task"] }
    }));
    const inspected = inspectRun({ root, run: runId });
    const state = inspected.state;
    expect(state).toBeDefined();
    const expectedSafeWave = inspected.execution_explanation?.waves[0]?.ready ?? [];
    const expectedCheckpointRefs = Object.values(state!.tasks).flatMap((task) => task.checkpoint_refs);
    const expectedCombinedPatchRef = state!.completion_audit?.combined_apply_evidence?.patch_ref ?? null;
    const realHandler = createApiHandler({ runRoot: root });

    const response = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
    const detail = await response.json();
    const consoleDetail = buildRunDetailModel(detail);

    expect(detail).toMatchObject({
      run_id: inspected.run_id,
      status: inspected.status,
      trust_status: inspected.trust_status
    });
    expect(detail.safe_wave).toEqual(expectedSafeWave);
    expect(detail.execution_explanation.waves[0].ready).toEqual(expectedSafeWave);
    expect(detail.apply_readiness).toMatchObject({
      status: "ready",
      checkpoint_refs: expectedCheckpointRefs,
      combined_patch_ref: expectedCombinedPatchRef,
      source: "run_state_v2"
    });
    expect(detail.provider_attempts).toHaveLength(state!.provider_attempts.length);
    expect(detail.verification).toHaveLength(state!.verification.length);
    expect(consoleDetail.safe_wave).toEqual(expectedSafeWave);
    expect(consoleDetail.apply_readiness?.checkpoint_refs).toEqual(expectedCheckpointRefs);
    expect(consoleDetail.apply_readiness?.combined_patch_ref).toBe(expectedCombinedPatchRef);
    expect(consoleDetail.provider_attempts).toHaveLength(state!.provider_attempts.length);
    expect(consoleDetail.verification).toHaveLength(state!.verification.length);
  });

  test("GET /runs and /runs/:runId prefer v2 apply readiness over successful verification events", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-v2-readiness-"));
    const runId = "run_not_ready";
    await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-source-") });
    const state = readRunStateV2(root, runId);
    writeRunStateV2(root, {
      ...state,
      status: "blocked",
      lifecycle_outcome: "blocked",
      tasks: Object.fromEntries(
        Object.entries(state.tasks).map(([taskId, task]) => [taskId, {
          ...task,
          status: "blocked",
          checkpoint_refs: [],
          latest_failure_class: "needs_rebase"
        }])
      ),
      apply: { status: "blocked", reason: "needs_rebase" },
      completion_audit: { status: "passed" }
    });
    const realHandler = createApiHandler({ runRoot: root });

    const listResponse = await realHandler(new Request("http://waygent.local/runs"));
    expect(await listResponse.json()).toMatchObject({
      runs: [
        {
          run_id: runId,
          status: "blocked",
          apply_status: "blocked"
        }
      ]
    });

    const detailResponse = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
    const detail = await detailResponse.json();
    expect(detail.status).toBe("blocked");
    expect(detail.apply_status).toBe("blocked");
    expect(detail.apply_readiness).toEqual({
      status: "blocked",
      reason: "needs_rebase",
      checkpoint_refs: [],
      combined_patch_ref: null,
      source: "run_state_v2"
    });
    expect(detail.apply).toEqual({
      status: "ready",
      reason: null
    });
  });

  test("GET /runs and /runs/:runId do not infer apply readiness without v2 state", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-missing-v2-"));
    const runId = "run_missing_v2";
    await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-source-") });
    rmSync(join(root, runId, "state.json"));
    const realHandler = createApiHandler({ runRoot: root });

    const listResponse = await realHandler(new Request("http://waygent.local/runs"));
    expect(await listResponse.json()).toMatchObject({
      runs: [
        {
          run_id: runId,
          apply_status: "not_ready"
        }
      ]
    });

    const detailResponse = await realHandler(new Request(`http://waygent.local/runs/${runId}`));
    const detail = await detailResponse.json();
    expect(detail.apply_status).toBe("not_ready");
    expect(detail.apply_readiness).toBeNull();
    expect(detail.apply).toEqual({
      status: "ready",
      reason: null
    });
  });

  test("GET /runs/:runId returns run detail sections for the console", async () => {
    const response = await get("/runs/run_demo_blocked");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.run.runId).toBe("run_demo_blocked");
    expect(body.tasks.map((task: { status: string }) => task.status)).toContain(
      "AWAITING_HUMAN_DECISION"
    );
    expect(body.decisionPackets[0]).toMatchObject({
      taskId: "task_verify",
      failureClass: "verification_failed"
    });
    expect(body.applyStatus).toMatchObject({
      state: "blocked",
      dirtySourceCheckout: true
    });
  });

  test("GET /runs/:runId includes v2 state evidence when present", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-api-v2-runs-"));
    const runId = "run_api_v2";
    await runWaygentDemo({ root, run_id: runId, workspace: initSourceCheckout("waygent-api-source-") });
    writeRunStateV2(root, {
      schema: "waygent.run_state.v2",
      run_id: runId,
      workspace: "/workspace",
      source_branch: "main",
      worktree_root: join(root, "worktrees", runId),
      run_root: join(root, runId),
      artifact_root: join(root, runId, "artifacts"),
      state_path: join(root, runId, "state.json"),
      event_journal_path: join(root, runId, "events.jsonl"),
      plan_path: "/workspace/plan.md",
      spec_path: "/workspace/spec.md",
      provider_profile: { provider: "codex" },
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "recover",
      tasks: {
        task_demo: {
          id: "task_demo",
          status: "blocked",
          risk: "medium",
          dependencies: [],
          file_claims: [{ path: "README.md", mode: "owned" }],
          attempts: ["attempt_task_demo_1"],
          task_packet_path: join(root, runId, "task_packets", "task_demo.json"),
          task_packet_sha256: "a".repeat(64),
          unit_manifest: { title: "Demo task" },
          checkpoint_refs: ["checkpoint_task_demo"],
          latest_failure_class: "verification_failed",
          decision_packet_ref: join(root, runId, "decisions", "task_demo.json"),
          timing: { started_at: "2026-05-21T00:00:00.000Z" }
        }
      },
      safe_waves: [
        {
          wave_id: "wave_1",
          ready: [],
          withheld: [{ task_id: "task_demo", reason: "verification_failed" }]
        }
      ],
      provider_attempts: [
        {
          schema: "runway.provider_attempt.v1",
          attempt_id: "attempt_task_demo_1",
          run_id: runId,
          task_id: "task_demo",
          role: "implement",
          provider: "codex",
          command: ["codex", "exec", "--json", "-"],
          cwd: join(root, "worktrees", runId),
          stdin_ref: "artifacts/provider/stdin.json",
          stdout_ref: "artifacts/provider/stdout.json",
          stderr_ref: "artifacts/provider/stderr.txt",
          event_stream_ref: null,
          exit_code: 0,
          timed_out: false,
          started_at: "2026-05-21T00:00:00.000Z",
          completed_at: "2026-05-21T00:01:00.000Z",
          worker_result_ref: "artifacts/provider/worker.json",
          failure_class: null,
          process: {
            stdout: "{}",
            stderr: "WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt",
            exit_code: 0,
            timed_out: false,
            started_at: "2026-05-21T00:00:00.000Z",
            completed_at: "2026-05-21T00:01:00.000Z",
            event_stream: null,
            stderr_summary: {
              total_lines: 1,
              counts: { error: 0, warning: 0, mcp: 0, plugin_manifest: 1, skill_loader: 0, other: 0 },
              samples: [{ category: "plugin_manifest", line: "ignoring interface.defaultPrompt" }]
            }
          }
        }
      ],
      reviews: [
        {
          schema: "runway.review_result.v1",
          run_id: runId,
          task_id: "task_demo",
          attempt_id: "review_task_demo_1",
          provider: "claude",
          verdict: "needs_fix",
          spec_score: 0.5,
          quality_score: 0.6,
          findings: [{ severity: "important", file: "README.md", line: 1, summary: "Needs verification evidence." }],
          residual_risk: ["verification incomplete"],
          summary: "Review requires a fix."
        }
      ],
      verification: [
        {
          verification_id: "verify_task_demo_1",
          task_id: "task_demo",
          command: "bun test",
          exit_code: 1,
          status: "failed"
        }
      ],
      recovery: [
        {
          task_id: "task_demo",
          failure_class: "verification_failed",
          allowed_actions: ["rerun_verification"],
          blocked_actions: ["apply"],
          recommended_next_action: "rerun_verification"
        }
      ],
      apply: { status: "blocked", reason: "verification_failed", checkpoint_ref: "checkpoint_task_demo" },
      context: { snapshot_path: null, basis_hash: null },
      drift: {
        last_checked_at: "2026-05-21T00:02:00.000Z",
        records: [{ status: "checked" }],
        unrepaired_blockers: [{ failure_class: "state_drift" }]
      },
      completion_audit: null,
      timestamps: {
        started_at: "2026-05-21T00:00:00.000Z",
        updated_at: "2026-05-21T00:02:00.000Z",
        completed_at: null
      }
    });
    const realHandler = createApiHandler({ runRoot: root });

    const response = await realHandler(new Request(`http://waygent.local/runs/${runId}`));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.provider_attempts[0]).toMatchObject({
      attempt_id: "attempt_task_demo_1",
      task_id: "task_demo",
      provider: "codex"
    });
    expect(body.provider_attempts[0].process.stderr_summary.counts.plugin_manifest).toBeGreaterThanOrEqual(1);
    expect(body.execution_explanation.recommended_next_actions).toBeArray();
    expect(body.verification[0]).toMatchObject({
      verification_id: "verify_task_demo_1",
      status: "failed"
    });
    expect(body.reviews[0]).toMatchObject({
      verdict: "needs_fix",
      summary: "Review requires a fix."
    });
    expect(body.recovery[0]).toMatchObject({
      recommended_next_action: "rerun_verification"
    });
    expect(body.task_packets[0]).toMatchObject({
      task_id: "task_demo",
      task_packet_sha256: "a".repeat(64)
    });
    expect(body.apply_readiness).toMatchObject({
      status: "blocked",
      reason: "state_drift",
      checkpoint_refs: ["checkpoint_task_demo"],
      combined_patch_ref: null,
      source: "run_state_v2"
    });
    expect(body.drift.unrepaired_blockers[0]).toMatchObject({
      failure_class: "state_drift"
    });
  });

  test("GET /runs/:runId/events returns ordered events", async () => {
    const response = await get("/runs/run_demo_trusted/events");
    expect(response.status).toBe(200);
    const body = await response.json();

    expect(body.events.map((event: { eventType: string }) => event.eventType)).toEqual([
      "platform.run_started",
      "runway.safe_wave_selected",
      "runway.worker_result",
      "lens.trust_report_updated"
    ]);
  });

  test("GET /runs/:runId/trust and /failures return projections", async () => {
    const trustResponse = await get("/runs/run_demo_failed/trust");
    expect(trustResponse.status).toBe(200);
    expect(await trustResponse.json()).toMatchObject({
      trust: { verdict: "failed" }
    });

    const failuresResponse = await get("/runs/run_demo_failed/failures");
    expect(failuresResponse.status).toBe(200);
    const body = await failuresResponse.json();
    expect(body.failures[0]).toMatchObject({
      taskId: "task_worker",
      failureClass: "adapter_crashed",
      recoveryAction: "switch_provider"
    });
  });

  test("unknown routes and runs return JSON 404 responses", async () => {
    expect((await get("/missing")).status).toBe(404);

    const missingRun = await get("/runs/nope");
    expect(missingRun.status).toBe(404);
    expect(await missingRun.json()).toEqual({
      error: "run_not_found",
      runId: "nope"
    });
  });
});

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  for (const args of [
    ["init", "-q"],
    ["config", "user.email", "test@example.com"],
    ["config", "user.name", "Waygent"],
    ["add", "-A"],
    ["commit", "-q", "-m", "init"]
  ]) {
    const result = Bun.spawnSync(["git", ...args], { cwd: workspace });
    if (result.exitCode !== 0) throw new Error(`git ${args.join(" ")} failed`);
  }
  return workspace;
}
