export type ScopeId =
  | "docs" | "console" | "app" | "package" | "waygent-closure"
  | "native" | "waygent-skill" | "codex-executor"
  | "claude-executor" | "full-offline";

export interface CommandSpec {
  id: string;
  argv: readonly string[];
  cwd?: string;
  optIn?: boolean;
}

export interface VerificationSelection {
  scopeIds: ScopeId[];
  commands: CommandSpec[];
  markdownFiles: string[];
  unknownPaths: string[];
  reasons: string[];
}

export interface VerificationScope {
  id: ScopeId;
  matchers: readonly string[];
  commands: readonly CommandSpec[];
}

const CONTRACT: CommandSpec = { id: "agent-contract", argv: ["bun", "run", "agent:contract"] };
const DIFF_CHECK: CommandSpec = { id: "diff-check", argv: ["git", "diff", "--check"] };
const TYPECHECK: CommandSpec = { id: "typecheck", argv: ["bun", "run", "typecheck"] };
const CHECK: CommandSpec = { id: "check", argv: ["bun", "run", "check"] };
const PLATFORM_DEMO: CommandSpec = { id: "platform-demo", argv: ["bun", "run", "platform:demo"] };
const SCENARIOS: CommandSpec = { id: "waygent-scenarios", argv: ["bun", "run", "waygent:scenarios"] };
const FIXTURE_LAB: CommandSpec = { id: "waygent-fixture-lab", argv: ["bun", "run", "waygent:fixture-lab"] };
const DOGFOOD: CommandSpec = { id: "waygent-dogfood", argv: ["bun", "run", "waygent:dogfood"] };
const CONSOLE_TEST: CommandSpec = { id: "console-test", argv: ["bun", "test", "src"], cwd: "apps/console" };
const CONSOLE_BUILD: CommandSpec = { id: "console-build", argv: ["bun", "run", "build"], cwd: "apps/console" };
const RUST_FORMAT: CommandSpec = { id: "rust-format", argv: ["cargo", "fmt", "--check"], cwd: "native/kernel" };
const RUST_TEST: CommandSpec = { id: "rust-test", argv: ["cargo", "test", "--workspace"], cwd: "native/kernel" };
const WAYGENT_SKILL_EVAL: CommandSpec = { id: "waygent-skill-eval", argv: ["./evals/run.sh"], cwd: "skills/waygent" };
const CODEX_EXECUTOR_EVAL: CommandSpec = { id: "codex-executor-eval", argv: ["./evals/run.sh"], cwd: "skills/kws-codex-plan-executor" };
const CLAUDE_EXECUTOR_EVAL: CommandSpec = { id: "claude-executor-eval", argv: ["./evals/run.sh"], cwd: "skills/kws-claude-multi-agent-executor" };
const LIVE_PROVIDER_SMOKE: CommandSpec = {
  id: "waygent-live-provider-smoke",
  argv: ["bun", "run", "waygent:live-provider-smoke"],
  optIn: true,
};

const OFFLINE_COMMANDS = [
  CONTRACT, DIFF_CHECK, TYPECHECK, CHECK, PLATFORM_DEMO, SCENARIOS, FIXTURE_LAB, DOGFOOD,
  CONSOLE_TEST, CONSOLE_BUILD, RUST_FORMAT, RUST_TEST, WAYGENT_SKILL_EVAL,
  CODEX_EXECUTOR_EVAL, CLAUDE_EXECUTOR_EVAL, LIVE_PROVIDER_SMOKE,
] as const;

export const VERIFICATION_SCOPES: readonly VerificationScope[] = [
  {
    id: "docs",
    matchers: ["docs/", "README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursor/rules/", ".github/copilot-instructions.md", "code_review.md"],
    commands: [CONTRACT, DIFF_CHECK],
  },
  { id: "console", matchers: ["apps/console/"], commands: [CONTRACT, DIFF_CHECK, CONSOLE_TEST, CONSOLE_BUILD] },
  { id: "app", matchers: ["apps/"], commands: [CONTRACT, DIFF_CHECK, TYPECHECK] },
  { id: "package", matchers: ["packages/"], commands: [CONTRACT, DIFF_CHECK, TYPECHECK] },
  { id: "waygent-closure", matchers: ["packages/", "bun.lock"], commands: [CONTRACT, DIFF_CHECK, CHECK, PLATFORM_DEMO, SCENARIOS, FIXTURE_LAB, DOGFOOD, LIVE_PROVIDER_SMOKE] },
  { id: "native", matchers: ["native/kernel/"], commands: [CONTRACT, DIFF_CHECK, RUST_FORMAT, RUST_TEST] },
  { id: "waygent-skill", matchers: ["skills/waygent/"], commands: [CONTRACT, DIFF_CHECK, WAYGENT_SKILL_EVAL, CHECK, PLATFORM_DEMO, SCENARIOS] },
  { id: "codex-executor", matchers: ["skills/kws-codex-plan-executor/"], commands: [CONTRACT, DIFF_CHECK, CODEX_EXECUTOR_EVAL, CHECK] },
  { id: "claude-executor", matchers: ["skills/kws-claude-multi-agent-executor/"], commands: [CONTRACT, DIFF_CHECK, CLAUDE_EXECUTOR_EVAL, CHECK] },
  { id: "full-offline", matchers: ["*"], commands: OFFLINE_COMMANDS },
];

