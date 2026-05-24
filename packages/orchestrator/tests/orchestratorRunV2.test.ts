import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { validateContract, type ReviewResult } from "@waygent/contracts";
import { readLatestRunId } from "@waygent/lens-store";
import { runWaygent } from "../src/orchestrator";
import { readRunStateV2 } from "../src/runState";

const plan = `
\`\`\`yaml waygent-task
id: task_a
title: Create file A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

describe("runWaygent v2 lifecycle", () => {
  test("creates v2 state, task packet, real verification evidence, and completion audit", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "waygent-run-v2-workspace-"));
    Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
    Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
    writeFileSync(join(workspace, "README.md"), "fixture\n");
    Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
    Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-"));

    await runWaygent({
      root,
      workspace,
      run_id: "run_v2",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_v2");
    expect(validateContract("waygent.run_state.v2", state)).toEqual(state);
    expect(state.schema).toBe("waygent.run_state.v2");
    expect(state.tasks.task_a?.task_packet_path).toBeTruthy();
    expect(state.tasks.task_a?.checkpoint_refs[0]).toContain("artifacts/checkpoints/task_a/candidate_task_a.json");
    expect(state.provider_attempts).toHaveLength(1);
    expect(state.verification.length).toBeGreaterThan(0);
    expect(state.completion_audit).toMatchObject({
      status: "passed",
      checkpoint_evidence: [expect.objectContaining({ ok: true })]
    });
    expect(state.preflight).toMatchObject({ status: "clean", reason: null, decision_packet_ref: null });
    expect(readLatestRunId(root)).toBe("run_v2");
  });

  test("passes completion audit when a read-only final verification task has no checkpoint", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-readonly-final-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-readonly-final-"));
    const planWithReadOnlyFinal = `
\`\`\`yaml waygent-task
id: task_a
title: Create file A
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`

\`\`\`yaml waygent-task
id: task_final_verification
title: Verify final state
dependencies:
  - task_a
file_claims:
  - path: README.md
    mode: read_only
risk: low
verify:
  - git diff --check
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_readonly_final",
      plan: planWithReadOnlyFinal,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_readonly_final");
    expect(state.status).toBe("completed");
    expect(state.tasks.task_final_verification?.checkpoint_refs).toEqual([]);
    expect(state.completion_audit).toMatchObject({
      status: "passed",
      combined_apply_evidence: expect.objectContaining({ status: "passed" })
    });
  });

  test("blocks dirty related source checkout before provider dispatch", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-dirty-related-source-");
    writeFileSync(join(workspace, "a.txt"), "dirty source evidence\n");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-dirty-related-"));

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_dirty_related",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dirty_related");
    expect(state).toMatchObject({
      status: "blocked",
      lifecycle_outcome: "blocked",
      current_phase: "preflight",
      apply: { status: "blocked", reason: "dirty_source_checkout" },
      preflight: {
        status: "dirty_related",
        dirty_files: ["a.txt"],
        related: ["a.txt"],
        reason: "dirty_source_checkout",
        decision_packet_ref: null
      }
    });
    expect(state.provider_attempts).toEqual([]);
    expect(result.events.find((event) => event.event_type === "runway.preflight_result")).toMatchObject({
      outcome: "blocked",
      payload: { status: "dirty_related", reason: "dirty_source_checkout" }
    });
    expect(result.events.some((event) => event.event_type === "runway.worker_result")).toBe(false);
    expect(readLatestRunId(root)).toBe("run_dirty_related");
  });

  test("records dirty unrelated preflight warning and proceeds", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-dirty-unrelated-source-");
    writeFileSync(join(workspace, "notes.md"), "operator note\n");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-dirty-unrelated-"));

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_dirty_unrelated",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dirty_unrelated");
    expect(state.status).toBe("completed");
    expect(state.provider_attempts).toHaveLength(1);
    expect(state.preflight).toMatchObject({
      status: "dirty_unrelated",
      dirty_files: ["notes.md"],
      related: [],
      unrelated: ["notes.md"],
      reason: "dirty_unrelated_source_checkout",
      decision_packet_ref: null
    });
    expect(result.events.find((event) => event.event_type === "runway.preflight_result")).toMatchObject({
      outcome: "success",
      severity: "warning",
      payload: { status: "dirty_unrelated", reason: "dirty_unrelated_source_checkout" }
    });
  });

  test("refuses to overwrite existing run evidence for a duplicate run id", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-duplicate-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-duplicate-"));
    const runRoot = join(root, "run_duplicate");
    mkdirSync(runRoot, { recursive: true });
    const eventJournal = join(runRoot, "events.jsonl");
    writeFileSync(eventJournal, "existing evidence\n");

    await expect(runWaygent({
      root,
      workspace,
      run_id: "run_duplicate",
      plan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    })).rejects.toThrow("run_id_already_exists");

    expect(existsSync(runRoot)).toBe(true);
    expect(readFileSync(eventJournal, "utf8")).toBe("existing evidence\n");
  });

  test("passes dependency checkpoint refs into dependent task packets", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-dependent-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-dependent-"));
    const dependentPlan = `
