import { rmSync } from "node:fs";
import { join } from "node:path";
import type { AgentLensEvent } from "@waygent/contracts";
import { buildKernelRequest, result as kernelResult } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeArtifact, writeLatestRunId } from "@waygent/lens-store";
import { FakeProviderAdapter } from "@waygent/provider-adapters";
import { buildDurableProjection, mergeCandidate } from "@waygent/runway-control";
import { resolveExecutionProfile, type ProfileOverride } from "./executionProfile";
import { parseWaygentPlan } from "./planParser";
import { buildRunEvent } from "./runEvents";
import { buildTaskGraphFromPlan } from "./taskGraph";

export interface RunWaygentOptions {
  root: string;
  run_id?: string;
  profile?: ProfileOverride;
  plan?: string;
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
  const parsed = parseWaygentPlan(options.plan ?? DEMO_PLAN);
  const graph = buildTaskGraphFromPlan(parsed);
  const projection = buildDurableProjection(graph);
  const taskId = projection.safe_wave[0] ?? parsed.tasks[0]?.id;
  if (!taskId) throw new Error("run requires at least one task");
  const task = graph.tasks.get(taskId);
  if (!task) throw new Error(`task ${taskId} missing from graph`);
  const parsedTask = parsed.tasks.find((candidate) => candidate.id === task.id);

  const started = buildRunEvent({
    run_id: runId,
    sequence: 1,
    event_type: "platform.run_started",
    phase: "platform",
    outcome: "running",
    summary: "Run opened.",
    payload: { plan: options.plan, spec: options.spec, profile }
  });
  appendEvent(paths.events, started);
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 2,
    event_type: "runway.plan_loaded",
    phase: "plan",
    outcome: "success",
    summary: "Plan parsed into task graph.",
    payload: { task_count: parsed.tasks.length, profile }
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

  const worker = await provider.run({ task_id: task.id, candidate_id: `candidate_${task.id}`, prompt: parsedTask?.title ?? task.id, changed_files: [] });
  writeArtifact(paths.root, "worker/result.json", JSON.stringify(worker, null, 2));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 4,
    event_type: "runway.worker_result",
    phase: "worker",
    outcome: "success",
    summary: worker.summary,
    payload: { worker }
  }));
  const kernelRequest = buildKernelRequest({
    request_id: `exec_${task.id}`,
    run_id: runId,
    task_id: task.id,
    cwd: ".",
    argv: ["printf", "hello"],
    timeout_ms: 1000
  });
  const kernel = kernelResult(kernelRequest, 0, "hello", "", false);
  writeArtifact(paths.root, `kernel/exec_${task.id}.json`, JSON.stringify(kernel, null, 2));
  const verified = mergeCandidate({ task_id: task.id, candidate_id: worker.candidate_id, reviewed: true, verified: true });
  task.checkpoint_ref = verified.checkpoint_ref ?? `checkpoint_${task.id}_${worker.candidate_id}`;
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 5,
    event_type: "runway.verification_result",
    phase: "verify",
    outcome: "success",
    summary: "Verification passed with kernel evidence.",
    payload: { worker, kernel, checkpoint_ref: task.checkpoint_ref }
  }));
  const trust = projectTrustReport(readEvents(paths.events));
  appendEvent(paths.events, buildRunEvent({
    run_id: runId,
    sequence: 6,
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

export async function runWaygentDemo(options: RunWaygentOptions): Promise<WaygentRunResult> {
  return runWaygent({ ...options, plan: options.plan ?? DEMO_PLAN });
}

export function defaultRunRoot(): string {
  return join(process.cwd(), "tmp", "waygent-runs");
}
