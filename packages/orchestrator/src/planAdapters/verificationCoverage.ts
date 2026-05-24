import type { FileClaim } from "@waygent/runway-control";
import { commandSegments, commandTokens } from "./commandLines";

export interface VerificationCoverageTask {
  title: string;
  label?: string;
  file_claims: FileClaim[];
  verification_commands: string[];
}

export interface VerificationCoverageIssue {
  task_title: string;
  path: string;
  message: string;
}

export function verificationClaimCoverageIssues(tasks: VerificationCoverageTask[]): VerificationCoverageIssue[] {
  const allClaimed = new Set(tasks.flatMap((task) => task.file_claims.map((claim) => claim.path)));
  const issues: VerificationCoverageIssue[] = [];
  for (const task of tasks) {
    for (const command of task.verification_commands) {
      for (const explicitPath of explicitVerificationPaths(command)) {
        if (![...allClaimed].some((claimPath) => claimCoversPath(claimPath, explicitPath))) {
          const subject = task.label ?? `Task "${task.title}"`;
          issues.push({
            task_title: task.title,
            path: explicitPath,
            message: `${subject} verification command references unclaimed path ${explicitPath}`
          });
        }
      }
    }
  }
  return issues;
}

export function verificationClaimCoverageErrors(tasks: VerificationCoverageTask[]): string[] {
  return verificationClaimCoverageIssues(tasks).map((issue) => issue.message);
}

function explicitVerificationPaths(command: string): string[] {
  const paths = new Set<string>();
  for (const segment of commandSegments(command)) {
    if (segment.startsWith("cd ")) continue;
    if (segment.startsWith("bun test ")) {
      for (const token of commandTokens(segment).slice(2)) {
        if (isExplicitPathToken(token)) paths.add(token);
      }
      continue;
    }
    if (segment.startsWith("git diff --check")) {
      const tokens = commandTokens(segment);
      const separatorIndex = tokens.indexOf("--");
      if (separatorIndex >= 0) {
        for (const token of tokens.slice(separatorIndex + 1)) {
          if (isExplicitPathToken(token)) paths.add(token);
        }
      }
    }
  }
  return [...paths];
}

function isExplicitPathToken(token: string): boolean {
  if (!token || token.startsWith("-")) return false;
  return token.includes("/") || token.startsWith(".") || /\.[a-zA-Z0-9]+$/.test(token);
}

function claimCoversPath(claimPath: string, path: string): boolean {
  const normalizedClaim = claimPath.replace(/\/\*\*$/, "").replace(/\/$/, "");
  const normalizedPath = path.replace(/\/$/, "");
  return normalizedPath === normalizedClaim || normalizedPath.startsWith(`${normalizedClaim}/`);
}
