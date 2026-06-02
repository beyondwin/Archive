export interface ExpectedGeneratedOutput {
  path_glob: string;
  reason: string;
  evidence_refs: string[];
}

export interface GeneratedOutputDetectionInput {
  task_id: string;
  plan_text: string;
  verification_commands: string[];
}

export interface GeneratedOutputDetectionResult {
  task_id: string;
  expected_outputs: ExpectedGeneratedOutput[];
}

export interface ScopeGapReport {
  schema: "waygent.scope_gap_report.v1";
  run_id: string;
  task_id: string;
  status: "blocked";
  expected_outputs: ExpectedGeneratedOutput[];
  missing_claims: Array<{ path: string; mode: "owned"; reason: string }>;
  existing_allowed_write_globs: string[];
}

const ZOD_FIXTURE_OUTPUT: ExpectedGeneratedOutput = {
  path_glob: "front/tests/unit/__fixtures__/zod-schemas/*.json",
  reason: "zod fixture export writes frontend schema fixtures",
  evidence_refs: []
};

export function detectGeneratedOutputs(
  input: GeneratedOutputDetectionInput
): GeneratedOutputDetectionResult {
  const evidence = new Set<string>();

  for (const command of input.verification_commands) {
    if (command.includes("zod:export-fixtures")) {
      evidence.add(`command:${command}`);
    }
    if (command.includes("front/tests/unit/__fixtures__/zod-schemas")) {
      evidence.add(`command:${command}`);
    }
  }

  const normalizedPlan = input.plan_text.toLowerCase();
  if (
    normalizedPlan.includes("export fixtures") ||
    normalizedPlan.includes("zod fixtures") ||
    normalizedPlan.includes("schema fixtures") ||
    normalizedPlan.includes("generated fixtures")
  ) {
    evidence.add("plan:generated fixtures");
  }

  if (evidence.size === 0) {
    return { task_id: input.task_id, expected_outputs: [] };
  }

  return {
    task_id: input.task_id,
    expected_outputs: [
      {
        ...ZOD_FIXTURE_OUTPUT,
        evidence_refs: Array.from(evidence)
      }
    ]
  };
}

export function findMissingGeneratedClaims(input: {
  run_id: string;
  task_id: string;
  expected_outputs: ExpectedGeneratedOutput[];
  existing_allowed_write_globs: string[];
}): ScopeGapReport | null {
  const missing = input.expected_outputs
    .filter(
      (output) =>
        !input.existing_allowed_write_globs.some((claim) =>
          coversGlob(claim, output.path_glob)
        )
    )
    .map((output) => ({
      path: output.path_glob,
      mode: "owned" as const,
      reason: "generated output is not covered by task writable claims"
    }));

  if (missing.length === 0) {
    return null;
  }

  return {
    schema: "waygent.scope_gap_report.v1",
    run_id: input.run_id,
    task_id: input.task_id,
    status: "blocked",
    expected_outputs: input.expected_outputs,
    missing_claims: missing,
    existing_allowed_write_globs: input.existing_allowed_write_globs
  };
}

function coversGlob(claim: string, outputGlob: string): boolean {
  const normalizedClaim = normalizePath(claim);
  const normalizedOutput = normalizePath(outputGlob);

  if (normalizedClaim === normalizedOutput) return true;
  if (normalizedClaim.endsWith("/**")) {
    return normalizedOutput.startsWith(normalizedClaim.slice(0, -"/**".length));
  }
  if (normalizedOutput.endsWith("/*.json")) {
    return normalizedClaim === normalizedOutput.slice(0, -"/*.json".length);
  }
  return normalizedOutput.startsWith(`${normalizedClaim}/`);
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\/+/, "").replace(/\/+$/, "");
}
