import { expect, test } from "bun:test";
import { selectVerification } from "./verification-map";

const ids = (paths: string[]) => selectVerification(paths).scopeIds;

test("required scope matrix", () => {
  expect(ids(["README.md"])).toEqual(["docs"]);
  expect(ids(["docs/README.md"])).toEqual(["docs"]);
  expect(ids(["apps/console/src/App.tsx"])).toEqual(["console"]);
  expect(ids([
    "packages/orchestrator/src/index.ts",
    "packages/runway-control/src/scheduler.ts",
  ])).toEqual(["waygent-closure"]);
  expect(ids(["native/kernel/crates/kernel-cli/src/main.rs"])).toEqual(["native"]);
  expect(ids(["skills/kws-codex-plan-executor/scripts/cpe.py"]))
    .toEqual(["codex-executor"]);
  expect(ids(["skills/kws-claude-multi-agent-executor/scripts/kernel/kernel.py"]))
    .toEqual(["claude-executor"]);
  expect(ids(["unexpected/new-surface.txt"])).toEqual(["full-offline"]);
});

test("selects a focused command for touched TypeScript tests", () => {
  const selection = selectVerification(["packages/orchestrator/tests/riskInference.test.ts"]);

  expect(selection.commands).toContainEqual({
    id: "focused-test:packages/orchestrator/tests/riskInference.test.ts",
    argv: ["bun", "test", "packages/orchestrator/tests/riskInference.test.ts"],
  });
});

test("keeps the app scope when console and another app change together", () => {
  expect(ids([
    "apps/console/src/App.tsx",
    "apps/api/src/index.ts",
  ])).toEqual(["console", "app"]);
});
