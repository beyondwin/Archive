export type ScopeId =
  | "docs" | "console" | "app" | "package" | "waygent-closure"
  | "native" | "waygent-skill" | "korean-writing-editor"
  | "codex-plan-runner" | "claude-plan-runner"
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
  deletedPaths: string[];
  unknownPaths: string[];
  reasons: string[];
}

export interface VerificationScope {
  id: ScopeId;
  matchers: readonly string[];
  commands: readonly CommandSpec[];
  allowOverlapWith?: readonly ScopeId[];
}

export interface VerificationTestRoot {
  id: string;
  root: string;
  command: CommandSpec;
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
const KOREAN_WRITING_EDITOR_EVAL: CommandSpec = {
  id: "korean-writing-editor-eval",
  argv: ["python3", "evals/run.py", "--scope", "full"],
  cwd: "skills/kws-korean-writing-editor",
};
const CODEX_PLAN_RUNNER_EVAL: CommandSpec = {
  id: "codex-plan-runner-eval",
  argv: ["./evals/run.sh"],
  cwd: "skills/kws-codex-plan-runner",
};
const CLAUDE_PLAN_RUNNER_EVAL: CommandSpec = {
  id: "claude-plan-runner-eval",
  argv: ["./evals/run.sh"],
  cwd: "skills/kws-claude-plan-runner",
};
const PLAN_RUNNER_PARITY: CommandSpec = {
  id: "plan-runner-parity",
  argv: ["./scripts/agent/check-plan-runner-parity"],
};
const PLAN_RUNNER_CUTOVER_TEST: CommandSpec = {
  id: "plan-runner-cutover-test",
  argv: ["./scripts/agent/plan-runner-cutover", "self-test"],
};
const CLAUDE_EXECUTOR_OFFLINE: CommandSpec = {
  id: "claude-executor-offline",
  argv: ["bun", "run", "agent:claude-offline"],
};
const CLAUDE_EXECUTOR_EVAL: CommandSpec = {
  id: "claude-executor-eval",
  argv: ["./evals/run.sh"],
  cwd: "skills/kws-claude-multi-agent-executor",
  optIn: true,
};
const LIVE_PROVIDER_SMOKE: CommandSpec = {
  id: "waygent-live-provider-smoke",
  argv: ["bun", "run", "waygent:live-provider-smoke"],
  optIn: true,
};

const OFFLINE_COMMANDS = [
  CONTRACT, DIFF_CHECK, TYPECHECK, CHECK, PLATFORM_DEMO, SCENARIOS, FIXTURE_LAB, DOGFOOD,
  CONSOLE_TEST, CONSOLE_BUILD, RUST_FORMAT, RUST_TEST, WAYGENT_SKILL_EVAL,
  CODEX_PLAN_RUNNER_EVAL, CLAUDE_PLAN_RUNNER_EVAL,
  PLAN_RUNNER_PARITY, PLAN_RUNNER_CUTOVER_TEST, CLAUDE_EXECUTOR_OFFLINE,
  CLAUDE_EXECUTOR_EVAL, LIVE_PROVIDER_SMOKE,
] as const;

export const VERIFICATION_SCOPES: readonly VerificationScope[] = [
  {
    id: "docs",
    matchers: [
      "docs/", "README.md", ".codex/README.md", "skills/README.md",
      "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursor/rules/",
      ".github/copilot-instructions.md", "code_review.md",
    ],
    commands: [CONTRACT, DIFF_CHECK],
  },
  { id: "console", matchers: ["apps/console/"], commands: [CONTRACT, DIFF_CHECK, CONSOLE_TEST, CONSOLE_BUILD], allowOverlapWith: ["app"] },
  { id: "app", matchers: ["apps/"], commands: [CONTRACT, DIFF_CHECK, TYPECHECK], allowOverlapWith: ["console"] },
  { id: "package", matchers: ["packages/"], commands: [CONTRACT, DIFF_CHECK, TYPECHECK], allowOverlapWith: ["waygent-closure"] },
  { id: "waygent-closure", matchers: ["packages/", "bun.lock"], commands: [CONTRACT, DIFF_CHECK, CHECK, PLATFORM_DEMO, SCENARIOS, FIXTURE_LAB, DOGFOOD, LIVE_PROVIDER_SMOKE], allowOverlapWith: ["package"] },
  { id: "native", matchers: ["native/kernel/"], commands: [CONTRACT, DIFF_CHECK, RUST_FORMAT, RUST_TEST] },
  { id: "waygent-skill", matchers: ["skills/waygent/"], commands: [CONTRACT, DIFF_CHECK, WAYGENT_SKILL_EVAL, CHECK, PLATFORM_DEMO, SCENARIOS] },
  { id: "korean-writing-editor", matchers: ["skills/kws-korean-writing-editor/"], commands: [CONTRACT, DIFF_CHECK, KOREAN_WRITING_EDITOR_EVAL] },
  { id: "codex-plan-runner", matchers: ["skills/kws-codex-plan-runner/"], commands: [CONTRACT, DIFF_CHECK, CODEX_PLAN_RUNNER_EVAL, PLAN_RUNNER_PARITY, PLAN_RUNNER_CUTOVER_TEST, CHECK] },
  { id: "claude-plan-runner", matchers: ["skills/kws-claude-plan-runner/"], commands: [CONTRACT, DIFF_CHECK, CLAUDE_PLAN_RUNNER_EVAL, PLAN_RUNNER_PARITY, PLAN_RUNNER_CUTOVER_TEST, CHECK] },
  { id: "claude-executor", matchers: ["skills/kws-claude-multi-agent-executor/"], commands: [CONTRACT, DIFF_CHECK, CLAUDE_EXECUTOR_OFFLINE, CLAUDE_EXECUTOR_EVAL, CHECK] },
  { id: "full-offline", matchers: ["*"], commands: OFFLINE_COMMANDS },
];

export const VERIFICATION_TEST_ROOTS: readonly VerificationTestRoot[] = [
  appTestRoot("api"),
  appTestRoot("cli"),
  packageTestRoot("context-packer"),
  packageTestRoot("contracts"),
  packageTestRoot("design-contract"),
  packageTestRoot("kernel-client"),
  packageTestRoot("lens-projectors"),
  packageTestRoot("lens-store"),
  packageTestRoot("orchestrator"),
  packageTestRoot("policy"),
  packageTestRoot("provider-adapters"),
  packageTestRoot("runway-control"),
  packageTestRoot("testkit"),
] as const;

export function selectVerification(
  paths: readonly string[],
  options: { deletedPaths?: readonly string[] } = {},
): VerificationSelection {
  const deletedPaths = stablePaths(options.deletedPaths ?? []);
  const deleted = new Set(deletedPaths);
  const markdownFiles = paths.filter((path) => path.endsWith(".md") && !deleted.has(path));
  const packageRoots = new Set(paths.flatMap(packageRoot));
  const hasClosure = paths.includes("bun.lock") || packageRoots.size >= 2;
  const unknownPaths = paths.filter((path) => !matchesKnownScope(path));
  const selected = unknownPaths.length > 0
    ? [scope("full-offline")]
    : selectKnownScopes(paths, hasClosure);

  return {
    scopeIds: selected.map(({ id }) => id),
    commands: deduplicateCommands([
      CONTRACT,
      DIFF_CHECK,
      ...selected.flatMap(({ commands }) => commands),
      ...(hasClosure ? [] : exactRootTestCommands(paths)),
      ...focusedTestCommands(paths.filter((path) => !deleted.has(path))),
    ]),
    markdownFiles,
    deletedPaths,
    unknownPaths,
    reasons: selected.flatMap(({ id }) => reasonsForScope(id, paths, hasClosure, unknownPaths)),
  };
}

function appTestRoot(name: string): VerificationTestRoot {
  const root = `apps/${name}`;
  return {
    id: `app-test:${name}`,
    root,
    command: { id: `app-test:${name}`, argv: ["bun", "test", "tests"], cwd: root },
  };
}

function packageTestRoot(name: string): VerificationTestRoot {
  const root = `packages/${name}`;
  return {
    id: `package-test:${name}`,
    root,
    command: { id: `package-test:${name}`, argv: ["bun", "test", "tests"], cwd: root },
  };
}

function exactRootTestCommands(paths: readonly string[]): CommandSpec[] {
  return VERIFICATION_TEST_ROOTS
    .filter(({ root }) => paths.some((path) => path.startsWith(`${root}/`)))
    .map(({ command }) => command);
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

function stablePaths(paths: readonly string[]): string[] {
  return [...new Set(paths.filter(Boolean))].sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0
  );
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
