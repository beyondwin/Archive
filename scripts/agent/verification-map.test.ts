import { expect, test } from "bun:test";
import {
  selectVerification,
  VERIFICATION_SCOPES,
  type CommandSpec,
  type ScopeId,
} from "./verification-map";

const command = (id: string, argv: string[], cwd?: string, optIn?: boolean) => ({ id, argv, cwd, optIn });
const commands = (paths: string[]) => selectVerification(paths).commands.map(toCommand);
const toCommand = ({ id, argv, cwd, optIn }: CommandSpec) => ({ id, argv: [...argv], cwd, optIn });

const contract = command("agent-contract", ["bun", "run", "agent:contract"]);
const diffCheck = command("diff-check", ["git", "diff", "--check"]);
const typecheck = command("typecheck", ["bun", "run", "typecheck"]);
const check = command("check", ["bun", "run", "check"]);
const platformDemo = command("platform-demo", ["bun", "run", "platform:demo"]);
const scenarios = command("waygent-scenarios", ["bun", "run", "waygent:scenarios"]);
const fixtureLab = command("waygent-fixture-lab", ["bun", "run", "waygent:fixture-lab"]);
const dogfood = command("waygent-dogfood", ["bun", "run", "waygent:dogfood"]);
const consoleTest = command("console-test", ["bun", "test", "src"], "apps/console");
const consoleBuild = command("console-build", ["bun", "run", "build"], "apps/console");
const apiTest = command("app-test:api", ["bun", "test", "tests"], "apps/api");
const cliTest = command("app-test:cli", ["bun", "test", "tests"], "apps/cli");
const packageTest = (name: string) =>
  command(`package-test:${name}`, ["bun", "test", "tests"], `packages/${name}`);
const rustFormat = command("rust-format", ["cargo", "fmt", "--check"], "native/kernel");
const rustTest = command("rust-test", ["cargo", "test", "--workspace"], "native/kernel");
const waygentSkillEval = command("waygent-skill-eval", ["./evals/run.sh"], "skills/_legacy/waygent");
const codexPlanRunnerEval = command(
  "codex-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-codex-plan-runner",
);
const claudePlanRunnerEval = command(
  "claude-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-claude-plan-runner",
);
const planRunnerParity = command(
  "plan-runner-parity",
  ["./scripts/agent/check-plan-runner-parity"],
);
const planRunnerCutoverTest = command(
  "plan-runner-cutover-test",
  ["./scripts/agent/plan-runner-cutover", "self-test"],
);
const claudeExecutorOffline = command("claude-executor-offline", ["bun", "run", "agent:claude-offline"]);
const claudeExecutorEval = command(
  "claude-executor-eval",
  ["./evals/run.sh"],
  "skills/_legacy/kws-claude-multi-agent-executor",
  true,
);
const liveProvider = command(
  "waygent-live-provider-smoke",
  ["bun", "run", "waygent:live-provider-smoke"],
  undefined,
  true,
);

const closureCommands = [contract, diffCheck, check, platformDemo, scenarios, fixtureLab, dogfood, liveProvider];
const offlineCommands = [
  contract, diffCheck, typecheck, check, platformDemo, scenarios, fixtureLab, dogfood,
  consoleTest, consoleBuild, rustFormat, rustTest, waygentSkillEval,
  codexPlanRunnerEval, claudePlanRunnerEval, planRunnerParity, planRunnerCutoverTest,
  claudeExecutorOffline, claudeExecutorEval, liveProvider,
];

