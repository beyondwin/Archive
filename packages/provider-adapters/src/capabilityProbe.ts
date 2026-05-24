import { spawnSync } from "node:child_process";
import { basename } from "node:path";
import type { ProviderProcessOptions } from "./types";

export type ProbedProvider = "codex" | "claude";

export interface ProviderHelpProbeResult {
  status: "ready" | "failed";
  stdout: string;
  stderr: string;
  exit_code: number | null;
}

export interface ProviderCapabilityAttestation {
  provider: ProbedProvider;
  executable: string;
  requested_model: string | null;
  applied_model: string | null;
  requested_reasoning: string | null;
  applied_reasoning: string | null;
  reason: "supported" | "unsupported_by_cli" | "probe_failed" | "custom_executable";
  help_exit_code: number | null;
}

export interface ProviderProcessAttestation {
  options: ProviderProcessOptions;
  capability: ProviderCapabilityAttestation;
}

export function probeProviderHelp(provider: ProbedProvider, options: ProviderProcessOptions): ProviderHelpProbeResult {
  if (!isProviderCliExecutable(provider, options.executable)) {
    return {
      status: "failed",
      stdout: "",
      stderr: "",
      exit_code: null
    };
  }
  const executable = options.executable;
  const args = provider === "codex" ? ["exec", "--help"] : ["--help"];
  const timeout = Math.min(options.timeout_ms ?? 5000, 5000);
  const result = spawnSync(executable, args, { encoding: "utf8", timeout });
  if (result.error && result.error.message.includes("ETIMEDOUT")) {
    return {
      status: "failed",
      stdout: result.stdout ?? "",
      stderr: `${result.stderr ?? ""}\nprovider help probe timed out after ${timeout}ms`.trim(),
      exit_code: null
    };
  }
  return {
    status: result.status === 0 ? "ready" : "failed",
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    exit_code: result.status
  };
}

export function attestProviderProcessOptions(
  provider: ProbedProvider,
  options: ProviderProcessOptions,
  probe: ProviderHelpProbeResult
): ProviderProcessAttestation {
  if (!isProviderCliExecutable(provider, options.executable)) {
    const { model: _model, effort: _effort, ...nextOptions } = options;
    return {
      options: nextOptions,
      capability: {
        provider,
        executable: options.executable,
        requested_model: options.model ?? null,
        applied_model: null,
        requested_reasoning: options.effort ?? null,
        applied_reasoning: null,
        reason: "custom_executable",
        help_exit_code: probe.exit_code
      }
    };
  }
  if (provider === "codex") {
    const helpText = `${probe.stdout}\n${probe.stderr}`;
    const supportsReasoning = probe.status === "ready" && helpText.includes("--reasoning");
    const nextOptions: ProviderProcessOptions = { ...options };
    if (options.effort && !supportsReasoning) delete nextOptions.effort;
    return {
      options: nextOptions,
      capability: {
        provider,
        executable: options.executable,
        requested_model: options.model ?? null,
        applied_model: options.model ?? null,
        requested_reasoning: options.effort ?? null,
        applied_reasoning: supportsReasoning ? options.effort ?? null : null,
        reason: probe.status === "ready" ? (supportsReasoning || !options.effort ? "supported" : "unsupported_by_cli") : "probe_failed",
        help_exit_code: probe.exit_code
      }
    };
  }
  return {
    options,
    capability: {
      provider,
      executable: options.executable,
      requested_model: options.model ?? null,
      applied_model: options.model ?? null,
      requested_reasoning: options.effort ?? null,
      applied_reasoning: options.effort ?? null,
      reason: probe.status === "ready" ? "supported" : "probe_failed",
      help_exit_code: probe.exit_code
    }
  };
}

function isProviderCliExecutable(provider: ProbedProvider, executable: string): boolean {
  const name = basename(executable).replace(/\.(cmd|exe|bat)$/i, "");
  return name === provider;
}
