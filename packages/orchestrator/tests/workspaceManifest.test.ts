import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import {
  detectManifestDrift,
  enumerateWorkspaceManifest
} from "../src/isolatedStrategy/workspaceManifest";

function makeWorkspace(): string {
  return mkdtempSync(join(tmpdir(), "waygent-workspace-manifest-"));
}

function writePackage(workspace: string, dir: string, contents: unknown): void {
  const pkgDir = join(workspace, "packages", dir);
  mkdirSync(pkgDir, { recursive: true });
  writeFileSync(join(pkgDir, "package.json"), JSON.stringify(contents));
}

describe("enumerateWorkspaceManifest", () => {
  test("returns @waygent/* packages sorted by name with relative paths", () => {
    const workspace = makeWorkspace();
    writePackage(workspace, "orchestrator", { name: "@waygent/orchestrator", version: "0.1.0" });
    writePackage(workspace, "contracts", { name: "@waygent/contracts", version: "0.1.0" });

    const manifest = enumerateWorkspaceManifest(workspace);

    expect(manifest.packages).toEqual([
      { name: "@waygent/contracts", relative_path: "packages/contracts" },
      { name: "@waygent/orchestrator", relative_path: "packages/orchestrator" }
    ]);
  });

  test("ignores non-@waygent packages, malformed package.json, and missing name", () => {
    const workspace = makeWorkspace();
    writePackage(workspace, "orchestrator", { name: "@waygent/orchestrator", version: "0.1.0" });
    writePackage(workspace, "third-party", { name: "left-pad", version: "1.0.0" });
    writePackage(workspace, "no-name", { version: "0.0.1" });
    // malformed package.json (raw write of broken JSON)
    const brokenDir = join(workspace, "packages", "broken");
    mkdirSync(brokenDir, { recursive: true });
    writeFileSync(join(brokenDir, "package.json"), "{ not json");

    const manifest = enumerateWorkspaceManifest(workspace);

    expect(manifest.packages).toEqual([
      { name: "@waygent/orchestrator", relative_path: "packages/orchestrator" }
    ]);
  });

  test("skips package directories without a package.json", () => {
    const workspace = makeWorkspace();
    mkdirSync(join(workspace, "packages", "empty-dir"), { recursive: true });
    writePackage(workspace, "orchestrator", { name: "@waygent/orchestrator", version: "0.1.0" });

    const manifest = enumerateWorkspaceManifest(workspace);

    expect(manifest.packages).toEqual([
      { name: "@waygent/orchestrator", relative_path: "packages/orchestrator" }
    ]);
  });

  test("returns empty manifest when packages/ does not exist", () => {
    const workspace = makeWorkspace();
    const manifest = enumerateWorkspaceManifest(workspace);
    expect(manifest.packages).toEqual([]);
  });

  test("rejects name fields that are not strings", () => {
    const workspace = makeWorkspace();
    writePackage(workspace, "weird", { name: 123, version: "0.0.1" });
    const manifest = enumerateWorkspaceManifest(workspace);
    expect(manifest.packages).toEqual([]);
  });
});

describe("detectManifestDrift", () => {
  test("reports no drift when manifests are identical", () => {
    const a = {
      packages: [
        { name: "@waygent/a", relative_path: "packages/a" },
        { name: "@waygent/b", relative_path: "packages/b" }
      ]
    };
    const drift = detectManifestDrift(a, a);
    expect(drift).toEqual({ drifted: false, added: [], removed: [] });
  });

  test("detects added packages in the current manifest", () => {
    const snapshot = {
      packages: [{ name: "@waygent/a", relative_path: "packages/a" }]
    };
    const current = {
      packages: [
        { name: "@waygent/a", relative_path: "packages/a" },
        { name: "@waygent/c", relative_path: "packages/c" },
        { name: "@waygent/b", relative_path: "packages/b" }
      ]
    };
    const drift = detectManifestDrift(snapshot, current);
    expect(drift).toEqual({ drifted: true, added: ["@waygent/b", "@waygent/c"], removed: [] });
  });

  test("detects removed packages from the snapshot", () => {
    const snapshot = {
      packages: [
        { name: "@waygent/a", relative_path: "packages/a" },
        { name: "@waygent/b", relative_path: "packages/b" }
      ]
    };
    const current = {
      packages: [{ name: "@waygent/a", relative_path: "packages/a" }]
    };
    const drift = detectManifestDrift(snapshot, current);
    expect(drift).toEqual({ drifted: true, added: [], removed: ["@waygent/b"] });
  });

  test("reports both added and removed when packages diverge", () => {
    const snapshot = {
      packages: [
        { name: "@waygent/a", relative_path: "packages/a" },
        { name: "@waygent/b", relative_path: "packages/b" }
      ]
    };
    const current = {
      packages: [
        { name: "@waygent/a", relative_path: "packages/a" },
        { name: "@waygent/c", relative_path: "packages/c" }
      ]
    };
    const drift = detectManifestDrift(snapshot, current);
    expect(drift).toEqual({ drifted: true, added: ["@waygent/c"], removed: ["@waygent/b"] });
  });

  test("does not treat a relative_path change for the same name as drift", () => {
    const snapshot = {
      packages: [{ name: "@waygent/a", relative_path: "packages/a" }]
    };
    const current = {
      packages: [{ name: "@waygent/a", relative_path: "packages/renamed-a" }]
    };
    const drift = detectManifestDrift(snapshot, current);
    expect(drift).toEqual({ drifted: false, added: [], removed: [] });
  });
});
