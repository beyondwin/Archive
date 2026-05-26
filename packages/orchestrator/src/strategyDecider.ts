export type VerifyIsolationRequest = "isolated" | "fast" | "auto";

export interface StrategyDecision {
  resolved: "isolated" | "fast";
  reason: string;
}

export interface DeciderInput {
  requested: VerifyIsolationRequest | undefined;
  worktreeDiff: string[];
  verificationCommands?: string[];
}

const PACKAGE_DIR_PREFIX = "packages/";
const LOCKFILE_PATHS = new Set(["bun.lock", "package.json"]);

export function decideVerificationStrategy(input: DeciderInput): StrategyDecision {
  const requested: VerifyIsolationRequest = input.requested ?? "auto";

  if (requested === "isolated") return { resolved: "isolated", reason: "explicit_tag" };
  if (requested === "fast") return { resolved: "fast", reason: "explicit_tag" };

  if ((input.verificationCommands ?? []).some(isDependencyInstallCommand)) {
    return { resolved: "isolated", reason: "verification_dependency_install" };
  }

  const paths = input.worktreeDiff
    .map((line) => extractPath(line))
    .filter((p): p is string => p !== null);

  if (paths.some((p) => LOCKFILE_PATHS.has(p))) {
    return { resolved: "isolated", reason: "diff_lockfile_touched" };
  }

  const packageDirs = new Set<string>();
  for (const p of paths) {
    if (p.startsWith(PACKAGE_DIR_PREFIX)) {
      const rest = p.slice(PACKAGE_DIR_PREFIX.length);
      const slash = rest.indexOf("/");
      const top = slash === -1 ? rest : rest.slice(0, slash);
      if (top.length > 0) packageDirs.add(top);
    }
  }

  if (packageDirs.size === 0) return { resolved: "fast", reason: "diff_no_package_changes" };
  if (packageDirs.size === 1) return { resolved: "fast", reason: "diff_single_package" };
  return { resolved: "isolated", reason: "diff_cross_package" };
}

function isDependencyInstallCommand(command: string): boolean {
  return /(^|&&|\|\||;)\s*(npm|pnpm|yarn|bun)\s+(install|i)\b/.test(command);
}

function extractPath(porcelainLine: string): string | null {
  if (porcelainLine.length < 4) return null;
  const body = porcelainLine.slice(3).trim();
  const arrow = body.indexOf(" -> ");
  return arrow === -1 ? body : body.slice(arrow + 4);
}
