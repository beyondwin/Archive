import { afterEach, describe, expect, test } from "bun:test";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import {
  CURRENT_GUIDANCE_FILES,
  REQUIRED_AGENT_FILES,
  REQUIRED_PATHS,
  TOOL_GUIDANCE_FILES,
} from "./contract";
import { checkContract, formatContractIssues } from "./check-contract";
import { VERIFICATION_SCOPES, type VerificationScope } from "./verification-map";

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

  test("rejects an app scope made unreachable by the narrower console scope", async () => {
    const scopes: VerificationScope[] = [
      {
        id: "console",
        matchers: ["apps/console/"],
        commands: [{ id: "console", argv: ["bun", "test", "src"], cwd: "apps/console" }],
        allowOverlapWith: ["app"],
      },
      {
        id: "app",
        matchers: ["apps/console/"],
        commands: [{ id: "app", argv: ["bun", "run", "typecheck"] }],
        allowOverlapWith: ["console"],
      },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification scope is unreachable: app",
    }));
  });

  test("rejects undeclared overlapping scope matchers", async () => {
    const scopes: VerificationScope[] = [
      { id: "app", matchers: ["apps/"], commands: [{ id: "app", argv: ["bun", "run", "typecheck"] }] },
      { id: "console", matchers: ["apps/console/"], commands: [{ id: "console", argv: ["bun", "test", "src"], cwd: "apps/console" }] },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification scope matchers overlap without an allowance: app \"apps/\" <-> console \"apps/console/\"",
    }));
  });

  test("rejects empty command argv", async () => {
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: ["docs/"], commands: [{ id: "invalid", argv: [] }] },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification command argv must contain only non-empty strings: invalid",
    }));
  });

  test.each([
    ["missing", "missing-command-cwd"],
    ["not a directory", "package.json"],
  ])("rejects a command cwd that is $0", async (_name, cwd) => {
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: ["docs/"], commands: [{ id: "invalid-cwd", argv: ["bun", "test"], cwd }] },
    ];

    const issues = await checkContract({ root: process.cwd(), verificationScopes: scopes });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: `verification command cwd must be an existing repository directory: invalid-cwd cwd=${JSON.stringify(cwd)}`,
    }));
  });

  test("rejects a referenced package script that does not exist", async () => {
    const root = await createContractFixture();
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: ["docs/"], commands: [{ id: "missing-script", argv: ["bun", "run", "not-present"] }] },
    ];

    const issues = await checkContract({ root, verificationScopes: scopes, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "invalid_verification_map",
      message: "verification command references a missing package script: missing-script script=\"not-present\" cwd=\".\"",
    }));
  });

  test.each([
    ["missing", "./missing-gate.sh", undefined],
    ["non-executable", "./gate.sh", 0o644],
  ])("rejects a $0 relative executable", async (_name, executable, mode) => {
    const root = await createContractFixture();
    if (mode !== undefined) {
      await writeFixtureFile(root, executable.slice(2), "#!/bin/sh\nexit 0\n");
      await chmod(join(root, executable), mode);
    }
    const scopes: VerificationScope[] = [
      { id: "docs", matchers: ["docs/"], commands: [{ id: "relative-gate", argv: [executable] }] },
    ];

    const issues = await checkContract({ root, verificationScopes: scopes, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "non_executable_gate",
      path: executable.slice(2),
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
    ).toBe("[missing_active_path] path=\"apps/missing\" required active path is missing");
  });

  test("JSON-encodes untrusted contract paths in CLI output", () => {
    const path = "bad\n\u001b[31m[forged]";

    const output = formatContractIssues([{
      code: "missing_active_path",
      path,
      message: "required active path is missing",
    }]);

    expect(output).toBe(
      "[missing_active_path] path=\"bad\\n\\u001b[31m[forged]\" required active path is missing",
    );
    expect(output.split("\n")).toHaveLength(1);
  });

  test("reports an invalid required package script", async () => {
    const root = await createContractFixture();
    await writeFile(join(root, "package.json"), JSON.stringify({ scripts: { "agent:contract": "false" } }));

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({ code: "missing_package_script" }));
  });

  test.each([
    ["agent:contract", "false"],
    ["agent:test", "false"],
    ["agent:verify", "false"],
  ])("requires the exact %s package entry point", async (name, value) => {
    const root = await createContractFixture();
    const packageJson = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    packageJson.scripts[name] = value;
    await writeFile(join(root, "package.json"), JSON.stringify(packageJson));

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [], verificationScopes: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "missing_package_script",
      message: `missing required package script: ${name}`,
    }));
  });

  test("accepts a contract fixture without repository-local execpolicy", async () => {
    const root = await createContractFixture();

    const issues = await checkContract({
      root,
      requiredPaths: [],
      requiredAgentFiles: [],
      trackedFiles: [],
      verificationScopes: [],
    });

    expect(issues).toEqual([]);
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

  test("detects an active root AgentLens path spelling", async () => {
    const root = await createContractFixture();
    await writeFile(join(root, "GEMINI.md"), "Primary location: AgentLens/runtime\n");

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("preserves historical root AgentLens path context", async () => {
    const root = await createContractFixture();
    await writeFile(join(root, "GEMINI.md"), "Historical AgentLens/runtime was removed.\n");

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).not.toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("does not treat a negated removal as historical context", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "AgentLens/runtime is not removed and remains the primary location.\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("central guidance inventory covers root, subtree, and tool files", () => {
    expect(CURRENT_GUIDANCE_FILES).toEqual(expect.arrayContaining([
      ...REQUIRED_AGENT_FILES,
      ...TOOL_GUIDANCE_FILES,
      "PLANS.md",
      "code_review.md",
    ]));
  });

  test("does not require skill or legacy executor trees", () => {
    expect(REQUIRED_PATHS.filter((path) => path.startsWith("skills/"))).toEqual([]);
    expect(REQUIRED_AGENT_FILES.filter((path) => path.startsWith("skills/"))).toEqual([]);
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

  test("does not let a retired Markdown bullet mask a later active bullet", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "- Historical: components/agentlens was removed\n- Primary: components/agentlens\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("preserves retired ancestor context for a nested Markdown list item", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "- Historical paths were removed:\n  - Primary location: components/agentlens\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).not.toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("preserves retired ancestor context for a loose nested Markdown list", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "- Historical paths were removed:\n\n  - Primary location: components/agentlens\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).not.toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("closes retired list context for an active sibling after a blank line", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "- Historical paths were removed:\n\n- Primary location: components/agentlens\n",
    );

    const issues = await checkContract({ root, requiredPaths: [], requiredAgentFiles: [], trackedFiles: [] });

    expect(issues).toContainEqual(expect.objectContaining({
      code: "stale_active_claim",
      path: "GEMINI.md",
    }));
  });

  test("keeps prose paragraphs independent across a blank line", async () => {
    const root = await createContractFixture();
    await writeFile(
      join(root, "GEMINI.md"),
      "Historical components/agentlens path was removed\n\nPrimary location: components/agentlens\n",
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
      "[tracked_file_scan_failed] path=\"git ls-files -z\" unable to list tracked files",
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
    scripts: {
      "agent:contract": "bun run scripts/agent/check-contract.ts",
      "agent:test": "bun test scripts/agent",
      "agent:verify": "bun run scripts/agent/verify.ts",
    },
  }));
  return root;
}

async function writeFixtureFile(root: string, path: string, contents: string): Promise<void> {
  const file = join(root, path);
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, contents);
}
