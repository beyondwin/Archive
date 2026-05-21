import { existsSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describe, expect, test } from "bun:test";
import { writeArtifact } from "../src";

describe("artifact store", () => {
  test("writes artifact metadata with digest", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-artifacts-"));
    const artifact = writeArtifact(root, "worker/result.json", "{\"ok\":true}");
    expect(artifact.path).toBe("artifacts/worker/result.json");
    expect(artifact.sha256).toHaveLength(64);
    expect(artifact.byte_length).toBe(11);
    expect(existsSync(join(root, artifact.path))).toBe(true);
  });
});
