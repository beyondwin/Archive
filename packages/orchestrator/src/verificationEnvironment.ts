import { spawnSync } from "node:child_process";
import { prepareInheritStrategy, type InheritStrategyEvidence } from "./inheritStrategy";
import {
  prepareIsolatedStrategy,
  type IsolatedStrategyEvidence
} from "./isolatedStrategy";
import { decideVerificationStrategy, type VerifyIsolationRequest } from "./strategyDecider";

export type VerificationStrategy = "none" | "inherit_node_modules" | "isolated_workspace_resolve";

export type IsolationStatus = "not_required" | "prepared" | "unavailable";

export interface VerificationEnvironmentEvidence {
  status: "prepared" | "skipped" | "failed";
  strategy: VerificationStrategy;
  decision: {
    requested: VerifyIsolationRequest | "auto";
    resolved: "isolated" | "fast";
    reason: string;
  };
  isolation_status: IsolationStatus;
  isolated_packages: string[];
  resolved_paths: Record<string, string>;
  cache: { hit: boolean; key: string; snapshot_path: string | null } | null;
  created_paths: string[];
  cleanup_status: "not_needed" | "pending" | "removed" | "failed";
  reason: string | null;
}

export interface PreparedVerificationEnvironment {
  evidence: VerificationEnvironmentEvidence;
  cleanup(): void;
}

export interface PrepareInput {
  workspace: string;
  worktree: string;
  disabled?: boolean;
  verifyIsolation?: VerifyIsolationRequest;
}

export function prepareVerificationEnvironment(input: PrepareInput): PreparedVerificationEnvironment {
  if (input.disabled) {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: "disabled"
    });
  }

  if (process.env.WAYGENT_DISABLE_ISOLATED_VERIFY_ENV === "1") {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: "killed_by_env_var"
    });
  }

  const worktreeDiff = collectDiff(input.worktree);
  const decision = decideVerificationStrategy({
    requested: input.verifyIsolation,
    worktreeDiff
  });

  if (decision.resolved === "fast") {
    return wrapInherit(prepareInheritStrategy(input), {
      requested: input.verifyIsolation ?? "auto",
      resolved: "fast",
      reason: decision.reason
    });
  }

  const prepared = prepareIsolatedStrategy({ workspace: input.workspace, worktree: input.worktree });
  return wrapIsolated(prepared, {
    requested: input.verifyIsolation ?? "auto",
    resolved: "isolated",
    reason: decision.reason
  });
}

function collectDiff(worktree: string): string[] {
  const result = spawnSync("git", ["status", "--porcelain"], { cwd: worktree, encoding: "utf8" });
  if (result.status !== 0) return [];
  return result.stdout.split("\n").filter((line) => line.length > 0);
}

function wrapInherit(
  prepared: { evidence: InheritStrategyEvidence; cleanup(): void },
  decision: VerificationEnvironmentEvidence["decision"]
): PreparedVerificationEnvironment {
  const evidence: VerificationEnvironmentEvidence = {
    status: prepared.evidence.status,
    strategy: prepared.evidence.strategy === "inherit_node_modules" ? "inherit_node_modules" : "none",
    decision,
    isolation_status: "not_required",
    isolated_packages: [],
    resolved_paths: {},
    cache: null,
    created_paths: prepared.evidence.created_paths,
    cleanup_status: prepared.evidence.cleanup_status,
    reason: prepared.evidence.reason
  };
  return {
    evidence,
    cleanup() {
      prepared.cleanup();
      evidence.cleanup_status = prepared.evidence.cleanup_status;
      evidence.reason = prepared.evidence.reason;
    }
  };
}

function wrapIsolated(
  prepared: { evidence: IsolatedStrategyEvidence; cleanup(): void },
  decision: VerificationEnvironmentEvidence["decision"]
): PreparedVerificationEnvironment {
  const evidence: VerificationEnvironmentEvidence = {
    status: prepared.evidence.status === "prepared" ? "prepared" : "failed",
    strategy: "isolated_workspace_resolve",
    decision,
    isolation_status: prepared.evidence.isolation_status,
    isolated_packages: prepared.evidence.isolated_packages,
    resolved_paths: prepared.evidence.resolved_paths,
    cache: prepared.evidence.cache,
    created_paths: prepared.evidence.created_paths,
    cleanup_status: prepared.evidence.cleanup_status,
    reason: prepared.evidence.reason
  };
  return {
    evidence,
    cleanup() {
      prepared.cleanup();
      evidence.cleanup_status = prepared.evidence.cleanup_status;
      evidence.reason = prepared.evidence.reason;
    }
  };
}
