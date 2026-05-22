import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildProjectScriptCatalog,
  isCommandInCatalog
} from "../src/planAdapters/projectScriptCatalog";

let workspace: string;

beforeEach(() => {
  workspace = mkdtempSync(join(tmpdir(), "psc-test-"));
});

afterEach(() => {
  rmSync(workspace, { recursive: true, force: true });
});

describe("buildProjectScriptCatalog", () => {
  test("emits npm/pnpm/bun/yarn variants for each package.json script", () => {
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({ scripts: { test: "bun test", lint: "eslint ." } })
    );

    const catalog = buildProjectScriptCatalog(workspace);

    expect(catalog.commands.has("npm run test")).toBe(true);
    expect(catalog.commands.has("pnpm run test")).toBe(true);
    expect(catalog.commands.has("bun run test")).toBe(true);
    expect(catalog.commands.has("yarn test")).toBe(true);
    expect(catalog.commands.has("npm run lint")).toBe(true);
    expect(catalog.sources.get("npm run test")).toBe("npm");
    expect(catalog.sources.get("bun run lint")).toBe("bun");
  });

  test("emits make targets and skips .PHONY", () => {
    writeFileSync(
      join(workspace, "Makefile"),
      [".PHONY: test", "test:", "\tbun test", "build:", "\tbun run build"].join("\n")
    );

    const catalog = buildProjectScriptCatalog(workspace);

    expect(catalog.commands.has("make test")).toBe(true);
    expect(catalog.commands.has("make build")).toBe(true);
    expect(catalog.sources.get("make test")).toBe("make");
  });

  test("emits poetry and project script entries from pyproject.toml", () => {
    writeFileSync(
      join(workspace, "pyproject.toml"),
      [
        "[tool.poetry.scripts]",
        "lint = 'pkg.lint:main'",
        "fmt = 'pkg.fmt:main'",
        "",
        "[project.scripts]",
        "mytool = 'pkg.cli:main'",
        ""
      ].join("\n")
    );

    const catalog = buildProjectScriptCatalog(workspace);

    expect(catalog.commands.has("poetry run lint")).toBe(true);
    expect(catalog.commands.has("lint")).toBe(true);
    expect(catalog.commands.has("poetry run fmt")).toBe(true);
    expect(catalog.commands.has("mytool")).toBe(true);
    expect(catalog.sources.get("poetry run lint")).toBe("poetry");
  });

  test("merges multiple sources without duplicates and tracks attribution", () => {
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({ scripts: { test: "bun test" } })
    );
    writeFileSync(join(workspace, "Makefile"), ["test:", "\techo test"].join("\n"));

    const catalog = buildProjectScriptCatalog(workspace);

    expect(catalog.commands.size).toBe(catalog.sources.size);
    expect(catalog.commands.has("bun run test")).toBe(true);
    expect(catalog.commands.has("make test")).toBe(true);
  });

  test("non-throwing on missing or malformed inputs", () => {
    writeFileSync(join(workspace, "package.json"), "{not json");
    mkdirSync(join(workspace, "sub"));

    const catalog = buildProjectScriptCatalog(workspace);

    expect(catalog.commands.size).toBe(0);
    expect(catalog.workspace_root).toBe(workspace);
  });
});

describe("isCommandInCatalog", () => {
  test("exact match wins", () => {
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({ scripts: { lint: "eslint ." } })
    );
    const catalog = buildProjectScriptCatalog(workspace);

    expect(isCommandInCatalog("npm run lint", catalog)).toBe(true);
  });

  test("accepts prefix with argument list", () => {
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({ scripts: { lint: "eslint ." } })
    );
    const catalog = buildProjectScriptCatalog(workspace);

    expect(isCommandInCatalog("npm run lint -- --fix", catalog)).toBe(true);
  });

  test("rejects near-misses with different suffix word", () => {
    writeFileSync(
      join(workspace, "package.json"),
      JSON.stringify({ scripts: { lint: "eslint ." } })
    );
    const catalog = buildProjectScriptCatalog(workspace);

    expect(isCommandInCatalog("npm run linter", catalog)).toBe(false);
  });
});
