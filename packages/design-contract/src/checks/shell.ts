import { spawn } from "node:child_process";

export interface ShellCheckResult {
  passed: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
}

export function runShell(command: string, cwd: string): Promise<ShellCheckResult> {
  return new Promise((resolve) => {
    const proc = spawn("sh", ["-c", command], { cwd });
    let out = "";
    let err = "";
    proc.stdout.on("data", (b: Buffer) => (out += b.toString("utf8")));
    proc.stderr.on("data", (b: Buffer) => (err += b.toString("utf8")));
    proc.on("close", (code) => {
      const exit = typeof code === "number" ? code : -1;
      resolve({ passed: exit === 0, exit_code: exit, stdout: out, stderr: err });
    });
  });
}
