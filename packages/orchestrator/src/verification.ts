import type { KernelExecutionResult } from "@waygent/contracts";
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
  return {
    status: results.every((result) => result.exit_code === 0 && !result.timed_out) ? "passed" : "failed",
    results
  };
}
