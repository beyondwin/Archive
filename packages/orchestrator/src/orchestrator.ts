import { rmSync } from "node:fs";
import { join } from "node:path";
import type { AgentLensEvent } from "@waygent/contracts";
import { buildKernelRequest, result as kernelResult } from "@waygent/kernel-client";
import { projectFailureSummary, projectTimeline, projectTrustReport } from "@waygent/lens-projectors";
import { appendEvent, readEvents, rebuildRunSummary, runPaths, writeArtifact } from "@waygent/lens-store";
import { FakeProviderAdapter } from "@waygent/provider-adapters";
import { buildDurableProjection, createTaskGraph, mergeCandidate } from "@waygent/runway-control";
import { resolveExecutionProfile, type ProfileOverride } from "./executionProfile";

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

export async function runWaygentDemo(options: RunWaygentOptions): Promise<WaygentRunResult> {
  const runId = options.run_id ?? "run_demo";
  const paths = runPaths(options.root, runId);
  rmSync(paths.root, { recursive: true, force: true });
  const profile = resolveExecutionProfile(options.profile, { provider: "fake" });
  const provider = new FakeProviderAdapter();
  const started = event(1, "platform.run_started", "platform", "success", "Run opened.", { plan: options.plan, spec: options.spec });
  appendEvent(paths.events, started);
  const profileEvent = event(2, profile.evidence_event_type, "runway", "success", "Execution profile selected.", { profile });
  appendEvent(paths.events, profileEvent);
  const worker = await provider.run({ task_id: "task_demo", candidate_id: "candidate_demo", prompt: "deterministic demo", changed_files: [] });
  writeArtifact(paths.root, "worker/result.json", JSON.stringify(worker, null, 2));
  const kernelRequest = buildKernelRequest({
    request_id: "exec_demo",
    run_id: runId,
    task_id: "task_demo",
    cwd: ".",
    argv: ["printf", "hello"],
    timeout_ms: 1000
  });
  const kernel = kernelResult(kernelRequest, 0, "hello", "", false);
  writeArtifact(paths.root, "kernel/exec_demo.json", JSON.stringify(kernel, null, 2));
  const verified = mergeCandidate({ task_id: "task_demo", candidate_id: "candidate_demo", reviewed: true, verified: true });
  const completed = event(3, "runway.verification_result", "verify", "success", "Verification passed with kernel evidence.", {
    worker,
    kernel,
    checkpoint_ref: verified.checkpoint_ref
  });
  appendEvent(paths.events, completed);
  const events = readEvents(paths.events);
  const graph = createTaskGraph([
    {
      id: "task_demo",
      dependencies: [],
      file_claims: [{ path: "README.md", mode: "owned" }],
      resource_locks: [],
      risk: "low",
      status: "READY",
      checkpoint_ref: verified.checkpoint_ref ?? "checkpoint_task_demo_candidate_demo"
    }
  ]);
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

  function event(
    sequence: number,
    event_type: string,
    phase: string,
    outcome: AgentLensEvent["outcome"],
    summary: string,
    payload: Record<string, unknown>
  ): AgentLensEvent {
    return {
      schema: "agentlens.event.v3",
      event_id: `event_demo_${sequence}`,
      agentlens_run_id: "run_lens",
      orchestrator_run_id: runId,
      producer: { name: "waygent", kind: "orchestrator", version: "0.1.0" },
      event_type,
      occurred_at: "2026-05-21T00:00:00Z",
      sequence,
      phase,
      outcome,
      severity: outcome === "success" ? "info" : "error",
      trust_impact: outcome === "success" ? "supports_success" : "supports_failure",
      summary,
      payload
    };
  }
}

export function defaultRunRoot(): string {
  return join(process.cwd(), "tmp", "waygent-runs");
}