test.each([
  ["docs", ["docs/README.md"], ["docs"], [contract, diffCheck]],
  ["console", ["apps/console/src/App.tsx"], ["console"], [contract, diffCheck, consoleTest, consoleBuild]],
  ["other app", ["apps/api/src/index.ts"], ["app"], [contract, diffCheck, typecheck, apiTest]],
  ["one package", ["packages/orchestrator/src/index.ts"], ["package"], [contract, diffCheck, typecheck, packageTest("orchestrator")]],
  ["two packages", ["packages/orchestrator/src/index.ts", "packages/runway-control/src/scheduler.ts"], ["waygent-closure"], closureCommands],
  ["bun lock", ["bun.lock"], ["waygent-closure"], closureCommands],
  ["native", ["native/kernel/crates/kernel-cli/src/main.rs"], ["native"], [contract, diffCheck, rustFormat, rustTest]],
  ["Waygent skill", ["skills/_legacy/waygent/SKILL.md"], ["waygent-skill"], [contract, diffCheck, waygentSkillEval, check, platformDemo, scenarios]],
  ["Codex plan runner", ["skills/_legacy/kws-codex-plan-runner/SKILL.md"], ["codex-plan-runner"], [contract, diffCheck, codexPlanRunnerEval, planRunnerParity, planRunnerCutoverTest, check]],
  ["Claude plan runner", ["skills/_legacy/kws-claude-plan-runner/scripts/runner"], ["claude-plan-runner"], [contract, diffCheck, claudePlanRunnerEval, planRunnerParity, planRunnerCutoverTest, check]],
  ["Claude executor", ["skills/_legacy/kws-claude-multi-agent-executor/scripts/kernel/kernel.py"], ["claude-executor"], [contract, diffCheck, claudeExecutorOffline, claudeExecutorEval, check]],
  ["unknown", ["unexpected/new-surface.txt"], ["full-offline"], offlineCommands],
] satisfies readonly [string, string[], ScopeId[], ReturnType<typeof command>[]][])(
  "selects the complete $0 command set",
  (_name, paths, scopeIds, expectedCommands) => {
    expect(selectVerification(paths).scopeIds).toEqual(scopeIds);
    expect(commands(paths)).toEqual(expectedCommands);
  },
);

test.each([
  ["Codex project guidance", ".codex/README.md"],
  ["skills guidance", "skills/README.md"],
  ["skills agent routing", "skills/AGENTS.md"],
  ["adding a skill", "skills/adding-a-skill.md"],
  ["legacy catalog note", "skills/_legacy/README.md"],
] satisfies readonly [string, string][])(
  "classifies exact $0 as docs with Markdown checking",
  (_name, path) => {
    const selection = selectVerification([path]);

    expect(selection.scopeIds).toEqual(["docs"]);
    expect(selection.commands.map(toCommand)).toEqual([contract, diffCheck]);
    expect(selection.markdownFiles).toEqual([path]);
    expect(selection.unknownPaths).toEqual([]);
    expect(selection.scopeIds).not.toContain("full-offline");
  },
);

test.each([
  ["bun.lock plus another app", ["bun.lock", "apps/api/src/index.ts"]],
  ["bun.lock plus console", ["bun.lock", "apps/console/src/App.tsx"]],
  ["cross-package plus app", [
    "packages/orchestrator/src/index.ts",
    "packages/runway-control/src/scheduler.ts",
    "apps/api/src/index.ts",
  ]],
] satisfies readonly [string, string[]][])(
  "closure replaces narrow TypeScript scopes for $0",
  (_name, paths) => {
    const selection = selectVerification(paths);

    expect(selection.scopeIds).toEqual(["waygent-closure"]);
    expect(commands(paths)).toEqual(closureCommands);
  },
);

test("keeps independently relevant docs, native, and skill scopes with closure", () => {
  const paths = [
    "bun.lock",
    "docs/README.md",
    "native/kernel/crates/kernel-cli/src/main.rs",
    "skills/_legacy/waygent/SKILL.md",
  ];

  expect(selectVerification(paths).scopeIds).toEqual([
    "docs", "native", "waygent-skill", "waygent-closure",
  ]);
});

test("explains preserved scopes before the closure escalation", () => {
  const selection = selectVerification([
    "docs/README.md",
    "native/kernel/crates/kernel-cli/src/main.rs",
    "bun.lock",
  ]);

  expect(selection.reasons).toEqual([
    "docs scope: docs/README.md",
    "native scope: native/kernel/crates/kernel-cli/src/main.rs",
    "cross-package or lockfile change requires offline closure",
  ]);
});

