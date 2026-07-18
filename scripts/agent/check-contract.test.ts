import { afterEach, describe, expect, test } from "bun:test";
import { chmod, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { CURRENT_GUIDANCE_FILES } from "./contract";
import { checkContract, formatContractIssues } from "./check-contract";
import { VERIFICATION_SCOPES, type VerificationScope } from "./verification-map";

const EXECUTOR_GATES = [
  "skills/kws-codex-plan-executor/evals/run.sh",
  "skills/kws-claude-multi-agent-executor/evals/run.sh",
] as const;

const fixtureRoots: string[] = [];

afterEach(async () => {
  await Promise.all(fixtureRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

describe("checkContract", () => {
  test("accepts the repository contract", async () => {
    expect(await checkContract({ root: process.cwd() })).toEqual([]);
  });

  test("rejects duplicate verification scope IDs", async () => {
    const duplicate = { ...VERIFICATION_SCOPES[0]! };

    const issues = await checkContract({
      root: process.cwd(),
      verificationScopes: [...VERIFICATION_SCOPES, duplicate],
    });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification scope ID is duplicated: docs",
    }));
  });

  test("rejects conflicting verification command IDs", async () => {
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: ["docs/"], commands: [{ id: "shared", argv: ["first"] }] },
      { id: "console", matchers: ["apps/console/"], commands: [{ id: "shared", argv: ["second"] }] },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification command ID conflicts: shared",
    }));
  });

  test("rejects empty verification matchers and scopes without commands", async () => {
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: [], commands: [{ id: "docs", argv: ["docs"] }] },
      { id: "console", matchers: ["apps/console/"], commands: [] },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification scope has no matchers: docs",
    }));
    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification scope has no commands: console",
    }));
  });

  test("reports a missing active path", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: ["definitely-missing/"],
      requiredAgentFiles: [],
      trackedFiles: [],
    });
    expect(issues[0]?.code).toBe("missing_active_path");
  });

  test("rejects tracked local state", async () => {
    const issues = await checkContract({
      root: process.cwd(),
      requiredPaths: [],
      requiredAgentFiles: [],
      trackedFiles: [".waygent/runs/example.json"],
    });
    expect(issues.map((issue) => issue.code)).toContain("tracked_local_state");
  });

  test("formats issues as stable CLI lines", () => {
    expect(
      formatContractIssues([
        {
          code: "missing_active_path",
          path: "apps/missing",
          message: "required active path is missing",
        },
      ]),
    ).toBe("[missing_active_path] [apps/missing] required active path is missing");
  });

  test("reports an invalid required package script", async () => {
    const root = await createContractFixture();
    await writeFile(join(root, "package.json"), JSON.stringify({ scripts: { "agent:contract": "false" } }));

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({ code: "missing_package_script" }));
  });

  test("reports a non-executable executor gate", async () => {
    const root = await createContractFixture();
    await chmod(join(root, EXECUTOR_GATES[0]), 0o644);

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "non_executable_gate",
      path: EXECUTOR_GATES[0],
    }));
  });

  test("reports a directory where an executor gate must be a file", async () => {
    const root = await createContractFixture();
    await rm(join(root, EXECUTOR_GATES[0]));
    await mkdir(join(root, EXECUTOR_GATES[0]));

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "non_executable_gate",
      path: EXECUTOR_GATES[0],
    }));
  });

  test("reports a directory where guidance requires a readable regular file", async () => {
    const root = await createContractFixture();
    await rm(join(root, "GEMINI.md"));
    await mkdir(join(root, "GEMINI.md"));

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_guidance_file",
      path: "GEMINI.md",
    }));
  });

  test("reports a directory where a required agent file must be a readable regular file", async () => {
    const root = await createContractFixture();
    await rm(join(root, "GEMINI.md"));
    await mkdir(join(root, "GEMINI.md"));

    const issues = await checkContract({
      root,
      requiredPaths: [],
      requiredAgentFiles: ["GEMINI.md"],
      trackedFiles: [],
    });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "missing_agent_file",
      path: "GEMINI.md",
    }));
  });

  test("detects a multiline claim that presents the removed path as primary", async () => {
    const root = await createContractFixture();
    await writeFile(join(root, "GEMINI.md"), "Primary location:\ncomponents/agentlens\n");

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("does not let a retired mention mask a later primary claim", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "The old components/agentlens path was removed.\nPrimary location: components/agentlens\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("surfaces a failed git tracked-file scan", async () => {
    const root = await createContractFixture();

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "tracked_file_scan_failed",
      path: "git ls-files -z",
    }));
  });

  test("CLI prints stable issues and exits nonzero for a failed tracked-file scan", async () => {
    const root = await createContractFixture();
    const script = join(process.cwd(), "scripts/agent/check-contract.ts");
    const child = Bun.spawn(["bun", script], { cwd: root, stdout: "pipe", stderr: "pipe" });

    expect(await child.exited).toBe(1);
    expect(await new Response(child.stdout).text()).toContain(
      "[tracked_file_scan_failed] [git ls-files -z] unable to list tracked files",
    );
  });
});

async function createContractFixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "agent-contract-"));
  fixtureRoots.push(root);

  for (const path of CURRENT_GUIDANCE_FILES) {
    await writeFixtureFile(root, path, "guidance\n");
  }
  await writeFixtureFile(root, "package.json", JSON.stringify({
    scripts: { "agent:contract": "bun run scripts/agent/check-contract.ts" },
  }));
  for (const path of EXECUTOR_GATES) {
    await writeFixtureFile(root, path, "#!/bin/sh\nexit 0\n");
    await chmod(join(root, path), 0o755);
  }
  return root;
}

async function writeFixtureFile(root: string, path: string, contents: string): Promise<void> {
  const file = join(root, path);
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, contents);
}