\`\`\`yaml waygent-task
id: task_base
title: Create base file
dependencies: []
file_claims:
  - path: base.txt
    mode: owned
risk: low
verify:
  - test -f base.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_dependent
title: Create dependent file
dependencies: [task_base]
file_claims:
  - path: dependent.txt
    mode: owned
risk: low
verify:
  - test -f dependent.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_dependent",
      plan: dependentPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_dependent");
    const packetPath = state.tasks.task_dependent?.task_packet_path;
    expect(packetPath).toBeTruthy();
    const packet = JSON.parse(readFileSync(packetPath!, "utf8")) as { checkpoint_inputs?: string[] };
    expect(packet.checkpoint_inputs).toEqual(["artifacts/checkpoints/task_base/candidate_task_base.json"]);
  });

  test("passes transitive checkpoint refs into dependent task packets and worktrees", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-transitive-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-transitive-"));
    const transitivePlan = `
\`\`\`yaml waygent-task
id: task_base
title: Create base file
dependencies: []
file_claims:
  - path: base.txt
    mode: owned
risk: low
verify:
  - test -f base.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_middle
title: Create middle file
dependencies: [task_base]
file_claims:
  - path: middle.txt
    mode: owned
risk: low
verify:
  - test -f base.txt && test -f middle.txt
\`\`\`
\`\`\`yaml waygent-task
id: task_final
title: Create final file
dependencies: [task_middle]
file_claims:
  - path: final.txt
    mode: owned
risk: low
verify:
  - test -f base.txt && test -f middle.txt && test -f final.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_transitive",
      plan: transitivePlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_transitive");
    expect(state.status).toBe("completed");
    const packetPath = state.tasks.task_final?.task_packet_path;
    expect(packetPath).toBeTruthy();
    const packet = JSON.parse(readFileSync(packetPath!, "utf8")) as { checkpoint_inputs?: string[] };
    expect(packet.checkpoint_inputs).toEqual([
      "artifacts/checkpoints/task_base/candidate_task_base.json",
      "artifacts/checkpoints/task_middle/candidate_task_middle.json"
    ]);
  });

  test("blocks checkpoint sealing when actual worktree changes escape allowed scope", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-diff-scope-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-diff-scope-"));
    const leakyProvider = writeLeakyProviderScript(root);
    const leakingPlan = `
\`\`\`yaml waygent-task
id: task_scope
title: Create file and leak another
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_diff_scope",
      plan: leakingPlan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        codex: {
          executable: process.execPath,
          args: [leakyProvider]
        }
      }
    });

    const state = readRunStateV2(root, "run_diff_scope");
    expect(state.tasks.task_scope).toMatchObject({
      status: "blocked",
      latest_failure_class: "diff_scope_failed",
      checkpoint_refs: []
    });
    expect(result.events.find((event) => event.event_type === "runway.diff_scope_result")).toMatchObject({
      outcome: "blocked",
      payload: {
        task_id: "task_scope",
        failure_class: "diff_scope_failed",
        reason: "changed_file_outside_allowed_globs",
        changed_files: ["a.txt", "secrets.txt"]
      }
    });
  });

  test("provider capability probe failures do not project a successful run as blocked", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-probe-failed-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-probe-failed-"));
    const provider = writeHelpFailingCodexProviderScript(root);
    const createPlan = `
