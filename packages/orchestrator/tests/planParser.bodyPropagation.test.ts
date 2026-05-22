import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";

const FIXTURE_WITH_PROSE = `
## Task 3: Implement Feature

Step 1: Do this thing.
- bullet line one
- bullet line two

Step 2: Then this thing.

\`\`\`yaml waygent-task
id: task_3
title: implement feature
dependencies: []
file_claims:
  - path: src/foo.ts
    mode: owned
verify:
  - bun test
risk: medium
\`\`\`
`;

const FIXTURE_WITH_EXPLICIT_INSTRUCTIONS = `
## Task 3: Implement Feature

Prose that should be ignored when yaml has instructions.

\`\`\`yaml waygent-task
id: task_3
title: implement feature
dependencies: []
file_claims:
  - path: src/foo.ts
    mode: owned
verify:
  - bun test
risk: medium
instructions:
  - explicit yaml instruction
\`\`\`
`;

describe("planParser — body propagation", () => {
  test("captures pre-yaml prose into instructions when yaml has no instructions", () => {
    const { tasks } = parseWaygentPlan(FIXTURE_WITH_PROSE);
    expect(tasks).toHaveLength(1);
    const joined = tasks[0]!.instructions.join("\n");
    expect(joined).toContain("Step 1: Do this thing");
    expect(joined).toContain("Step 2: Then this thing");
  });

  test("inherit_plan_prose=false disables capture", () => {
    const { tasks } = parseWaygentPlan(FIXTURE_WITH_PROSE, { inherit_plan_prose: false });
    expect(tasks[0]!.instructions).toEqual([]);
  });

  test("yaml instructions win over prose when both are present", () => {
    const { tasks } = parseWaygentPlan(FIXTURE_WITH_EXPLICIT_INSTRUCTIONS);
    expect(tasks[0]!.instructions).toEqual(["explicit yaml instruction"]);
  });
});
