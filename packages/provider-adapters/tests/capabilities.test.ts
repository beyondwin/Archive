import { describe, expect, test } from "bun:test";
import { acpCapabilityManifest, assertCapabilities, codexCapabilityManifest, fakeCapabilityManifest } from "../src";

describe("provider capabilities", () => {
  test("declares supported provider features", () => {
    expect(fakeCapabilityManifest.result_schema).toBe("runway.worker_result.v1");
    expect(codexCapabilityManifest.shell).toBe(true);
  });

  test("rejects unmet requirements before dispatch", () => {
    expect(() => assertCapabilities(acpCapabilityManifest, { file_edits: true })).toThrow(/file_edits/);
  });
});
