import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";

const plan = `
# Demo Plan

### Task 1: Prepare
\`\`\`yaml waygent-task
id: task_prepare
title: Prepare workspace
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - bun test ./packages/orchestrator/tests
\`\`\`

### Task 2: Verify
\`\`\`yaml waygent-task
id: task_verify
title: Verify output
dependencies: [task_prepare]
file_claims:
  - path: packages/orchestrator/src/orchestrator.ts
    mode: owned
risk: medium
verify:
  - bun run check
\`\`\`
`;

describe("Waygent plan parser", () => {
  test("parses waygent-task blocks into typed task specs", () => {
    const parsed = parseWaygentPlan(plan);

    expect(parsed.tasks).toHaveLength(2);
    expect(parsed.tasks[0]).toMatchObject({
      id: "task_prepare",
      title: "Prepare workspace",
      dependencies: [],
      risk: "low"
    });
    expect(parsed.tasks[0]?.file_claims).toEqual([{ path: "README.md", mode: "owned" }]);
    expect(parsed.tasks[1]?.dependencies).toEqual(["task_prepare"]);
    expect(parsed.tasks[1]?.verification_commands).toEqual(["bun run check"]);
  });

  test("rejects missing task ids", () => {
    expect(() =>
      parseWaygentPlan(`
\`\`\`yaml waygent-task
title: Missing id
dependencies: []
file_claims: []
risk: low
verify: []
\`\`\`
`)
    ).toThrow("missing required waygent-task fields: id");
  });
});
