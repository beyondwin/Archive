import type { PermissionDecision, PermissionProfile } from "@waygent/contracts";
import { validateContract } from "@waygent/contracts";

export type PolicyMode = "plan" | "read" | "execute" | "auto_edit" | "recovery" | "yolo";

const modeRank: Record<PolicyMode, number> = {
  plan: 0,
  read: 1,
  execute: 2,
  auto_edit: 3,
  recovery: 4,
  yolo: 5
};

export interface PolicyRequest {
  mode: PolicyMode;
  command: string[];
  cwd: string;
  writes: string[];
  profile: PermissionProfile;
}

export function evaluatePolicy(request: PolicyRequest): PermissionDecision {
  const prefix = request.command[0] ?? "";
  if (modeRank[request.mode] < modeRank.execute && request.command.length > 0) {
    return decision(false, "mode does not allow command execution", "mode", request.profile);
  }
  if (!request.profile.command_prefixes.includes(prefix) && request.mode !== "yolo") {
    return decision(false, `command prefix ${prefix} is not allowed`, "command_prefixes", request.profile);
  }
  for (const write of request.writes) {
    if (request.profile.filesystem.deny.some((deny) => inPath(write, deny))) {
      return decision(false, `${write} is denied`, "filesystem.deny", request.profile);
    }
    if (!request.profile.filesystem.write.some((grant) => inPath(write, grant)) && request.mode !== "yolo") {
      return decision(false, `${write} is outside write grants`, "filesystem.write", request.profile);
    }
  }
  return decision(true, "allowed by policy profile", undefined, request.profile);
}

function decision(allowed: boolean, reason: string, denied_by: string | undefined, profile: PermissionProfile): PermissionDecision {
  return validateContract<PermissionDecision>("policy.permission_decision.v1", {
    schema: "policy.permission_decision.v1",
    allowed,
    reason,
    denied_by,
    profile
  });
}

export function inPath(path: string, grant: string): boolean {
  const normalizedPath = path.replace(/\/+$/, "");
  const normalizedGrant = grant.replace(/\/+$/, "").replace(/\*\*$/, "");
  return normalizedGrant === "." || normalizedPath === normalizedGrant || normalizedPath.startsWith(`${normalizedGrant}/`);
}

export function permissionProfile(overrides: Partial<PermissionProfile> = {}): PermissionProfile {
  const profile: PermissionProfile = {
    filesystem: {
      read: ["."],
      write: [],
      deny: [".git/config"],
      ...overrides.filesystem
    },
    network: overrides.network ?? "disabled",
    command_prefixes: overrides.command_prefixes ?? ["bun", "git"]
  };
  if (overrides.escalation_reason) profile.escalation_reason = overrides.escalation_reason;
  return profile;
}
