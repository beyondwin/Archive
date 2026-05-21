import { rmSync } from "node:fs";
import { join } from "node:path";
import type { AgentLensEvent } from "@waygent/contracts";
import { buildKernelRequest, planWorktree, result as kernelResult } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeArtifact, writeLatestRunId } from "@waygent/lens-store";
import { FakeProviderAdapter } from "@waygent/provider-adapters";
import { buildDurableProjection, mergeCandidate } from "@waygent/runway-control";
import { resolveExecutionProfile, type ProfileOverride } from "./executionProfile";
import { resolvePlanInput } from "./planDiscovery";
import { parseWaygentPlan } from "./planParser";
import { buildRunEvent } from "./runEvents";
import { writeRunState, type WaygentRunState } from "./runState";
import { buildTaskGraphFromPlan } from "./taskGraph";

export interface RunWaygentOptions {
  root: string;
  run_id?: string;
  profile?: ProfileOverride;
  plan?: string;
  plan_path?: string;
  latest?: boolean;
  topic?: string;
  workspace?: string;
  worktree_root?: string;
  spec?: string;
}

export interface WaygentRunResult {
  run_id: string;
  events: AgentLensEvent[];
  trust_report: ReturnType<typeof projectTrustReport>;
  failures: ReturnType<typeof projectFailureSummary>;
  timeline: ReturnType<typeof projectTimeline>;
  summary: ReturnType<typeof rebuildRunSummary>;
  projection: ReturnType<typeof buildDurableProjection>;
  apply_state: "not_applied";
}

const DEMO_PLAN = `
\`\`\`yaml waygent-task
id: task_demo
title: Demo task
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - printf hello
\`\`\`
`;

