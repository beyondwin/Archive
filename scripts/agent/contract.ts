export const REQUIRED_PATHS = [
  "apps/cli", "apps/api", "apps/console",
  "packages/orchestrator", "packages/runway-control",
  "packages/provider-adapters", "packages/lens-store",
  "packages/lens-projectors", "native/kernel", "skills/waygent",
  "skills/kws-codex-plan-executor", "skills/kws-codex-plan-runner",
  "skills/kws-claude-plan-runner", "skills/kws-claude-multi-agent-executor",
] as const;

export const ROOT_GUIDANCE_FILES = ["AGENTS.md"] as const;

export const SUBTREE_GUIDANCE_FILES = [
  "apps/AGENTS.md", "packages/AGENTS.md",
  "native/kernel/AGENTS.md", "skills/AGENTS.md",
  "skills/kws-codex-plan-executor/AGENTS.md",
  "skills/kws-codex-plan-runner/AGENTS.md",
  "skills/kws-claude-plan-runner/AGENTS.md",
  "skills/kws-claude-multi-agent-executor/AGENTS.md",
] as const;

export const REQUIRED_AGENT_FILES = [
  ...ROOT_GUIDANCE_FILES,
  ...SUBTREE_GUIDANCE_FILES,
] as const;

export const TOOL_GUIDANCE_FILES = [
  "CLAUDE.md", "GEMINI.md", ".cursor/rules/archive.mdc",
  ".github/copilot-instructions.md", ".codex/README.md",
] as const;

export const CURRENT_GUIDANCE_FILES = [
  ...REQUIRED_AGENT_FILES,
  ...TOOL_GUIDANCE_FILES,
  ".gitignore", "PLANS.md", "code_review.md",
] as const;

export const LOCAL_STATE_PATTERN =
  /^(?:\.waygent|\.agentlens|\.claude|\.codex-orchestrator|\.orchestrator|\.superpowers|node_modules|native\/kernel\/target)(?:\/|$)/;

export type ContractIssueCode =
  | "missing_active_path" | "missing_agent_file" | "stale_active_claim"
  | "missing_package_script" | "non_executable_gate"
  | "tracked_local_state" | "invalid_verification_map"
  | "codex_execpolicy_unavailable" | "invalid_guidance_file"
  | "tracked_file_scan_failed";

export interface ContractIssue {
  code: ContractIssueCode;
  path: string;
  message: string;
}
