import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";

const INLINE = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies: [task_a, task_b]
file_claims:
  - path: a
    mode: owned
verify:
  - printf hi
risk: low
\`\`\``;

const BLOCK = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies:
  - task_a
  - task_b
file_claims:
  - path: a
    mode: owned
verify:
  - printf hi
risk: low
\`\`\``;

const SINGLE_BARE = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies: task_a
file_claims:
  - path: a
    mode: owned
verify:
  - printf hi
risk: low
\`\`\``;

const EMPTY_BLOCK = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies:
file_claims:
  - path: a
    mode: owned
verify:
  - printf hi
risk: low
\`\`\``;

describe("planParser — dependencies dual form", () => {
  test("inline list parses", () => {
    const { tasks } = parseWaygentPlan(INLINE);
    expect(tasks[0]!.dependencies).toEqual(["task_a", "task_b"]);
  });

  test("block list parses identically", () => {
    const { tasks } = parseWaygentPlan(BLOCK);
    expect(tasks[0]!.dependencies).toEqual(["task_a", "task_b"]);
  });

  test("single bare token parses as a one-element list", () => {
    const { tasks } = parseWaygentPlan(SINGLE_BARE);
    expect(tasks[0]!.dependencies).toEqual(["task_a"]);
  });

  test("block form with no entries parses as an empty list", () => {
    const { tasks } = parseWaygentPlan(EMPTY_BLOCK);
    expect(tasks[0]!.dependencies).toEqual([]);
  });
});
