import { access, readFile, stat } from "node:fs/promises";
import { constants } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import {
  CURRENT_GUIDANCE_FILES,
  LOCAL_STATE_PATTERN,
  REQUIRED_AGENT_FILES,
  REQUIRED_PATHS,
  type ContractIssue,
} from "./contract";
import {
  VERIFICATION_SCOPES,
  VERIFICATION_TEST_ROOTS,
  type CommandSpec,
  type VerificationScope,
} from "./verification-map";

const REQUIRED_PACKAGE_SCRIPTS = {
  "agent:contract": "bun run scripts/agent/check-contract.ts",
  "agent:test": "bun test scripts/agent",
  "agent:verify": "bun run scripts/agent/verify.ts",
} as const;

const ACTIVE_CLAIM = /\b(?:active|current|primary)\b/i;

export interface CheckContractOptions {
  root?: string;
  requiredPaths?: readonly string[];
  requiredAgentFiles?: readonly string[];
  trackedFiles?: readonly string[];
  verificationScopes?: readonly VerificationScope[];
}

export async function checkContract(
  options: CheckContractOptions = {},
): Promise<ContractIssue[]> {
  const root = resolve(options.root ?? process.cwd());
  const requiredPaths = options.requiredPaths ?? REQUIRED_PATHS;
  const requiredAgentFiles = options.requiredAgentFiles ?? REQUIRED_AGENT_FILES;
  const verificationScopes = options.verificationScopes ?? VERIFICATION_SCOPES;
  const verificationCommands = [
    ...verificationScopes.flatMap(({ commands }) => commands),
    ...(options.verificationScopes === undefined
      ? VERIFICATION_TEST_ROOTS.map(({ command }) => command)
      : []),
  ];
  const issues: ContractIssue[] = [];

  issues.push(...checkVerificationMap(verificationScopes, verificationCommands));
  issues.push(...await checkVerificationCommands(root, verificationCommands));

  for (const path of requiredPaths) {
    if (!await exists(join(root, path))) {
      issues.push({
        code: "missing_active_path",
        path,
        message: "required active path is missing",
      });
    }
  }

  for (const path of requiredAgentFiles) {
    if (!await isReadableRegularFile(join(root, path))) {
      issues.push({
        code: "missing_agent_file",
        path,
        message: "required agent guidance file is missing or is not a readable regular file",
      });
    }
  }

  issues.push(...await checkGuidance(root));
  issues.push(...await checkPackageScripts(root));

  const scan = options.trackedFiles === undefined ? await listTrackedFiles(root) : undefined;
  if (scan?.issue) {
    issues.push(scan.issue);
  }
  const trackedFiles = options.trackedFiles ?? scan?.files ?? [];
  for (const path of trackedFiles) {
    if (LOCAL_STATE_PATTERN.test(path)) {
      issues.push({
        code: "tracked_local_state",
        path,
        message: "local runtime state must not be tracked",
      });
    }
  }

  return issues;
}

export function formatContractIssues(
  issues: readonly ContractIssue[],
): string {
  return issues.map((issue) =>
    `[${issue.code}] path=${JSON.stringify(issue.path)} ${issue.message}`
  ).join("\n");
}

async function checkGuidance(root: string): Promise<ContractIssue[]> {
  const issues: ContractIssue[] = [];

  for (const path of CURRENT_GUIDANCE_FILES) {
    const file = join(root, path);
    if (!await isReadableRegularFile(file)) {
      issues.push({
        code: "invalid_guidance_file",
        path,
        message: "current guidance file must be a readable regular file",
      });
      continue;
    }

    let contents: string;
    try {
      contents = await readFile(file, "utf8");
    } catch {
      issues.push({
        code: "invalid_guidance_file",
        path,
        message: "current guidance file could not be read",
      });
      continue;
    }

    if (hasStaleActiveClaim(contents)) {
      issues.push({
        code: "stale_active_claim",
        path,
        message: "guidance presents a removed AgentLens path as active",
      });
    }
  }

  return issues;
}

