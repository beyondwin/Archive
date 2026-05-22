import { describe, expect, test } from "bun:test";
import { buildSpecManifest, specSliceForTask } from "../src/specManifest";

describe("spec manifest", () => {
  const spec = `
# Runtime Design

## F1. Plan Preflight

Plan preflight details.

### F2. Decisions Register

Decision register details.
`;

  test("maps explicit section references to task spec slices", () => {
    const manifest = buildSpecManifest({
      spec,
      spec_path: "design.md",
      tasks: [{
        id: "task_decisions",
        title: "Decisions",
        instructions: ["Implement F2 decisions register"]
      }]
    });

    const slice = specSliceForTask(spec, manifest, "task_decisions");

    expect(slice.fallback_used).toBe(false);
    expect(slice.sections_used).toEqual(["f2_decisions_register"]);
    expect(slice.text).toContain("Decision register details.");
    expect(slice.text).not.toContain("Plan preflight details.");
  });

  test("falls back to the full spec when no section matches", () => {
    const manifest = buildSpecManifest({
      spec,
      spec_path: "design.md",
      tasks: [{ id: "task_unknown", title: "Unknown", instructions: [] }]
    });

    const slice = specSliceForTask(spec, manifest, "task_unknown");

    expect(slice.fallback_used).toBe(true);
    expect(slice.text).toBe(spec);
  });

  test("preserves duplicate section titles with unique ids", () => {
    const duplicateSpec = `
## Shared Runtime

First section.

## Shared Runtime

Second section.
`;
    const manifest = buildSpecManifest({
      spec: duplicateSpec,
      spec_path: "design.md",
      tasks: []
    });

    expect(Object.keys(manifest.sections)).toEqual(["shared_runtime", "shared_runtime_2"]);
    expect(manifest.sections.shared_runtime?.title).toBe("Shared Runtime");
    expect(manifest.sections.shared_runtime_2?.title).toBe("Shared Runtime");
    expect(duplicateSpec.slice(...manifest.sections.shared_runtime!.range)).toContain("First section.");
    expect(duplicateSpec.slice(...manifest.sections.shared_runtime_2!.range)).toContain("Second section.");
  });
});
