import { createHash } from "node:crypto";
import type { KernelExecutionRequest, KernelExecutionResult, PermissionProfile } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";
import { evaluatePolicy } from "@waygent/policy";

export function buildKernelRequest(input: Omit<KernelExecutionRequest, "schema" | "env" | "stdin" | "tty" | "capture"> & {
  env?: Record<string, string>;
  stdin?: KernelExecutionRequest["stdin"];
  tty?: boolean;
  capture?: KernelExecutionRequest["capture"];
  permission_profile?: PermissionProfile;
}): KernelExecutionRequest {
  return validateContract<KernelExecutionRequest>("kernel.execution_request.v1", {
    schema: "kernel.execution_request.v1",
    env: {},
    stdin: "closed",
    tty: false,
    capture: { stdout_limit_bytes: 200000, stderr_limit_bytes: 200000 },
    ...input
  });
}

export async function executeInProcess(request: KernelExecutionRequest): Promise<KernelExecutionResult> {
  if (request.permission_profile) {
    const permission = evaluatePolicy({
      mode: "execute",
      command: request.argv,
      cwd: request.cwd,
      writes: [],
      profile: request.permission_profile
    });
    if (!permission.allowed) return result(request, 1, "", permission.reason, false, permission);
  }
  const proc = Bun.spawn(request.argv, {
    cwd: request.cwd,
    env: { ...process.env, ...request.env },
    stdin: request.stdin === "closed" ? "ignore" : "pipe",
    stdout: "pipe",
    stderr: "pipe"
  });
  const timer = setTimeout(() => proc.kill(), request.timeout_ms);
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited
  ]);
  clearTimeout(timer);
  return result(request, exitCode, stdout, stderr, false);
}

export function result(
  request: KernelExecutionRequest,
  exitCode: number | null,
  stdout: string,
  stderr: string,
  timedOut: boolean,
  permission_decision?: KernelExecutionResult["permission_decision"]
): KernelExecutionResult {
  const boundedOut = bound(stdout, request.capture.stdout_limit_bytes);
  const boundedErr = bound(stderr, request.capture.stderr_limit_bytes);
  return validateContract<KernelExecutionResult>("kernel.execution_result.v1", {
    schema: "kernel.execution_result.v1",
    request_id: request.request_id,
    run_id: request.run_id,
    task_id: request.task_id,
    exit_code: exitCode,
    signal: null,
    timed_out: timedOut,
    stdout: boundedOut.text,
    stderr: boundedErr.text,
    stdout_truncated: boundedOut.truncated,
    stderr_truncated: boundedErr.truncated,
    stdout_sha256: digest(stdout),
    stderr_sha256: digest(stderr),
    changed_files: [],
    permission_decision
  });
}

function bound(text: string, limit: number): { text: string; truncated: boolean } {
  const bytes = new TextEncoder().encode(text);
  if (bytes.byteLength <= limit) return { text, truncated: false };
  return { text: new TextDecoder().decode(bytes.slice(0, limit)), truncated: true };
}

function digest(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}
