import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runWaygent, readRunStateV2 } from "@waygent/orchestrator";
import { normalizeProcessOutput } from "@waygent/provider-adapters";
import { projectOperatorDecisionFromState, projectTrustReport } from "@waygent/lens-projectors";
import { readEvents } from "@waygent/lens-store";

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "before\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}

function fixture(name: string): string {
  return readFileSync(join(import.meta.dir, "..", "fixtures", "waygent-lab", name), "utf8");
}

describe("Waygent Fixture-Lab", () => {
  test("recoverable prose plan starts and records intake artifacts", async () => {
    const workspace = initSourceCheckout("waygent-lab-recoverable-");
    const root = mkdtempSync(join(tmpdir(), "waygent-lab-recoverable-root-"));
    mkdirSync(join(workspace, "docs", "superpowers", "plans"), { recursive: true });
    writeFileSync(join(workspace, "docs", "superpowers", "plans", "recoverable.md"), fixture("recoverable-prose-plan.md"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_lab_recoverable",
      plan_path: "recoverable.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_lab_recoverable");
    const events = readEvents(join(root, "run_lab_recoverable", "events.jsonl"));
    const operator = projectOperatorDecisionFromState({ state, events });

    expect(state.intake_recovery?.status).toBe("recovered");
    expect(operator.intake_recovery?.status).toBe("recovered");
    expect(operator.evidence_packet.artifact_refs).toContain("artifacts/intake/recovery-report.json");
  });

  test("unsafe plan asks for user decision and never dispatches a worker", async () => {
    const workspace = initSourceCheckout("waygent-lab-unsafe-");
    const root = mkdtempSync(join(tmpdir(), "waygent-lab-unsafe-root-"));
    writeFileSync(join(workspace, "unsafe.md"), fixture("unsafe-destructive-plan.md"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_lab_unsafe",
      plan_path: "unsafe.md",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_lab_unsafe");
    const events = readEvents(join(root, "run_lab_unsafe", "events.jsonl"));
    const operator = projectOperatorDecisionFromState({ state, events });

    expect(events.map((event) => event.event_type)).not.toContain("runway.worker_result");
    expect(state.intake_recovery?.status).toBe("decision_required");
    expect(operator.primary_blocker?.code).toBe("intake_decision_required");
  });

  test("malformed provider fixture still normalizes worker result from second json fence", () => {
    const output = normalizeProcessOutput("claude", "task_demo", "candidate_task_demo", {
      exitCode: 0,
      stdout: fixture("malformed-provider-with-worker-result.stdout.txt"),
      stderr: "",
      timedOut: false,
      startedAt: "2026-05-23T00:00:00.000Z",
      completedAt: "2026-05-23T00:00:01.000Z"
    });

    expect(output.worker).toMatchObject({
      task_id: "task_demo",
      status: "completed",
      summary: "Recovered worker JSON from second fence."
    });
  });

  test("stale verification failure stays recovered after a later pass and review evidence", async () => {
    const workspace = initSourceCheckout("waygent-lab-stale-verification-");
    const root = mkdtempSync(join(tmpdir(), "waygent-lab-stale-verification-root-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_lab_stale_verification",
      plan: "```yaml waygent-task\nid: task_stale_fixture\ntitle: Stale verification fixture\ndependencies: []\nfile_claims:\n  - path: stale.txt\n    mode: owned\nrisk: low\nverify:\n  - printf stale\n```",
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_lab_stale_verification");
    state.verification = [
      {
        verification_id: "verify_task_stale_fixture_stale_failure",
        task_id: "task_stale_fixture",
        command: "printf stale",
        status: "failed",
        verified_at: "2026-05-26T00:00:00.000Z",
        failure_class: "verification_failed",
        kernel_result_ref: "artifacts/kernel/task_stale_fixture-stale-failure.json"
      },
      ...state.verification
    ];
    state.recovered_failures = [{
      task_id: "task_stale_fixture",
      failure_class: "verification_failed",
      recovered_at: "2026-05-26T00:01:00.000Z",
      evidence_refs: ["verification_id:verify_task_stale_fixture_stale_failure"]
    }];
    state.reviews = [{
      schema: "waygent.task_review.v1",
      run_id: "run_lab_stale_verification",
      task_id: "task_stale_fixture",
      review_id: "review_task_stale_fixture_quality_1",
      role: "quality_reviewer",
      status: "passed",
      verdict: "approved",
      findings: [],
      residual_risk: [],
      reviewed_patch_refs: state.tasks.task_stale_fixture?.checkpoint_refs ?? [],
      model: "fixture-reviewer",
      reviewed_at: "2026-05-26T00:02:00.000Z"
    }];
    state.completion_audit = {
      ...(state.completion_audit ?? {}),
      status: "passed",
      review_evidence: state.reviews
    };

    const events = readEvents(join(root, "run_lab_stale_verification", "events.jsonl"));
    const trust = projectTrustReport(events, state);
    const operator = projectOperatorDecisionFromState({ state, events });

    expect(trust.trust_status).toBe("trusted");
    expect(trust.recovered_failure_count).toBeGreaterThanOrEqual(1);
    expect(operator.primary_blocker?.code ?? null).toBeNull();
    expect(operator.allowed_actions.map((action) => action.id)).toContain("apply_run");
  });

  test("recovered malformed Codex JSONL still returns the later worker result", () => {
    const stdout = [
      JSON.stringify({ type: "thread.started", thread_id: "session_recovered_malformed" }),
      JSON.stringify({ type: "item.completed", item: { type: "agent_message", text: "{not json" } }),
      JSON.stringify({
        type: "item.completed",
        item: {
          type: "agent_message",
          text: JSON.stringify({
            schema: "runway.worker_result.v1",
            task_id: "task_demo",
            candidate_id: "candidate_task_demo",
            status: "completed",
            changed_files: ["recovered.txt"],
            summary: "Recovered worker JSON from later Codex item.",
            evidence: { command: "codex-jsonl" }
          })
        }
      })
    ].join("\n");

    const output = normalizeProcessOutput("codex", "task_demo", "candidate_task_demo", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      startedAt: "2026-05-26T00:00:00.000Z",
      completedAt: "2026-05-26T00:00:01.000Z"
    });

    expect(output.worker).toMatchObject({
      task_id: "task_demo",
      status: "completed",
      changed_files: ["recovered.txt"],
      summary: "Recovered worker JSON from later Codex item."
    });
    expect(output.worker.evidence.session_id).toBe("session_recovered_malformed");
  });
});