test("keeps app verification when console and another app change without closure", () => {
  const paths = ["apps/console/src/App.tsx", "apps/api/src/index.ts"];

  expect(selectVerification(paths).scopeIds).toEqual(["console", "app"]);
  expect(commands(paths)).toEqual([
    contract, diffCheck, consoleTest, consoleBuild, typecheck, apiTest,
  ]);
});

test.each([
  ["apps/api/src/server.ts", apiTest],
  ["apps/cli/src/index.ts", cliTest],
  ["packages/context-packer/src/index.ts", packageTest("context-packer")],
  ["packages/contracts/src/index.ts", packageTest("contracts")],
  ["packages/design-contract/src/index.ts", packageTest("design-contract")],
  ["packages/kernel-client/src/index.ts", packageTest("kernel-client")],
  ["packages/lens-projectors/src/index.ts", packageTest("lens-projectors")],
  ["packages/lens-store/src/index.ts", packageTest("lens-store")],
  ["packages/orchestrator/src/index.ts", packageTest("orchestrator")],
  ["packages/policy/src/index.ts", packageTest("policy")],
  ["packages/provider-adapters/src/index.ts", packageTest("provider-adapters")],
  ["packages/runway-control/src/index.ts", packageTest("runway-control")],
  ["packages/testkit/src/index.ts", packageTest("testkit")],
] satisfies readonly [string, ReturnType<typeof command>][]) (
  "selects the exact test root for $0",
  (path, expected) => {
    expect(commands([path])).toContainEqual(expected);
  },
);

test("always selects contract and plain patch hygiene for a clean tree", () => {
  const selection = selectVerification([]);

  expect(selection.scopeIds).toEqual([]);
  expect(selection.commands.map(toCommand)).toEqual([contract, diffCheck]);
});

test("does not schedule Markdown link reads for frozen legacy skill bodies", () => {
  const selection = selectVerification([
    "skills/_legacy/README.md",
    "skills/_legacy/kws-claude-multi-agent-executor/HISTORY.md",
    "skills/_legacy/waygent/SKILL.md",
  ]);

  expect(selection.markdownFiles).toEqual(["skills/_legacy/README.md"]);
  expect(selection.scopeIds).toEqual(["docs", "waygent-skill", "claude-executor"]);
});

test("does not schedule Markdown link reads for Superpowers design artifacts", () => {
  const selection = selectVerification([
    "docs/README.md",
    "docs/architecture/waygent.md",
    "docs/superpowers/plans/2026-07-25-provider-plan-runners-thin-superpowers-boundary.md",
    "docs/superpowers/specs/2026-07-17-cpe-2.0-token-evidence-observability-addendum.md",
  ]);

  expect(selection.markdownFiles).toEqual([
    "docs/README.md",
    "docs/architecture/waygent.md",
  ]);
  expect(selection.scopeIds).toEqual(["docs"]);
});

test("classifies deleted Markdown without scheduling a link read", () => {
  const selection = selectVerification(["docs/removed.md"], {
    deletedPaths: ["docs/removed.md"],
  });

  expect(selection.scopeIds).toEqual(["docs"]);
  expect(selection.markdownFiles).toEqual([]);
  expect(selection.deletedPaths).toEqual(["docs/removed.md"]);
  expect(selection.commands.map(toCommand)).toEqual([contract, diffCheck]);
});

test("keeps existing Markdown in mixed changes while excluding the deletion", () => {
  const selection = selectVerification(
    ["docs/kept.md", "docs/removed.md"],
    { deletedPaths: ["docs/removed.md"] },
  );

  expect(selection.markdownFiles).toEqual(["docs/kept.md"]);
  expect(selection.deletedPaths).toEqual(["docs/removed.md"]);
});

