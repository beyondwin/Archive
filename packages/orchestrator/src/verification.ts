import type { FailureClass, KernelExecutionResult } from "@waygent/contracts";
import { buildKernelRequest, executeInProcess } from "@waygent/kernel-client";

export interface VerificationRunInput {
  run_id: string;
  task_id: string;
  cwd: string;
  commands: string[];
  timeout_ms?: number;
}

export interface VerificationRunOutput {
  status: "passed" | "failed";
  results: KernelExecutionResult[];
  failure_class: FailureClass | null;
  failure_summary: string | null;
  failed_verification_id: string | null;
}

export async function runVerificationCommands(input: VerificationRunInput): Promise<VerificationRunOutput> {
  const results: KernelExecutionResult[] = [];
  for (let index = 0; index < input.commands.length; index += 1) {
    const command = input.commands[index]!;
    const request = buildKernelRequest({
      request_id: `verify_${input.task_id}_${index + 1}`,
      run_id: input.run_id,
      task_id: input.task_id,
      cwd: input.cwd,
      argv: ["bash", "-lc", command],
      timeout_ms: input.timeout_ms ?? 120000
    });
    results.push(await executeInProcess(request));
  }
  const failed = results.find((result) => result.exit_code !== 0 || result.timed_out) ?? null;
  const classified = failed ? classifyVerificationResult(failed) : null;
  return {
    status: failed ? "failed" : "passed",
    results,
    failure_class: classified?.failure_class ?? null,
    failure_summary: classified?.failure_summary ?? null,
    failed_verification_id: failed?.request_id ?? null
  };
}

export function classifyVerificationResult(result: KernelExecutionResult): {
  failure_class: FailureClass;
  failure_summary: string;
} {
  const text = `${result.stderr}\n${result.stdout}`;
  if (result.timed_out || (result.exit_code === 143 && firstSignalLine(text) === "verification failed")) {
    return { failure_class: "timeout", failure_summary: "verification timed out" };
  }
  const dependencyLine = firstMatchingLine(text, /Cannot find package|ERR_MODULE_NOT_FOUND|Cannot find module/i);
  if (dependencyLine) {
    return { failure_class: "dependency_missing", failure_summary: dependencyLine };
  }
  const commandLine = firstMatchingLine(text, /\bcommand not found\b|^not found\b/i);
  if (commandLine) {
    return { failure_class: "command_not_found", failure_summary: commandLine };
  }
  const permissionLine = firstMatchingLine(text, /permission denied|policy denied/i);
  if (permissionLine) {
    return { failure_class: "permission_denied", failure_summary: permissionLine };
  }
  return { failure_class: "verification_failed", failure_summary: firstSignalLine(text) };
}

function firstSignalLine(text: string): string {
  return text.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "verification failed";
}

function firstMatchingLine(text: string, pattern: RegExp): string | null {
  return text.split(/\r?\n/).map((line) => line.trim()).find((line) => pattern.test(line)) ?? null;
}
