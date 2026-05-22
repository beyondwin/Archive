import type {
  FailureClass,
  ProviderAttempt,
  ProviderReadinessProjection,
  WaygentRunStateV2
} from "@waygent/contracts";

export interface ProviderReadinessInput {
  state: WaygentRunStateV2;
}

export function projectProviderReadinessFromState(input: ProviderReadinessInput): ProviderReadinessProjection {
  const provider = selectedProvider(input.state);
  const latestAttempt = latestProviderAttempt(input.state.provider_attempts, provider);
  if (!provider) {
    return projection(input.state.run_id, null, "not_configured", [], null, null, [], "Configure a Waygent provider profile before running live tasks.");
  }
  if (!latestAttempt) {
    if (provider === "fake") {
      return projection(input.state.run_id, provider, "ready", ["fake-provider"], null, null, [], "Offline fake provider is ready for deterministic local checks.");
    }
    return projection(
      input.state.run_id,
      provider,
      "unknown",
      defaultCommandSummary(provider),
      null,
      null,
      [],
      `Run a ${provider} task or opt-in live smoke to collect provider readiness evidence.`
    );
  }

  const stderr = latestAttempt.process?.stderr ?? "";
  const command = sanitizedCommandSummary(latestAttempt.command);
  const attemptRefs = [
    latestAttempt.attempt_id,
    latestAttempt.stdout_ref,
    latestAttempt.stderr_ref,
    latestAttempt.worker_result_ref ?? ""
  ].filter(Boolean);
  const failureClass = latestAttempt.failure_class;
  if (looksAuthRequired(stderr)) {
    return projection(input.state.run_id, provider, "auth_required", command, latestAttempt.process?.stderr_summary ?? null, failureClass, attemptRefs, `Authenticate the ${provider} provider outside Waygent, then rerun the task.`);
  }
  if (looksUnavailable(stderr, latestAttempt)) {
    return projection(input.state.run_id, provider, "unavailable", command, latestAttempt.process?.stderr_summary ?? null, failureClass, attemptRefs, `Install or fix the ${provider} provider command, then rerun the Waygent task.`);
  }
  if (latestAttempt.timed_out || failureClass === "timeout") {
    return projection(input.state.run_id, provider, "failed", command, latestAttempt.process?.stderr_summary ?? null, failureClass ?? "timeout", attemptRefs, `Increase the ${provider} timeout only after checking provider and verification cost evidence.`);
  }
  if (failureClass || latestAttempt.exit_code !== 0 || !latestAttempt.worker_result_ref) {
    return projection(input.state.run_id, provider, "failed", command, latestAttempt.process?.stderr_summary ?? null, failureClass, attemptRefs, `Inspect ${provider} stdout, stderr, and worker result evidence before rerunning.`);
  }
  return projection(
    input.state.run_id,
    provider,
    "ready",
    command,
    latestAttempt.process?.stderr_summary ?? null,
    null,
    attemptRefs,
    providerReadyRecommendation(provider, latestAttempt)
  );
}

function projection(
  runId: string,
  provider: string | null,
  status: ProviderReadinessProjection["status"],
  commandSummary: string[],
  stderrSummary: ProviderReadinessProjection["stderr_summary"],
  failureClass: FailureClass | string | null,
  attemptRefs: string[],
  recommendedNextAction: string
): ProviderReadinessProjection {
  return {
    schema: "waygent.provider_readiness.v1",
    run_id: runId,
    provider,
    status,
    command_summary: commandSummary,
    stderr_summary: stderrSummary,
    failure_class: failureClass,
    attempt_refs: attemptRefs,
    recommended_next_action: recommendedNextAction
  };
}

function selectedProvider(state: WaygentRunStateV2): string | null {
  const provider = state.provider_profile.provider;
  if (typeof provider === "string" && provider.length > 0) return provider;
  return state.provider_attempts.at(-1)?.provider ?? null;
}

function latestProviderAttempt(attempts: ProviderAttempt[], provider: string | null): ProviderAttempt | null {
  const matching = provider ? attempts.filter((attempt) => attempt.provider === provider) : attempts;
  return matching.at(-1) ?? null;
}

function defaultCommandSummary(provider: string): string[] {
  if (provider === "codex") return ["codex"];
  if (provider === "claude") return ["claude"];
  if (provider === "fake") return ["fake-provider"];
  return [provider];
}

function sanitizedCommandSummary(command: string[]): string[] {
  const redactedNext = new Set(["--api-key", "--token", "--auth-token", "--password"]);
  const result: string[] = [];
  for (let index = 0; index < command.length; index += 1) {
    const part = command[index] ?? "";
    if (redactedNext.has(part)) {
      result.push(part, "[redacted]");
      index += 1;
      continue;
    }
    if (/api[-_]?key|token|password|secret/i.test(part) && part.includes("=")) {
      result.push(part.replace(/=.*/, "=[redacted]"));
      continue;
    }
    result.push(part);
  }
  return result;
}

function looksAuthRequired(stderr: string): boolean {
  return /auth|authenticate|login|logged in|api key|permission denied|unauthorized/i.test(stderr);
}

function looksUnavailable(stderr: string, attempt: ProviderAttempt): boolean {
  return attempt.exit_code === null
    || /ENOENT|not found|command not found|failed to start|spawn .*enoent/i.test(stderr)
    || attempt.failure_class === "command_not_found"
    || attempt.failure_class === "service_unreachable";
}

function providerReadyRecommendation(provider: string, attempt: ProviderAttempt): string {
  const summary = attempt.process?.stderr_summary;
  const startupNoise = (summary?.counts.plugin_manifest ?? 0)
    + (summary?.counts.skill_loader ?? 0)
    + (summary?.counts.mcp ?? 0);
  if (startupNoise > 0) {
    return `Provider ${provider} is ready; clean provider startup warnings to reduce configuration noise.`;
  }
  return `Provider ${provider} has successful process evidence.`;
}