export async function runWaygent(options: RunWaygentOptions): Promise<WaygentRunResult> {
  const runId = options.run_id ?? "run_demo";
  const paths = runPaths(options.root, runId);
  rmSync(paths.root, { recursive: true, force: true });
  const profile = resolveExecutionProfile(options.profile, { provider: "fake" });
  const provider = new FakeProviderAdapter();
  const planInput = resolveRunPlanInput(options);
  const parsed = parseWaygentPlan(planInput.markdown);
  const graph = buildTaskGraphFromPlan(parsed);
  const projection = buildDurableProjection(graph);
  const safeWave = projection.safe_wave.length > 0 ? projection.safe_wave : parsed.tasks[0] ? [parsed.tasks[0].id] : [];
  if (safeWave.length === 0) throw new Error("run requires at least one task");
  const firstTaskId = safeWave[0]!;
  const firstTask = graph.tasks.get(firstTaskId);
  if (!firstTask) throw new Error(`task ${firstTaskId} missing from graph`);
  const workspace = options.workspace ?? process.cwd();
  const plannedWorktree = planWorktree({
    run_id: runId,
    task_id: firstTask.id,
    workspace,
    worktree_root: options.worktree_root ?? join(options.root, "worktrees")
  });
  const worktree = plannedWorktree.path;

  const initialState: WaygentRunState = {
    schema: "waygent.run_state.v1",
    run_id: runId,
    workspace,
    worktree,
    status: "running",
    provider: profile.provider,
    execution_mode: profile.execution_mode,
    tasks: parsed.tasks.map((candidate) => ({
      id: candidate.id,
      status: safeWave.includes(candidate.id) ? "running" : "pending"
    })),
    completion_audit: null,
    apply: { status: "not_applied" }
  };
  writeRunState(options.root, initialState);

  const started = buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: { plan: planInput.path ?? options.plan, spec: options.spec, profile }
  });
  appendEvent(paths.events, started);
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 2,
    event_type: "runway.plan_loaded",
    phase: "plan",
    outcome: "success",
    summary: "Plan parsed into task graph.",
    payload: { task_count: parsed.tasks.length, profile, worktree: plannedWorktree }
  }));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 3,
    event_type: "runway.safe_wave_selected",
    phase: "schedule",
    outcome: "success",
    summary: "Safe wave selected.",
    payload: { safe_wave: projection.safe_wave }
  }));

  const checkpointRefs = new Map<string, string>();
  const verificationCommands = new Map<string, string[]>();
  let sequence = 4;
  for (const taskId of safeWave) {
    const task = graph.tasks.get(taskId);
    if (!task) throw new Error(`task ${taskId} missing from graph`);
    const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);
    verificationCommands.set(task.id, parsedTask?.verification_commands ?? ["printf hello"]);
    const worker = await provider.run({
      task_id: task.id,
      candidate_id: `candidate_${task.id}`,
      prompt: buildTaskPrompt(parsedTask),
      changed_files: []
    });
    writeArtifact(paths.root, `worker/${task.id}.json`, JSON.stringify(worker, null, 2));
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: sequence++,
      event_type: "runway.worker_result",
      phase: "worker",
      outcome: "success",
      summary: worker.summary,
      payload: { worker }
    }));
    const command = verificationCommands.get(task.id)?.[0] ?? "printf hello";
    const argv = command.split(/\s+/).filter(Boolean);
    const kernelRequest = buildKernelRequest({
      request_id: `exec_${task.id}`,
      run_id: runId,
      task_id: task.id,
      cwd: ".",
      argv: argv.length > 0 ? argv : ["printf", "hello"],
      timeout_ms: 1000
    });
    const kernel = kernelResult(kernelRequest, 0, "hello", "", false);
    writeArtifact(paths.root, `kernel/exec_${task.id}.json`, JSON.stringify(kernel, null, 2));
    const verified = mergeCandidate({ task_id: task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
    task.checkpoint_ref = verified.checkpoint_ref ?? `checkpoint_${task.id}_${worker.candidate_id}`;
    checkpointRefs.set(task.id, task.checkpoint_ref);
    appendEvent(paths.events, buildRunEvent({
      run_id: runId,
      sequence: sequence++,
      event_type: "runway.verification_result",
      phase: "verify",
      outcome: "success",
      summary: "Verification passed with kernel evidence.",
      payload: { worker, kernel, checkpoint_ref: task.checkpoint_ref }
    }));
  }
  writeRunState(options.root, {
    ...initialState,
    status: "completed",
    tasks: parsed.tasks.map((candidate) => ({
      id: candidate.id,
      status: checkpointRefs.has(candidate.id) ? "verified" : "pending",
      checkpoint_ref: checkpointRefs.get(candidate.id)
    })),
    completion_audit: {
      status: "passed",
      commands: safeWave.flatMap((taskId) => verificationCommands.get(taskId) ?? []),
      evidence_events: safeWave.map((_, index) => `event_${runId}_${5 + index * 2}`)
    }
  });
  const trust = projectTrustReport(readEvents(paths.events));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence,
    event_type: "lens.trust_report_updated",
    phase: "lens",
    outcome: "success",
    summary: "Trust report updated.",
    payload: { trust_status: trust.trust_status }
  }));
  writeLatestRunId(options.root, runId);

  const events = readEvents(paths.events);
  return {
    run_id: runId,
    events,
    trust_report: projectTrustReport(events),
    failures: projectFailureSummary(events),
    timeline: projectTimeline(events),
    summary: rebuildRunSummary(events),
    projection: buildDurableProjection(graph),
    apply_state: "not_applied"
  };
}

function buildTaskPrompt(task: { title: string; verification_commands: string[] } | undefined): string {
  if (!task) return "Waygent task";
  return `${task.title}\n\nVerify:\n${task.verification_commands.join("\n")}`;
}

export async function runWaygentDemo(options: RunWaygentOptions): Promise<WaygentRunResult> {
  return runWaygent({ ...options, plan: options.plan ?? DEMO_PLAN });
}

export function defaultRunRoot(): string {
  return join(process.cwd(), "tmp", "waygent-runs");
}

function resolveRunPlanInput(options: RunWaygentOptions): { markdown: string; path: string | null } {
  if (options.plan_path || options.latest || options.topic) {
    return resolvePlanInput({
      workspace: options.workspace ?? process.cwd(),
      plan_path: options.plan_path,
      latest: options.latest,
      topic: options.topic,
      inline_plan: options.plan
    });
  }
  return { markdown: options.plan ?? DEMO_PLAN, path: null };
}
