import { isAbsolute, resolve } from "node:path";
import { commandSegments, commandTokens } from "./commandLines";
import { isCommandInCatalog, type ProjectScriptCatalog } from "./projectScriptCatalog";

export type VerificationClassificationStatus = "safe" | "unsafe" | "ignored";

export type VerificationCommandRole =
  | "verification"
  | "implementation_only"
  | "diagnostic_readonly"
  | "optional_environment"
  | "unsafe"
  | "unknown";

export type VerificationClassificationReason =
  | "gradle_wrapper"
  | "gradle"
  | "node_test"
  | "package_script"
  | "known_runner"
  | "implementation_only"
  | "diagnostic_readonly"
  | "optional_environment"
  | "git_diff_check"
  | "destructive"
  | "workspace_escape"
  | "unknown";

export interface VerificationCommandSegment {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
  role: VerificationCommandRole;
}

export interface VerificationPolicyInput {
  command: string;
  workspace: string;
  catalog: ProjectScriptCatalog | null;
}

export interface VerificationClassification {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
  role: VerificationCommandRole;
  segments: VerificationCommandSegment[];
}

const destructivePattern = /\b(rm\s+-rf|git\s+reset\s+--hard|git\s+clean\s+-fd|drop\s+table|kubectl\s+delete)\b/i;
const knownPrefixes = [
  "bun test",
  "bun run test",
  "bun run check",
  "bun run typecheck",
  "bun run build",
  "bun run platform:demo",
  "bun run waygent:scenarios",
  "bun run waygent:dogfood",
  "bun run waygent:fixture-lab",
  "cargo test",
  "npm test",
  "npm run test",
  "pnpm test",
  "pnpm run test",
  "yarn test",
  "test ",
  "printf "
];

export function classifyVerificationCommand(input: VerificationPolicyInput): VerificationClassification {
  const segments = commandSegments(input.command).map((segment, index) =>
    classifySegment(segment, index, input.workspace, input.catalog)
  );
  const blocking = segments.find((segment) => segment.role === "unsafe" || segment.role === "unknown");
  if (blocking) {
    return { command: input.command, status: "unsafe", reason: blocking.reason, role: blocking.role, segments };
  }

  const verification = [...segments].reverse().find((segment) => segment.role === "verification");
  const executableVerification = [...segments]
    .reverse()
    .find((segment) => segment.role === "verification" && !isWorkspaceChangeSegment(segment.command));
  const implementationOnly = segments.find((segment) => segment.role === "implementation_only");
  if (executableVerification && implementationOnly) {
    return { command: input.command, status: "unsafe", reason: "implementation_only", role: "unsafe", segments };
  }

  if (implementationOnly) {
    return {
      command: input.command,
      status: "ignored",
      reason: "implementation_only",
      role: "implementation_only",
      segments
    };
  }

  const optionalEnvironment = segments.find((segment) => segment.role === "optional_environment");
  if (optionalEnvironment) {
    return {
      command: input.command,
      status: "ignored",
      reason: "optional_environment",
      role: "optional_environment",
      segments
    };
  }

  const diagnostic = segments.find((segment) => segment.role === "diagnostic_readonly");
  if (diagnostic) {
    return {
      command: input.command,
      status: "ignored",
      reason: "diagnostic_readonly",
      role: "diagnostic_readonly",
      segments
    };
  }

  return {
    command: input.command,
    status: executableVerification ? "safe" : "ignored",
    reason: executableVerification?.reason ?? verification?.reason ?? "unknown",
    role: executableVerification ? "verification" : verification ? "verification" : "unknown",
    segments
  };
}

export function isSafeVerificationCommand(input: VerificationPolicyInput): boolean {
  return classifyVerificationCommand(input).status === "safe";
}

function segment(
  command: string,
  status: VerificationClassificationStatus,
  reason: VerificationClassificationReason,
  role: VerificationCommandRole
): VerificationCommandSegment {
  return { command, status, reason, role };
}

