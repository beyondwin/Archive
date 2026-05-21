import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";
import { buildTaskGraphFromPlan } from "../src/taskGraph";

describe("Waygent task graph conversion", () => {
  test("marks root tasks ready and dependent tasks pending", () => {
    const parsed = parseWaygentPlan(`
\`\`\`yaml waygent-task
id: task_a
title: A
dependencies: []
file_claims:
  - path: README.md
    mode: owned
risk: low
verify:
  - bun test
\`\`\`
\`\`\`yaml waygent-task
id: task_b
title: B
dependencies: [task_a]
file_claims:
  - path: packages/orchestrator/src/taskGraph.ts
    mode: owned
risk: high
verify:
  - bun run check
\`\`\`
`);

    const graph = buildTaskGraphFromPlan(parsed);

    expect(graph.tasks.get("task_a")?.status).toBe("READY");
    expect(graph.tasks.get("task_b")?.status).toBe("PENDING");
    expect(graph.tasks.get("task_b")?.resource_locks).toEqual([]);
  });
});