export function selectVerification(paths: readonly string[]): VerificationSelection {
  const markdownFiles = paths.filter((path) => path.endsWith(".md"));
  const packageRoots = new Set(paths.flatMap(packageRoot));
  const hasClosure = paths.includes("bun.lock") || packageRoots.size >= 2;
  const unknownPaths = paths.filter((path) => !matchesKnownScope(path));
  const selected = unknownPaths.length > 0
    ? [scope("full-offline")]
    : selectKnownScopes(paths, hasClosure);

  return {
    scopeIds: selected.map(({ id }) => id),
    commands: deduplicateCommands([
      ...selected.flatMap(({ commands }) => commands),
      ...focusedTestCommands(paths),
    ]),
    markdownFiles,
    unknownPaths,
    reasons: selected.flatMap(({ id }) => reasonsForScope(id, paths, hasClosure, unknownPaths)),
  };
}

function selectKnownScopes(paths: readonly string[], hasClosure: boolean): VerificationScope[] {
  const selected: VerificationScope[] = [];
  for (const candidate of VERIFICATION_SCOPES) {
    if (candidate.id === "full-offline" || candidate.id === "package" || candidate.id === "waygent-closure") {
      continue;
    }
    if (hasClosure && (candidate.id === "console" || candidate.id === "app")) {
      continue;
    }
    if (paths.some((path) => matches(candidate, path)) && !isCoveredByNarrowerScope(candidate.id, paths)) {
      selected.push(candidate);
    }
  }
  if (hasClosure) {
    selected.push(scope("waygent-closure"));
  } else if (paths.some((path) => matches(scope("package"), path))) {
    selected.push(scope("package"));
  }
  return selected;
}

function isCoveredByNarrowerScope(id: ScopeId, paths: readonly string[]): boolean {
  if (id !== "app") return false;
  const appPaths = paths.filter((path) => matches(scope("app"), path));
  return appPaths.length > 0 && appPaths.every((path) => matches(scope("console"), path));
}

function scope(id: ScopeId): VerificationScope {
  const found = VERIFICATION_SCOPES.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`missing verification scope: ${id}`);
  return found;
}

function packageRoot(path: string): string[] {
  const match = /^packages\/([^/]+)\//.exec(path);
  return match ? [match[1]!] : [];
}

function matchesKnownScope(path: string): boolean {
  return VERIFICATION_SCOPES
    .filter(({ id }) => id !== "waygent-closure" && id !== "full-offline")
    .some((candidate) => matches(candidate, path)) || path === "bun.lock";
}

function matches(scope: VerificationScope, path: string): boolean {
  return scope.matchers.some((matcher) => matcher.endsWith("/") ? path.startsWith(matcher) : path === matcher);
}

function deduplicateCommands(commands: readonly CommandSpec[]): CommandSpec[] {
  const selected = new Map<string, CommandSpec>();
  for (const command of commands) {
    selected.set(`${command.cwd ?? ""}\u0000${command.argv.join("\u0000")}`, command);
  }
  return [...selected.values()];
}

function focusedTestCommands(paths: readonly string[]): CommandSpec[] {
  return paths
    .filter((path) => /\.(?:test|spec)\.[cm]?[jt]sx?$/.test(path))
    .map((path) => ({
      id: `focused-test:${path}`,
      argv: ["bun", "test", path],
    }));
}

function reasonsForScope(
  id: ScopeId,
  paths: readonly string[],
  hasClosure: boolean,
  unknownPaths: readonly string[],
): string[] {
  if (id === "full-offline") return unknownPaths.map((path) => `unknown path: ${path}`);
  if (id === "waygent-closure" && hasClosure) return ["cross-package or lockfile change requires offline closure"];
  return paths.filter((path) => matches(scope(id), path)).map((path) => `${id} scope: ${path}`);
}
