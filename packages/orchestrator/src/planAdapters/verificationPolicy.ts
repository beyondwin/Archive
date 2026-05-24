import { isAbsolute, resolve } from "node:path";
import { commandSegments, commandTokens } from "./commandLines";
import { isCommandInCatalog, type ProjectScriptCatalog } from "./projectScriptCatalog";

export type VerificationClassificationStatus = "safe" | "unsafe" | "ignored";

export type VerificationClassificationReason =
  | "gradle_wrapper"
  | "gradle"
  | "node_test"
  | "package_script"
  | "known_runner"
  | "implementation_only"
  | "git_diff_check"
  | "destructive"
  | "workspace_escape"
  | "unknown";

export interface VerificationCommandSegment {
  command: string;
  status: VerificationClassificationStatus;
  reason: VerificationClassificationReason;
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
  const unsafe = segments.find((segment) => segment.status === "unsafe");
  if (unsafe) {
    return { command: input.command, status: "unsafe", reason: unsafe.reason, segments };
  }
  const safe = [...segments].reverse().find((segment) => segment.status === "safe");
  const safeVerification = [...segments]
    .reverse()
    .find((segment) => segment.status === "safe" && !isWorkspaceChangeSegment(segment.command));
  const implementationOnly = segments.find((segment) => segment.reason === "implementation_only");
  if (safeVerification && implementationOnly) {
    return { command: input.command, status: "unsafe", reason: "implementation_only", segments };
  }
  if (implementationOnly) {
    return { command: input.command, status: "ignored", reason: "implementation_only", segments };
  }
  return {
    command: input.command,
    status: safe ? "safe" : "ignored",
    reason: safe?.reason ?? "unknown",
    segments
  };
}

export function isSafeVerificationCommand(input: VerificationPolicyInput): boolean {
  return classifyVerificationCommand(input).status === "safe";
}

function classifySegment(
  segment: string,
  index: number,
  workspace: string,
  catalog: ProjectScriptCatalog | null
): VerificationCommandSegment {
  if (!segment) return { command: segment, status: "ignored", reason: "unknown" };
  if (destructivePattern.test(segment)) return { command: segment, status: "unsafe", reason: "destructive" };
  if (/[|;`]/.test(segment) || /\s[12]?>/.test(segment)) {
    return { command: segment, status: "unsafe", reason: "unknown" };
  }
  if (segment.startsWith("cd ")) {
    if (index !== 0 || !cdStaysInsideWorkspace(segment, workspace)) {
      return { command: segment, status: "unsafe", reason: "workspace_escape" };
    }
    return { command: segment, status: "safe", reason: "known_runner" };
  }
  if (isImplementationOnlyCommand(segment)) {
    return { command: segment, status: "ignored", reason: "implementation_only" };
  }
  if (segment.startsWith("./gradlew ")) return { command: segment, status: "safe", reason: "gradle_wrapper" };
  if (segment === "./gradlew") return { command: segment, status: "safe", reason: "gradle_wrapper" };
  if (segment.startsWith("gradle ")) return { command: segment, status: "safe", reason: "gradle" };
  if (segment.startsWith("node --test")) return { command: segment, status: "safe", reason: "node_test" };
  if (segment.startsWith("git diff --check")) return { command: segment, status: "safe", reason: "git_diff_check" };
  if (catalog && isCommandInCatalog(segment, catalog)) {
    return { command: segment, status: "safe", reason: "package_script" };
  }
  if (knownPrefixes.some((prefix) => segment === prefix.trim() || segment.startsWith(prefix))) {
    return { command: segment, status: "safe", reason: "known_runner" };
  }
  return { command: segment, status: "unsafe", reason: "unknown" };
}

function isImplementationOnlyCommand(segment: string): boolean {
  if (/^(npm|bun|pnpm|yarn)\s+install\b/.test(segment)) return true;
  if (/^(npm|bun|pnpm|yarn)\s+run\s+(format|fmt|generate|codegen)\b/.test(segment)) return true;
  if (/^prettier\s+--write\b/.test(segment)) return true;
  if (segment === "graphify update ." || segment.startsWith("graphify update ")) return true;
  return /^git\s+(add|commit|push|checkout|merge|rebase|stash|worktree|cherry-pick)\b/.test(segment);
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
