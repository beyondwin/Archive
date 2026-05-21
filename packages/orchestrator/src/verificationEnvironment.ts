import { existsSync, lstatSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";

export interface VerificationEnvironmentEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: "inherit_node_modules" | "none";
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedVerificationEnvironment {
  evidence: VerificationEnvironmentEvidence;
  cleanup(): void;
}

export function prepareVerificationEnvironment(input: {
  workspace: string;
  worktree: string;
  disabled?: boolean;
}): PreparedVerificationEnvironment {
  const sourceNodeModules = join(input.workspace, "node_modules");
  const worktreeNodeModules = join(input.worktree, "node_modules");
  const evidence: VerificationEnvironmentEvidence = {
    status: "skipped",
    strategy: "none",
    created_paths: [],
    cleanup_status: "not_needed",
    reason: null
  };

  if (input.disabled) {
    evidence.reason = "disabled";
    return { evidence, cleanup: () => {} };
  }
  if (!existsSync(sourceNodeModules)) {
    evidence.reason = "source_node_modules_missing";
    return { evidence, cleanup: () => {} };
  }
  if (existsSync(worktreeNodeModules)) {
    evidence.reason = "worktree_node_modules_exists";
    return { evidence, cleanup: () => {} };
  }

  try {
    symlinkSync(sourceNodeModules, worktreeNodeModules, "dir");
    evidence.status = "prepared";
    evidence.strategy = "inherit_node_modules";
    evidence.created_paths = ["node_modules"];
    evidence.cleanup_status = "pending";
  } catch (error) {
    evidence.status = "failed";
    evidence.reason = error instanceof Error ? error.message : String(error);
    evidence.cleanup_status = "not_needed";
  }

  return {
    evidence,
    cleanup() {
      if (evidence.cleanup_status !== "pending") return;
      try {
        if (existsSync(worktreeNodeModules)) {
          if (!lstatSync(worktreeNodeModules).isSymbolicLink()) {
            evidence.cleanup_status = "failed";
            evidence.reason = "node_modules cleanup skipped: created path is not a symbolic link";
            return;
          }
          rmSync(worktreeNodeModules, { force: true, recursive: true });
        }
        evidence.cleanup_status = "removed";
      } catch (error) {
        evidence.cleanup_status = "failed";
        evidence.reason = error instanceof Error ? error.message : String(error);
      }
    }
  };
}
