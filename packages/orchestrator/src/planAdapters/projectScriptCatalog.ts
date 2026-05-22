import { readFileSync } from "node:fs";
import { join } from "node:path";

export type CatalogSource = "npm" | "pnpm" | "yarn" | "bun" | "make" | "poetry" | "project";

export interface ProjectScriptCatalog {
  commands: ReadonlySet<string>;
  sources: ReadonlyMap<string, CatalogSource>;
  workspace_root: string;
}

const NPM_RUNNERS: ReadonlyArray<{ runner: string; source: CatalogSource }> = [
  { runner: "npm run", source: "npm" },
  { runner: "pnpm run", source: "pnpm" },
  { runner: "bun run", source: "bun" },
  { runner: "yarn", source: "yarn" }
];

export function buildProjectScriptCatalog(workspace: string): ProjectScriptCatalog {
  const commands = new Map<string, CatalogSource>();
  collectFromPackageJson(workspace, commands);
  collectFromMakefile(workspace, commands);
  collectFromPyproject(workspace, commands);
  return {
    commands: new Set(commands.keys()),
    sources: commands,
    workspace_root: workspace
  };
}

export function isCommandInCatalog(command: string, catalog: ProjectScriptCatalog): boolean {
  const normalized = command.trim();
  if (!normalized) return false;
  if (catalog.commands.has(normalized)) return true;
  for (const entry of catalog.commands) {
    if (normalized.startsWith(`${entry} `)) return true;
  }
  return false;
}

function safeRead(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function safeParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function collectFromPackageJson(workspace: string, out: Map<string, CatalogSource>): void {
  const raw = safeRead(join(workspace, "package.json"));
  if (raw === null) return;
  const parsed = safeParseJson(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return;
  const scripts = (parsed as { scripts?: unknown }).scripts;
  if (!scripts || typeof scripts !== "object" || Array.isArray(scripts)) return;
  for (const name of Object.keys(scripts as Record<string, unknown>)) {
    if (!name) continue;
    for (const { runner, source } of NPM_RUNNERS) {
      addCommand(out, `${runner} ${name}`, source);
    }
  }
}

function collectFromMakefile(workspace: string, out: Map<string, CatalogSource>): void {
  const raw = safeRead(join(workspace, "Makefile"));
  if (raw === null) return;
  const lines = raw.split(/\r?\n/);
  const targetPattern = /^([a-zA-Z][a-zA-Z0-9_-]*):/;
  for (const line of lines) {
    if (line.startsWith(".PHONY:")) continue;
    const match = line.match(targetPattern);
    if (!match || !match[1]) continue;
    addCommand(out, `make ${match[1]}`, "make");
  }
}

function collectFromPyproject(workspace: string, out: Map<string, CatalogSource>): void {
  const raw = safeRead(join(workspace, "pyproject.toml"));
  if (raw === null) return;
  for (const name of extractTomlTableKeys(raw, "tool.poetry.scripts")) {
    addCommand(out, `poetry run ${name}`, "poetry");
    addCommand(out, name, "poetry");
  }
  for (const name of extractTomlTableKeys(raw, "project.scripts")) {
    addCommand(out, name, "project");
  }
}

function extractTomlTableKeys(raw: string, table: string): string[] {
  const escaped = table.replace(/\./g, "\\.");
  const headerPattern = new RegExp(`^\\[${escaped}\\]\\s*$`, "m");
  const headerMatch = raw.match(headerPattern);
  if (!headerMatch || headerMatch.index === undefined) return [];
  const start = headerMatch.index + headerMatch[0].length;
  const rest = raw.slice(start);
  const nextHeader = rest.search(/^\s*\[/m);
  const section = nextHeader >= 0 ? rest.slice(0, nextHeader) : rest;
  const keys: string[] = [];
  for (const line of section.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_\-]*)\s*=/);
    if (match && match[1]) keys.push(match[1]);
  }
  return keys;
}

function addCommand(out: Map<string, CatalogSource>, command: string, source: CatalogSource): void {
  if (!out.has(command)) out.set(command, source);
}
