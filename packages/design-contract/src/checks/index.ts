import { existsSync } from "node:fs";
import { join } from "node:path";
import type { InvariantCheck } from "../types";
import { runShell } from "./shell";

export interface CheckResult {
  passed: boolean;
  evidence: string;
}

export async function runInvariantCheck(check: InvariantCheck, cwd: string): Promise<CheckResult> {
  if (check.kind === "shell") {
    const r = await runShell(check.command, cwd);
    const matched = check.expect_exit_zero ? r.exit_code === 0 : r.exit_code !== 0;
    return {
      passed: matched,
      evidence: `shell \`${check.command}\` exit=${r.exit_code} stderr=${r.stderr.slice(0, 200)}`
    };
  }
  if (check.kind === "file_exists") {
    const present = existsSync(join(cwd, check.path));
    return { passed: present, evidence: `file_exists ${check.path} present=${present}` };
  }
  const pathsArg = check.paths.map((p) => JSON.stringify(p)).join(" ");
  const command = `rg --no-messages -q ${JSON.stringify(check.pattern)} ${pathsArg}`;
  const r = await runShell(command, cwd);
  const matched = check.must_match ? r.exit_code === 0 : r.exit_code !== 0;
  return {
    passed: matched,
    evidence: `rg pattern=${check.pattern} paths=[${check.paths.join(",")}] exit=${r.exit_code}`
  };
}