test.each([
  ["API source", "apps/api/src/removed.ts", apiTest],
  ["API test file", "apps/api/tests/removed.test.ts", apiTest],
  ["orchestrator source", "packages/orchestrator/src/removed.ts", packageTest("orchestrator")],
  ["orchestrator test file", "packages/orchestrator/tests/removed.test.ts", packageTest("orchestrator")],
] satisfies readonly [string, string, ReturnType<typeof command>][]) (
  "keeps the mapped root suite for a deleted $0",
  (_name, path, expectedRootSuite) => {
    const selection = selectVerification([path], { deletedPaths: [path] });

    expect(selection.commands.map(toCommand)).toContainEqual(expectedRootSuite);
  },
);

test.each([
  "apps/api/tests/removed.test.ts",
  "packages/orchestrator/tests/removed.test.ts",
])("does not focus a deleted test file: %s", (path) => {
  const selection = selectVerification([path], { deletedPaths: [path] });

  expect(selection.commands.some(({ id }) => id === `focused-test:${path}`)).toBeFalse();
});

test.each([
  ["app", "apps/unmapped/src/removed.ts", "app-test:"],
  ["package", "packages/unmapped/src/removed.ts", "package-test:"],
] as const)("does not invent a root suite for an unmapped $0", (_name, path, idPrefix) => {
  const selection = selectVerification([path], { deletedPaths: [path] });

  expect(selection.commands.some(({ id }) => id.startsWith(idPrefix))).toBeFalse();
});

test("deduplicates commands by cwd and argv", () => {
  const actualCommands = commands([
    "docs/README.md",
    "native/kernel/crates/kernel-cli/src/main.rs",
    "skills/_legacy/kws-codex-plan-runner/scripts/runner.py",
  ]);

  expect(actualCommands).toEqual([
    contract, diffCheck, rustFormat, rustTest, codexPlanRunnerEval,
    planRunnerParity, planRunnerCutoverTest, check,
  ]);
  expect(new Set(actualCommands.map(({ argv, cwd }) => `${cwd ?? ""}\u0000${argv.join("\u0000")}`)).size)
    .toBe(actualCommands.length);
});

test("keeps the plan-runner live canary out of every offline scope", () => {
  for (const scope of VERIFICATION_SCOPES) {
    expect(scope.commands.some(({ argv }) =>
      argv.some((part) => part.includes("plan-runner-live-canary"))
    )).toBeFalse();
  }
});

test("does not route either retired sequential executor", () => {
  const serialized = JSON.stringify(VERIFICATION_SCOPES);
  expect(serialized).not.toContain("kws-codex-plan-executor");
  expect(serialized).not.toContain("kws-claude-plan-executor");
  expect(VERIFICATION_SCOPES.map(({ id }) => id)).not.toContain("codex-executor");
});

test("verification map has no migrated skill scopes", () => {
  expect(VERIFICATION_SCOPES.map(({ id }) => id)).toEqual([
    "docs",
    "console",
    "app",
    "package",
    "waygent-closure",
    "native",
    "waygent-skill",
    "codex-plan-runner",
    "claude-plan-runner",
    "claude-executor",
    "full-offline",
  ]);
});

test("reports unknown and Markdown paths alongside conservative selection", () => {
  const selection = selectVerification(["docs/README.md", "unexpected/new-surface.md"]);

  expect(selection.scopeIds).toEqual(["full-offline"]);
  expect(selection.unknownPaths).toEqual(["unexpected/new-surface.md"]);
  expect(selection.markdownFiles).toEqual(["docs/README.md", "unexpected/new-surface.md"]);
  expect(selection.reasons).toEqual(["unknown path: unexpected/new-surface.md"]);
});

test("selects a focused command for touched TypeScript tests", () => {
  const selection = selectVerification(["packages/orchestrator/tests/riskInference.test.ts"]);

  expect(selection.commands).toContainEqual({
    id: "focused-test:packages/orchestrator/tests/riskInference.test.ts",
    argv: ["bun", "test", "packages/orchestrator/tests/riskInference.test.ts"],
  });
});