async function checkPackageScripts(root: string): Promise<ContractIssue[]> {
  const path = "package.json";
  try {
    const packageJson = JSON.parse(await readFile(join(root, path), "utf8")) as {
      scripts?: Record<string, unknown>;
    };
    return Object.entries(REQUIRED_PACKAGE_SCRIPTS).flatMap(([name, command]) =>
      packageJson.scripts?.[name] === command
        ? []
        : [{
          code: "missing_package_script" as const,
          path,
          message: `missing required package script: ${name}`,
        }],
    );
  } catch {
    return [{
      code: "missing_package_script",
      path,
      message: "package.json is missing or invalid",
    }];
  }
}

async function listTrackedFiles(root: string): Promise<{
  files: string[];
  issue?: ContractIssue;
}> {
  try {
    const process = Bun.spawn(["git", "ls-files", "-z"], {
      cwd: root,
      stdout: "pipe",
      stderr: "ignore",
    });
    if (await process.exited !== 0) {
      return {
        files: [],
        issue: trackedFileScanIssue(),
      };
    }
    return { files: (await new Response(process.stdout).text()).split("\0").filter(Boolean) };
  } catch {
    return {
      files: [],
      issue: trackedFileScanIssue(),
    };
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function isReadableRegularFile(path: string): Promise<boolean> {
  try {
    if (!(await stat(path)).isFile()) {
      return false;
    }
    await access(path, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

function hasStaleActiveClaim(contents: string): boolean {
  return guidanceClaims(contents).some((claim) =>
    ACTIVE_CLAIM.test(claim) && !hasRetiredContext(claim)
  );
}

function hasRetiredContext(claim: string): boolean {
  if (/\b(?:do|must)\s+not\b/i.test(claim)) return true;
  if (/\bnot\s+(?:the\s+)?(?:active|current|primary)\b/i.test(claim)) return true;
  const withoutNegatedRetirement = claim.replace(
    /\bnot\s+(?:removed|legacy|historical|retired)\b/gi,
    "",
  );
  return /\b(?:removed|legacy|historical|retired)\b/i.test(withoutNegatedRetirement);
}

interface MarkdownListItem {
  indent: number;
  body: string;
  ancestors: readonly string[];
}

function guidanceClaims(contents: string): string[] {
  const claims: string[] = [];
  const listStack: MarkdownListItem[] = [];
  const prose: string[] = [];

  const appendItemClaims = (item: MarkdownListItem): void => {
    for (const claim of pathClaims(item.body)) {
      claims.push([...item.ancestors, claim].join(" "));
    }
  };
  const closeList = (minimumIndent = Number.NEGATIVE_INFINITY): void => {
    while (listStack.length > 0 && listStack.at(-1)!.indent >= minimumIndent) {
      appendItemClaims(listStack.pop()!);
    }
  };
  const flushProse = (): void => {
    if (prose.length > 0) {
      for (const paragraph of prose.splice(0).join("\n").split(/\n[ \t]*\n+/)) {
        claims.push(...pathClaims(paragraph));
      }
    }
  };

  const lines = contents.replace(/\r\n?/g, "\n").split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]!;
    const listMatch = /^([ \t]*)(?:[-+*]|\d+[.)])[ \t]+(.*)$/.exec(line);
    if (listMatch) {
      flushProse();
      const indent = markdownIndent(listMatch[1]!);
      closeList(indent);
      listStack.push({
        indent,
        body: listMatch[2]!,
        ancestors: listStack.map(({ body }) => body),
      });
      continue;
    }

    const currentItem = listStack.at(-1);
    if (
      currentItem !== undefined && line.trim().length === 0 &&
      nextListIndent(lines, index) > currentItem.indent
    ) {
      continue;
    }
    if (currentItem !== undefined && line.trim().length > 0 && leadingIndent(line) > currentItem.indent) {
      currentItem.body = `${currentItem.body}\n${line.trim()}`;
      continue;
    }
    if (currentItem !== undefined) {
      closeList();
    }
    prose.push(line);
  }

  closeList();
  flushProse();
  return claims;
}

function pathClaims(contents: string): string[] {
  const normalized = contents.replace(/\s+/g, " ").trim();
  const claims: string[] = [];
  const pathIndexes = [
    ...[...normalized.matchAll(/components\/agentlens/gi)].map((match) => match.index ?? 0),
    ...[...normalized.matchAll(/(?:^|[^\w/])AgentLens\//g)].map((match) =>
      (match.index ?? 0) + match[0].lastIndexOf("AgentLens/")
    ),
  ].sort((left, right) => left - right);
  for (const pathIndex of pathIndexes) {
    claims.push(normalized.slice(
      sentenceStart(normalized, pathIndex),
      sentenceEnd(normalized, pathIndex + "AgentLens/".length),
    ));
  }
  return claims;
}

function markdownIndent(whitespace: string): number {
  return whitespace.replace(/\t/g, "    ").length;
}

function leadingIndent(line: string): number {
  return markdownIndent(/^[ \t]*/.exec(line)?.[0] ?? "");
}

function nextListIndent(lines: readonly string[], index: number): number {
  for (let next = index + 1; next < lines.length; next += 1) {
    const line = lines[next]!;
    if (line.trim().length === 0) continue;
    const match = /^([ \t]*)(?:[-+*]|\d+[.)])[ \t]+/.exec(line);
    return match ? markdownIndent(match[1]!) : Number.NEGATIVE_INFINITY;
  }
  return Number.NEGATIVE_INFINITY;
}

function sentenceStart(contents: string, index: number): number {
  return Math.max(
    contents.lastIndexOf(".", index - 1),
    contents.lastIndexOf("!", index - 1),
    contents.lastIndexOf("?", index - 1),
  ) + 1;
}

function sentenceEnd(contents: string, index: number): number {
  const endings = [
    contents.indexOf(".", index),
    contents.indexOf("!", index),
    contents.indexOf("?", index),
  ].filter((ending) => ending !== -1);
  return endings.length === 0 ? contents.length : Math.min(...endings);
}

function trackedFileScanIssue(): ContractIssue {
  return {
    code: "tracked_file_scan_failed",
    path: "git ls-files -z",
    message: "unable to list tracked files",
  };
}

function checkVerificationMap(
  scopes: readonly VerificationScope[],
  manifestCommands: readonly CommandSpec[] = scopes.flatMap(({ commands }) => commands),
): ContractIssue[] {
  const issues: ContractIssue[] = [];
  const scopeIds = new Set<string>();
  const commands = new Map<string, string>();

  for (const scope of scopes) {
    if (scopeIds.has(scope.id)) {
      issues.push(verificationMapIssue(`verification scope ID is duplicated: ${scope.id}`));
    }
    scopeIds.add(scope.id);

    if (scope.matchers.length === 0 || scope.matchers.some((matcher) => matcher.trim().length === 0)) {
      issues.push(verificationMapIssue(`verification scope has no matchers: ${scope.id}`));
    }
    if (scope.commands.length === 0) {
      issues.push(verificationMapIssue(`verification scope has no commands: ${scope.id}`));
    }

    for (const target of scope.allowOverlapWith ?? []) {
      if (!scopes.some(({ id }) => id === target)) {
        issues.push(verificationMapIssue(
          `verification overlap allowance references a missing scope: ${scope.id} -> ${target}`,
        ));
      }
    }
  }

  for (let leftIndex = 0; leftIndex < scopes.length; leftIndex += 1) {
    const left = scopes[leftIndex]!;
    for (let rightIndex = leftIndex + 1; rightIndex < scopes.length; rightIndex += 1) {
      const right = scopes[rightIndex]!;
      for (const leftMatcher of left.matchers) {
        for (const rightMatcher of right.matchers) {
          if (
            matcherOverlap(leftMatcher, rightMatcher) &&
            !overlapAllowed(left, right)
          ) {
            issues.push(verificationMapIssue(
              `verification scope matchers overlap without an allowance: ${left.id} ${JSON.stringify(leftMatcher)} <-> ${right.id} ${JSON.stringify(rightMatcher)}`,
            ));
          }
        }
      }
    }
  }

  for (const scope of scopes) {
    if (scope.matchers.length > 0 && !scopeReachable(scope, scopes)) {
      issues.push(verificationMapIssue(`verification scope is unreachable: ${scope.id}`));
    }
  }

  for (const command of manifestCommands) {
    const previous = commands.get(command.id);
    const current = commandIdentity(command);
    if (previous !== undefined && previous !== current) {
      issues.push(verificationMapIssue(`verification command ID conflicts: ${command.id}`));
    }
    commands.set(command.id, current);
  }

  return issues;
}

function matcherOverlap(left: string, right: string): boolean {
  if (left === "*" || right === "*") return false;
  if (left === right) return true;
  return (left.endsWith("/") && right.startsWith(left)) ||
    (right.endsWith("/") && left.startsWith(right));
}

function overlapAllowed(left: VerificationScope, right: VerificationScope): boolean {
  return (left.allowOverlapWith ?? []).includes(right.id) &&
    (right.allowOverlapWith ?? []).includes(left.id);
}

function scopeReachable(scope: VerificationScope, scopes: readonly VerificationScope[]): boolean {
  return representativePathSets(scope).some((paths) =>
    selectedScopeIds(paths, scopes).includes(scope.id)
  );
}

function representativePathSets(scope: VerificationScope): string[][] {
  if (scope.id === "full-offline") return [["__agent_manifest_unknown__/probe"]];
  if (scope.id === "waygent-closure") {
    const representatives: string[][] = [];
    if (scope.matchers.includes("bun.lock")) representatives.push(["bun.lock"]);
    if (scope.matchers.some((matcher) => matcherOverlap(matcher, "packages/"))) {
      representatives.push([
        "packages/__agent_probe_a__/src.ts",
        "packages/__agent_probe_b__/src.ts",
      ]);
    }
    return representatives;
  }
  return scope.matchers.map((matcher) => [matcherRepresentative(matcher)]);
}

function matcherRepresentative(matcher: string): string {
  return matcher === "*"
    ? "__agent_manifest_unknown__/probe"
    : matcher.endsWith("/") ? `${matcher}__agent_manifest_probe__` : matcher;
}

function selectedScopeIds(paths: readonly string[], scopes: readonly VerificationScope[]): string[] {
  const known = paths.every((path) =>
    path === "bun.lock" || scopes.some((scope) =>
      scope.id !== "waygent-closure" && scope.id !== "full-offline" &&
      scope.matchers.some((matcher) => manifestMatches(matcher, path))
    )
  );
  if (!known) {
    return scopes.some(({ id }) => id === "full-offline") ? ["full-offline"] : [];
  }

  const packageRoots = new Set(paths.flatMap((path) => {
    const match = /^packages\/([^/]+)\//.exec(path);
    return match ? [match[1]!] : [];
  }));
  const hasClosure = paths.includes("bun.lock") || packageRoots.size >= 2;
  const selected: string[] = [];
  const console = scopes.find(({ id }) => id === "console");
  for (const scope of scopes) {
    if (scope.id === "full-offline" || scope.id === "package" || scope.id === "waygent-closure") continue;
    if (hasClosure && (scope.id === "console" || scope.id === "app")) continue;
    const matchingPaths = paths.filter((path) =>
      scope.matchers.some((matcher) => manifestMatches(matcher, path))
    );
    if (matchingPaths.length === 0) continue;
    if (
      scope.id === "app" && console !== undefined &&
      matchingPaths.every((path) => console.matchers.some((matcher) => manifestMatches(matcher, path)))
    ) continue;
    selected.push(scope.id);
  }
  if (hasClosure && scopes.some(({ id }) => id === "waygent-closure")) {
    selected.push("waygent-closure");
  } else {
    const packageScope = scopes.find(({ id }) => id === "package");
    if (
      packageScope !== undefined && paths.some((path) =>
        packageScope.matchers.some((matcher) => manifestMatches(matcher, path))
      )
    ) selected.push("package");
  }
  return selected;
}

function manifestMatches(matcher: string, path: string): boolean {
  return matcher.endsWith("/") ? path.startsWith(matcher) : path === matcher;
}

async function checkVerificationCommands(
  root: string,
  manifestCommands: readonly CommandSpec[],
): Promise<ContractIssue[]> {
  const issues: ContractIssue[] = [];
  const checked = new Set<string>();
  const packageScripts = new Map<string, Record<string, unknown> | undefined>();

  for (const command of manifestCommands) {
    const identity = commandIdentity(command);
    if (checked.has(identity)) continue;
    checked.add(identity);

    if (
      !Array.isArray(command.argv) || command.argv.length === 0 ||
      command.argv.some((argument) => typeof argument !== "string" || argument.length === 0)
    ) {
      issues.push(verificationMapIssue(
        `verification command argv must contain only non-empty strings: ${command.id}`,
      ));
      continue;
    }

    const cwd = command.cwd ?? ".";
    const resolvedCwd = resolve(root, cwd);
    if (!isRepositoryRelative(root, cwd, resolvedCwd) || !await isDirectory(resolvedCwd)) {
      issues.push(verificationMapIssue(
        `verification command cwd must be an existing repository directory: ${command.id} cwd=${JSON.stringify(cwd)}`,
      ));
      continue;
    }

    if (command.argv[0] === "bun" && command.argv[1] === "run" && command.argv[2] !== undefined) {
      let scripts = packageScripts.get(resolvedCwd);
      if (!packageScripts.has(resolvedCwd)) {
        scripts = await readPackageScripts(resolvedCwd);
        packageScripts.set(resolvedCwd, scripts);
      }
      if (typeof scripts?.[command.argv[2]] !== "string") {
        issues.push(verificationMapIssue(
          `verification command references a missing package script: ${command.id} script=${JSON.stringify(command.argv[2])} cwd=${JSON.stringify(cwd)}`,
        ));
      }
    }

    if (command.argv[0] === "bun" && command.argv[1] === "test" && command.argv[2] !== undefined) {
      const testTarget = resolve(resolvedCwd, command.argv[2]);
      if (!isRepositoryRelative(root, command.argv[2], testTarget) || !await exists(testTarget)) {
        issues.push(verificationMapIssue(
          `verification test target must exist: ${command.id} target=${JSON.stringify(command.argv[2])} cwd=${JSON.stringify(cwd)}`,
        ));
      }
    }

    if (command.argv[0]!.startsWith("./") || command.argv[0]!.startsWith("../")) {
      const executable = resolve(resolvedCwd, command.argv[0]);
      const path = repositoryPath(root, executable);
      try {
        if (!isRepositoryRelative(root, command.argv[0], executable) || !(await stat(executable)).isFile()) {
          throw new Error("not an executable file");
        }
        await access(executable, constants.X_OK);
      } catch {
        issues.push({
          code: "non_executable_gate",
          path,
          message: "verification executable must exist and have executable permission",
        });
      }
    }
  }
  return issues;
}

function isRepositoryRelative(root: string, input: string, resolved: string): boolean {
  const path = relative(root, resolved);
  return !isAbsolute(input) && path !== ".." && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

async function isDirectory(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isDirectory();
  } catch {
    return false;
  }
}

async function readPackageScripts(directory: string): Promise<Record<string, unknown> | undefined> {
  try {
    const packageJson = JSON.parse(await readFile(join(directory, "package.json"), "utf8")) as {
      scripts?: Record<string, unknown>;
    };
    return packageJson.scripts;
  } catch {
    return undefined;
  }
}

function repositoryPath(root: string, path: string): string {
  const repositoryRelative = relative(root, path).split(sep).join("/");
  return repositoryRelative === "" ? "." : repositoryRelative;
}

function commandIdentity(command: CommandSpec): string {
  return JSON.stringify({ argv: command.argv, cwd: command.cwd, optIn: command.optIn });
}

function verificationMapIssue(message: string): ContractIssue {
  return {
    code: "invalid_verification_map",
    path: "scripts/agent/verification-map.ts",
    message,
  };
}

if (import.meta.main) {
  const issues = await checkContract();
  if (issues.length === 0) {
    console.log("agent contract: PASS");
  } else {
    console.log(formatContractIssues(issues));
    process.exitCode = 1;
  }
}
