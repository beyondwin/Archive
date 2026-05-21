import type { RiskLevel } from "@waygent/contracts";
import type { FileClaim, FileClaimMode } from "@waygent/runway-control";

export interface ScaffoldWaygentTaskInput {
  id: string;
  title: string;
  dependencies: string[];
  file_claims: FileClaim[];
  risk: RiskLevel;
  verify: string[];
}

export function scaffoldWaygentTask(input: ScaffoldWaygentTaskInput): string {
  if (!input.id.trim()) throw new Error("task id required");
  if (!input.title.trim()) throw new Error("title required");
  if (input.file_claims.length === 0) throw new Error("file claims required");
  if (input.verify.length === 0) throw new Error("verification commands required");
  return [
    "```yaml waygent-task",
    `id: ${input.id}`,
    `title: ${input.title}`,
    `dependencies: [${input.dependencies.join(", ")}]`,
    "file_claims:",
    ...input.file_claims.flatMap((claim) => [`  - path: ${claim.path}`, `    mode: ${claim.mode}`]),
    `risk: ${input.risk}`,
    "verify:",
    ...input.verify.map((command) => `  - ${command}`),
    "```",
    ""
  ].join("\n");
}

export function parseClaimFlag(value: string): FileClaim {
  const [path, mode = "owned"] = value.split(":");
  if (!path) throw new Error("claim path required");
  if (!["owned", "shared_append", "read_only"].includes(mode)) throw new Error(`invalid claim mode ${mode}`);
  return { path, mode: mode as FileClaimMode };
}
