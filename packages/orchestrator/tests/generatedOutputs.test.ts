import { describe, expect, test } from "bun:test";
import {
  detectGeneratedOutputs,
  findMissingGeneratedClaims
} from "../src/generatedOutputs";

describe("detectGeneratedOutputs", () => {
  test("detects zod fixture export outputs from commands and plan text", () => {
    const result = detectGeneratedOutputs({
      task_id: "task_contracts",
      plan_text: "Run zod:export-fixtures and commit generated fixtures.",
      verification_commands: [
        "pnpm --dir front zod:export-fixtures",
        "git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/"
      ]
    });

    expect(result.expected_outputs).toEqual([
      {
        path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
        reason: "zod fixture export writes frontend schema fixtures",
        evidence_refs: [
          "command:pnpm --dir front zod:export-fixtures",
          "command:git diff --exit-code front/tests/unit/__fixtures__/zod-schemas/",
          "plan:generated fixtures"
        ]
      }
    ]);
  });

  test("returns no outputs for unknown commands", () => {
    const result = detectGeneratedOutputs({
      task_id: "task_docs",
      plan_text: "Update operator docs.",
      verification_commands: ["git diff --check -- docs/operations/recovery.md"]
    });

    expect(result.expected_outputs).toEqual([]);
  });
});

describe("findMissingGeneratedClaims", () => {
  test("reports expected outputs not covered by owned claims", () => {
    const report = findMissingGeneratedClaims({
      run_id: "run_readmates",
      task_id: "task_contracts",
      existing_allowed_write_globs: [
        "front/scripts/export-zod-fixtures.ts",
        "server/src/test/kotlin/com/readmates/contract/FrontendZodSchemaContractTest.kt"
      ],
      expected_outputs: [
        {
          path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          reason: "zod fixture export writes frontend schema fixtures",
          evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
        }
      ]
    });

    expect(report).toEqual({
      schema: "waygent.scope_gap_report.v1",
      run_id: "run_readmates",
      task_id: "task_contracts",
      status: "blocked",
      expected_outputs: [
        {
          path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          reason: "zod fixture export writes frontend schema fixtures",
          evidence_refs: ["command:pnpm --dir front zod:export-fixtures"]
        }
      ],
      missing_claims: [
        {
          path: "front/tests/unit/__fixtures__/zod-schemas/*.json",
          mode: "owned",
          reason: "generated output is not covered by task writable claims"
        }
      ],
      existing_allowed_write_globs: [
        "front/scripts/export-zod-fixtures.ts",
        "server/src/test/kotlin/com/readmates/contract/FrontendZodSchemaContractTest.kt"
      ]
    });
  });
});