function verification(command: string, reason: VerificationClassificationReason): VerificationCommandSegment {
  return segment(command, "safe", reason, "verification");
}

function ignored(
  command: string,
  reason: VerificationClassificationReason,
  role: VerificationCommandRole
): VerificationCommandSegment {
  return segment(command, "ignored", reason, role);
}

function blocked(
  command: string,
  reason: VerificationClassificationReason,
  role: VerificationCommandRole = "unsafe"
): VerificationCommandSegment {
  return segment(command, "unsafe", reason, role);
}

function classifySegment(
  rawSegment: string,
  index: number,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): VerificationCommandSegment {
  const segmentText = rawSegment.trim();
  if (!segmentText) return ignored(segmentText, "unknown", "unknown");
  if (isOptionalEnvironmentCommand(segmentText)) {
    return ignored(segmentText, "optional_environment", "optional_environment");
  }
  if (destructivePattern.test(segmentText)) return blocked(segmentText, "destructive");
  if (/[|;`]/.test(segmentText) || /\s[12]?>/.test(segmentText)) {
    return blocked(segmentText, "unknown", "unknown");
  }
  if (segmentText.startsWith("cd ")) {
    if (index !== 0 || !cdStaysInsideWorkspace(segmentText, workspace)) {
      return blocked(segmentText, "workspace_escape");
    }
    return verification(segmentText, "known_runner");
  }
  if (isImplementationOnlyCommand(segmentText)) {
    return ignored(segmentText, "implementation_only", "implementation_only");
  }
  if (isDiagnosticReadOnlyCommand(segmentText)) {
    return ignored(segmentText, "diagnostic_readonly", "diagnostic_readonly");
  }
  if (segmentText.startsWith("./gradlew ")) return verification(segmentText, "gradle_wrapper");
  if (segmentText === "./gradlew") return verification(segmentText, "gradle_wrapper");
  if (segmentText.startsWith("gradle ")) return verification(segmentText, "gradle");
  if (segmentText.startsWith("node --test")) return verification(segmentText, "node_test");
  if (segmentText.startsWith("git diff --check")) return verification(segmentText, "git_diff_check");
  if (catalog && isCommandInCatalog(segmentText, catalog)) {
    return verification(segmentText, "package_script");
  }
  if (knownPrefixes.some((prefix) => segmentText === prefix.trim() || segmentText.startsWith(prefix))) {
    return verification(segmentText, "known_runner");
  }
  return blocked(segmentText, "unknown", "unknown");
}

function isImplementationOnlyCommand(segment: string): boolean {
  if (/^(npm|bun|pnpm|yarn)\s+install\b/.test(segment)) return true;
  if (/^(npm|bun|pnpm|yarn)\s+run\s+(format|fmt|generate|codegen)\b/.test(segment)) return true;
  if (/^prettier\s+--write\b/.test(segment)) return true;
  if (segment === "graphify update ." || segment.startsWith("graphify update ")) return true;
  return /^git\s+(add|commit|push|checkout|merge|rebase|stash|worktree|cherry-pick)\b/.test(segment);
}

function isDiagnosticReadOnlyCommand(segment: string): boolean {
  return /^git\s+status\b/.test(segment) ||
    /^git\s+log\b/.test(segment) ||
    /^git\s+diff\s+--stat\b/.test(segment) ||
    /^git\s+branch\b/.test(segment) ||
    /^git\s+rev-parse\b/.test(segment);
}

function isOptionalEnvironmentCommand(segment: string): boolean {
  return segment === "command -v adb || true" ||
    segment === "adb devices" ||
    segment === "adb devices -l";
}

function isWorkspaceChangeSegment(segment: string): boolean {
  return segment.startsWith("cd ");
}

function cdStaysInsideWorkspace(segment: string, workspace: string): boolean {
  const target = commandTokens(segment)[1];
  if (!target) return false;
  const resolved = isAbsolute(target) ? resolve(target) : resolve(workspace, target);
  const root = resolve(workspace);
  return resolved === root || resolved.startsWith(`${root}/`);
}
