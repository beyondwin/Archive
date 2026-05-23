import { describe, expect, it } from "bun:test";
import { parseWaygentPlan } from "../src/planParser";

const FIXTURE = `# Plan

\`\`\`yaml waygent-task
id: T1
title: test isolated
dependencies: []
file_claims:
  - path: a.ts
    mode: owned
risk: low
verify:
  - bun test
verify_isolation: isolated
\`\`\`

\`\`\`yaml waygent-task
id: T2
title: test default
dependencies: []
file_claims:
  - path: b.ts
    mode: owned
risk: low
verify:
  - bun test
\`\`\`

\`\`\`yaml waygent-task
id: T3
title: test auto
dependencies: []
file_claims:
  - path: c.ts
    mode: owned
risk: low
verify:
  - bun test
verify_isolation: auto
\`\`\`

\`\`\`yaml waygent-task
id: T4
title: test fast
dependencies: []
file_claims:
  - path: d.ts
    mode: owned
risk: low
verify:
  - bun test
verify_isolation: fast
\`\`\`
`;

describe("verify_isolation field", () => {
  it("parses explicit isolated value", () => {
    const plan = parseWaygentPlan(FIXTURE);
    const t1 = plan.tasks.find((t) => t.id === "T1");
    expect(t1?.verify_isolation).toBe("isolated");
  });

  it("omits the field on tasks that do not set it", () => {
    const plan = parseWaygentPlan(FIXTURE);
    const t2 = plan.tasks.find((t) => t.id === "T2");
    expect(t2?.verify_isolation).toBeUndefined();
  });

  it("parses auto value", () => {
    const plan = parseWaygentPlan(FIXTURE);
    const t3 = plan.tasks.find((t) => t.id === "T3");
    expect(t3?.verify_isolation).toBe("auto");
  });

  it("parses fast value", () => {
    const plan = parseWaygentPlan(FIXTURE);
    const t4 = plan.tasks.find((t) => t.id === "T4");
    expect(t4?.verify_isolation).toBe("fast");
  });
});
