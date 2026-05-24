import { describe, expect, test } from "bun:test";
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { attestProviderProcessOptions, probeProviderHelp } from "../src/capabilityProbe";

describe("provider capability probe", () => {
  test("omits unsupported Codex reasoning flags while preserving requested evidence", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      model: "gpt-5.5",
      effort: "high"
    }, {
      status: "ready",
      stdout: "Usage: codex exec [OPTIONS]\n  --model <MODEL>\n",
      stderr: "",
      exit_code: 0
    });

    expect(attestation.options).toEqual({
      executable: "codex",
      args: ["exec", "--json", "-"],
      model: "gpt-5.5"
    });
    expect(attestation.capability).toMatchObject({
      provider: "codex",
      requested_reasoning: "high",
      applied_reasoning: null,
      reason: "unsupported_by_cli"
    });
  });

  test("keeps supported Codex reasoning flags", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      effort: "high"
    }, {
      status: "ready",
      stdout: "Usage: codex exec [OPTIONS]\n  --reasoning <EFFORT>\n",
      stderr: "",
      exit_code: 0
    });

    expect(attestation.options.effort).toBe("high");
    expect(attestation.capability.applied_reasoning).toBe("high");
  });

  test("does not treat custom provider executables as failed CLI probes", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: process.execPath,
      args: ["worker.mjs"],
      model: "gpt-5.5",
      effort: "high"
    }, {
      status: "failed",
      stdout: "",
      stderr: "Cannot find module 'exec'",
      exit_code: 1
    });

    expect(attestation.options).toEqual({
      executable: process.execPath,
      args: ["worker.mjs"]
    });
    expect(attestation.capability).toMatchObject({
      provider: "codex",
      requested_model: "gpt-5.5",
      applied_model: null,
      requested_reasoning: "high",
      applied_reasoning: null,
      reason: "custom_executable"
    });
  });

  test("does not execute custom provider binaries during CLI help probing", () => {
    const probe = probeProviderHelp("codex", {
      executable: process.execPath,
      args: ["worker.mjs"]
    });

    expect(probe).toEqual({
      status: "failed",
      stdout: "",
      stderr: "",
      exit_code: null
    });
  });

  test("detects Codex reasoning support from stderr help output", () => {
    const attestation = attestProviderProcessOptions("codex", {
      executable: "codex",
      args: ["exec", "--json", "-"],
      effort: "high"
    }, {
      status: "ready",
      stdout: "",
      stderr: "Usage: codex exec [OPTIONS]\n  --reasoning <EFFORT>\n",
      exit_code: 0
    });

    expect(attestation.options.effort).toBe("high");
    expect(attestation.capability).toMatchObject({
      applied_reasoning: "high",
      reason: "supported"
    });
  });

  test("times out hanging provider CLI help probes", () => {
    const dir = mkdtempSync(join(tmpdir(), "waygent-provider-probe-"));
    const executable = join(dir, "codex");
    writeFileSync(executable, "#!/usr/bin/env sh\nsleep 2\n");
    chmodSync(executable, 0o755);

    const probe = probeProviderHelp("codex", {
      executable,
      args: ["exec", "--json", "-"],
      timeout_ms: 10
    });

    expect(probe.status).toBe("failed");
    expect(probe.exit_code).toBeNull();
    expect(probe.stderr).toContain("timed out");
  });
});