\`\`\`yaml waygent-task
id: task_probe
title: Create file after failed probe
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_probe_failed",
      plan: createPlan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        codex: {
          executable: provider,
          args: ["exec", "--json", "-"]
        }
      }
    });

    const state = readRunStateV2(root, "run_probe_failed");
    const capabilityEvent = result.events.find((event) => event.event_type === "platform.provider_capability_attested");

    expect(state.status).toBe("completed");
    expect(capabilityEvent).toMatchObject({
      outcome: "success",
      trust_impact: "requires_review",
      payload: {
        provider_capabilities: [
          expect.objectContaining({ reason: "probe_failed" })
        ]
      }
    });
  });

  test("schedules recovery retry for malformed worker result before completing run", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-recovery-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-recovery-"));
    const provider = writeRecoveringMalformedProviderScript(root);
    const retryPlan = `
\`\`\`yaml waygent-task
id: task_retry
title: Create file after recovery
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: low
verify:
  - test -f a.txt
\`\`\`
`;

    const result = await runWaygent({
      root,
      workspace,
      run_id: "run_recovery_retry",
      plan: retryPlan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: { codex: { executable: provider, args: [] } },
      initial_reviews: [reviewResult("run_recovery_retry", "task_retry", "candidate_task_retry")]
    });

    const state = readRunStateV2(root, "run_recovery_retry");
    expect(state.recovery.some((record) =>
      record.task_id === "task_retry" &&
      record.failure_class === "malformed_result" &&
      record.action === "retry_with_strict_prompt"
    )).toBe(true);
    expect(result.events.some((event) => event.event_type === "runway.recovery_scheduled")).toBe(true);
    expect(state.status).toBe("completed");
    expect(state.completion_audit?.status).toBe("passed");
  });

  test("blocks completion audit for high-risk tasks without review evidence", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-high-risk-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-high-risk-"));
    const highRiskPlan = `
\`\`\`yaml waygent-task
id: task_high
title: Create high-risk file
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: high
verify:
  - test -f a.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_high_risk_no_review",
      plan: highRiskPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" }
    });

    const state = readRunStateV2(root, "run_high_risk_no_review");
    expect(state.status).toBe("blocked");
    expect(state.completion_audit?.status).toBe("failed");
    expect(state.completion_audit?.residual_risk).toContain("review_evidence:high_risk_task");
  });

  test("passes completion audit for high-risk tasks with review evidence", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-high-risk-reviewed-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-high-risk-reviewed-"));
    const highRiskPlan = `
\`\`\`yaml waygent-task
id: task_high
title: Create high-risk file
dependencies: []
file_claims:
  - path: a.txt
    mode: owned
risk: high
verify:
  - test -f a.txt
\`\`\`
`;

    await runWaygent({
      root,
      workspace,
      run_id: "run_high_risk_reviewed",
      plan: highRiskPlan,
      profile: { provider: "fake", execution_mode: "multi-agent" },
      initial_reviews: [reviewResult("run_high_risk_reviewed", "task_high", "candidate_task_high")]
    });

    const state = readRunStateV2(root, "run_high_risk_reviewed");
    expect(state.status).toBe("completed");
    expect(state.completion_audit?.review_evidence).toHaveLength(1);
    expect(state.completion_audit?.residual_risk ?? []).not.toContain("review_evidence:high_risk_task");
  });

  test("blocks terminal completion when required method evidence is missing", async () => {
    const workspace = initSourceCheckout("waygent-run-v2-method-evidence-source-");
    const root = mkdtempSync(join(tmpdir(), "waygent-run-v2-method-evidence-"));
    const provider = writeNoMethodEvidenceProviderScript(root);

    await runWaygent({
      root,
      workspace,
      run_id: "run_method_evidence_missing",
      plan,
      profile: { provider: "codex", execution_mode: "multi-agent" },
      provider_processes: {
        codex: {
          executable: process.execPath,
          args: ["-e", provider]
        }
      },
      require_method_evidence: true
    });

    const state = readRunStateV2(root, "run_method_evidence_missing");
    expect(state.tasks.task_a).toMatchObject({ status: "verified" });
    expect(state).toMatchObject({
      status: "blocked",
      lifecycle_outcome: "blocked",
      completion_audit: {
        status: "failed",
        terminal_invariant: {
          passed: false,
          blockers: expect.arrayContaining([
            expect.objectContaining({ code: "method_evidence_missing", task_id: "task_a" })
          ])
        }
      }
    });
  });
});

function writeLeakyProviderScript(root: string): string {
  const scriptPath = join(root, "leaky-provider.mjs");
  writeFileSync(scriptPath, `
import { writeFileSync } from "node:fs";

writeFileSync("a.txt", "allowed\\n");
writeFileSync("secrets.txt", "leak\\n");
process.stdout.write(JSON.stringify({
  schema: "runway.worker_result.v1",
  task_id: "task_scope",
  candidate_id: "candidate_task_scope",
  status: "completed",
  changed_files: ["a.txt", "secrets.txt"],
  summary: "Created an allowed file and an out-of-scope file.",
  evidence: { provider: "test-leaky-provider" }
}));
`);
  return scriptPath;
}

function writeRecoveringMalformedProviderScript(root: string): string {
  const scriptPath = join(root, "recovering-malformed-provider.mjs");
  const counterPath = join(root, "recovering-malformed-provider-count.txt");
  writeFileSync(scriptPath, `#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const counterPath = ${JSON.stringify(counterPath)};
const count = existsSync(counterPath) ? Number(readFileSync(counterPath, "utf8")) : 0;
writeFileSync(counterPath, String(count + 1));
writeFileSync("a.txt", count === 0 ? "created before recovery\\n" : "created after recovery\\n");

if (count === 0) {
  process.stdout.write(JSON.stringify({
    schema: "runway.worker_result.v1",
    task_id: "task_retry",
    candidate_id: "candidate_task_retry",
    status: "blocked",
    changed_files: ["a.txt"],
    summary: "First attempt produced malformed output shape after editing.",
    evidence: { provider: "test-recovering-provider", attempt: count + 1 },
    failure_class: "malformed_result"
  }));
} else {
  process.stdout.write(JSON.stringify({
    schema: "runway.worker_result.v1",
    task_id: "task_retry",
    candidate_id: "candidate_task_retry",
    status: "completed",
    changed_files: ["a.txt"],
    summary: "Created file after scheduler recovery retry.",
    evidence: { provider: "test-recovering-provider", attempt: count + 1 }
  }));
}
`);
  chmodSync(scriptPath, 0o755);
  return scriptPath;
}

function writeHelpFailingCodexProviderScript(root: string): string {
  const scriptPath = join(root, "codex");
  writeFileSync(scriptPath, `#!/usr/bin/env node
import { writeFileSync } from "node:fs";

if (process.argv.slice(2).join(" ") === "exec --help") {
  process.stderr.write("help unavailable\\n");
  process.exit(1);
}

writeFileSync("a.txt", "created after probe failure\\n");
process.stdout.write(JSON.stringify({
  schema: "runway.worker_result.v1",
  task_id: "task_probe",
  candidate_id: "candidate_task_probe",
  status: "completed",
  changed_files: ["a.txt"],
  summary: "Created file despite help probe failure.",
  evidence: { provider: "test-codex-provider" }
}));
`);
  chmodSync(scriptPath, 0o755);
  return scriptPath;
}

function writeNoMethodEvidenceProviderScript(_root: string): string {
  return `
import { writeFileSync } from "node:fs";

if (process.argv.includes("--help")) {
  process.stdout.write("codex help fixture\\n");
  process.exit(0);
}

writeFileSync("a.txt", "created without method audit\\n");
process.stdout.write(JSON.stringify({
  schema: "runway.worker_result.v1",
  task_id: "task_a",
  candidate_id: "candidate_task_a",
  status: "completed",
  changed_files: ["a.txt"],
  summary: "Created file without method evidence.",
  evidence: { provider: "test-codex-provider" }
}));
`;
}

function reviewResult(runId: string, taskId: string, attemptId: string): ReviewResult {
  return {
    schema: "runway.review_result.v1",
    run_id: runId,
    task_id: taskId,
    attempt_id: attemptId,
    provider: "test-reviewer",
    verdict: "pass",
    spec_score: 1,
    quality_score: 1,
    findings: [],
    residual_risk: [],
    summary: "Reviewed test fixture."
  };
}

function initSourceCheckout(prefix: string): string {
  const workspace = mkdtempSync(join(tmpdir(), prefix));
  Bun.spawnSync(["git", "init", "-q"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.email", "test@example.com"], { cwd: workspace });
  Bun.spawnSync(["git", "config", "user.name", "Test"], { cwd: workspace });
  writeFileSync(join(workspace, "README.md"), "fixture\n");
  Bun.spawnSync(["git", "add", "-A"], { cwd: workspace });
  Bun.spawnSync(["git", "commit", "-q", "-m", "init"], { cwd: workspace });
  return workspace;
}
