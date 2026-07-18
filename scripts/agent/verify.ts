import { isAbsolute, relative, resolve, sep } from "node:path";
import { selectVerification, type CommandSpec } from "./verification-map";
import type { ScopeId } from "./contract";

export interface ChangedPathOptions {
  root: string;
  base?: string;
  head?: string;
  git?: (args: readonly string[]) => Promise<string>;
}

export interface NormalizedGitRange {
  base: string;
  head: string;
  diffArgs: readonly string[];
}

export interface ChangedPathsResult {
  paths: string[];
  deletedPaths: string[];
  normalizedRange?: NormalizedGitRange;
}

export interface VerificationResult {
  selectedScopes: ScopeId[];
  paths: string[];
  deletedPaths: string[];
  commandResults: Array<{ id: string; exitCode: number; skipped: boolean }>;
  unknownPaths: string[];
  exitCode: number;
}

class InvalidGitRangeError extends Error {
  readonly code = "invalid_git_range";

  constructor(
    readonly base: string,
    readonly head: string,
  ) {
    super(`invalid Git range: ${base}...${head}`);
  }
}

export async function collectChangedPaths(
  options: ChangedPathOptions,
): Promise<string[]> {
  return (await collectChangedPathsResult(options)).paths;
}

export async function collectChangedPathsResult(
  options: ChangedPathOptions,
): Promise<ChangedPathsResult> {
  if ((options.base === undefined) !== (options.head === undefined)) {
    throw new Error("base and head must be provided together");
  }

  const git = options.git ?? ((args: readonly string[]) => runGit(options.root, args));
  const normalizedRange = options.base === undefined
    ? undefined
    : await normalizeGitRange(options.base, options.head!, git);
  const outputs = options.base === undefined
    ? await Promise.all([
        git(["diff", "--name-only", "--diff-filter=ACMRD", "-z", "HEAD"]),
        git(["diff", "--name-only", "--diff-filter=D", "-z", "HEAD"]),
        git(["ls-files", "--others", "--exclude-standard", "-z"]),
      ])
    : await Promise.all([
        git([
          "diff", "--name-only", "--diff-filter=ACMRD", "-z",
          ...normalizedRange!.diffArgs,
        ]),
        git([
          "diff", "--name-only", "--diff-filter=D", "-z",
          ...normalizedRange!.diffArgs,
        ]),
      ]);

  return {
    paths: stablePaths([
      ...splitPathOutput(outputs[0] ?? ""),
      ...splitPathOutput(outputs[1] ?? ""),
      ...(options.base === undefined ? splitPathOutput(outputs[2] ?? "") : []),
    ]),
    deletedPaths: stablePaths(splitPathOutput(outputs[1] ?? "")),
    normalizedRange,
  };
}

export async function normalizeGitRange(
  base: string,
  head: string,
  git: NonNullable<ChangedPathOptions["git"]>,
): Promise<NormalizedGitRange> {
  try {
    if (/^(?:0{40}|0{64})$/.test(base)) {
      await git(["rev-parse", "--verify", head]);
      const emptyTree = (await git(["hash-object", "-t", "tree", "/dev/null"])).trim();
      if (emptyTree === "") throw new Error("empty tree hash was not returned");
      return { base, head, diffArgs: [emptyTree, head] };
    }
    await Promise.all([
      git(["rev-parse", "--verify", base]),
      git(["rev-parse", "--verify", head]),
    ]);
    return { base, head, diffArgs: [`${base}...${head}`] };
  } catch {
    throw new InvalidGitRangeError(base, head);
  }
}

export async function runVerification(options: {
  root: string;
  paths: readonly string[];
  deletedPaths?: readonly string[];
  dryRun?: boolean;
  normalizedRange?: NormalizedGitRange;
  run?: (command: CommandSpec) => Promise<number>;
}): Promise<VerificationResult> {
  const paths = stablePaths(options.paths);
  const deletedPaths = stablePaths(options.deletedPaths ?? []);
  const selection = selectVerification(paths, { deletedPaths });
  const commands = verificationCommands(
    selection.markdownFiles,
    selection.commands,
    options.normalizedRange,
  );
  const run = options.run ?? ((command: CommandSpec) => runCommand(options.root, command));
  const commandResults: VerificationResult["commandResults"] = [];
  let exitCode = 0;

  for (let index = 0; index < commands.length; index += 1) {
    const command = commands[index]!;
    if (options.dryRun || command.optIn) {
      commandResults.push({ id: command.id, exitCode: 0, skipped: true });
      continue;
    }

    const commandExitCode = await run(command);
    commandResults.push({ id: command.id, exitCode: commandExitCode, skipped: false });
    if (commandExitCode !== 0) {
      exitCode = commandExitCode;
      for (const skipped of commands.slice(index + 1)) {
        commandResults.push({ id: skipped.id, exitCode: 0, skipped: true });
      }
      break;
    }
  }

  return {
    selectedScopes: selection.scopeIds,
    paths,
    deletedPaths,
    commandResults,
    unknownPaths: selection.unknownPaths,
    exitCode,
  };
}

function verificationCommands(
  markdownFiles: readonly string[],
  selectedCommands: readonly CommandSpec[],
  normalizedRange?: NormalizedGitRange,
): CommandSpec[] {
  const markdownCommand: CommandSpec[] = markdownFiles.length === 0
    ? []
    : [{
        id: "markdown-links",
        argv: ["bun", "run", "scripts/agent/check-markdown-links.ts", ...stablePaths(markdownFiles)],
      }];
  return [
    ...markdownCommand,
    ...selectedCommands.map((command) => command.id === "diff-check" && normalizedRange !== undefined
      ? { ...command, argv: [...command.argv, ...normalizedRange.diffArgs] }
      : command),
  ];
}

async function runGit(root: string, args: readonly string[]): Promise<string> {
  const child = Bun.spawn(["git", ...args], {
    cwd: resolve(root),
    stdout: "pipe",
    stderr: "pipe",
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  if (exitCode !== 0) {
    throw new Error(stderr.trim() || `git ${args.join(" ")} exited ${exitCode}`);
  }
  return stdout;
}

async function runCommand(root: string, command: CommandSpec): Promise<number> {
  const child = Bun.spawn([...command.argv], {
    cwd: resolve(root, command.cwd ?? "."),
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
  });
  return child.exited;
}

function splitPathOutput(output: string): string[] {
  return output.split("\0").filter(Boolean);
}

function stablePaths(paths: readonly string[]): string[] {
  return [...new Set(paths.map((path) => path.replace(/^\.\//, "")).filter(Boolean))].sort(compare);
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

interface CliOptions {
  dryRun: boolean;
  paths: string[];
  base?: string;
  head?: string;
}

function parseArguments(args: readonly string[]): CliOptions {
  const options: CliOptions = { dryRun: false, paths: [] };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index]!;
    if (argument === "--") continue;
    if (argument === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (argument === "--path" || argument === "--base" || argument === "--head") {
      const value = args[index + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new Error(`${argument} requires a value`);
      }
      index += 1;
      if (argument === "--path") options.paths.push(value);
      if (argument === "--base") options.base = value;
      if (argument === "--head") options.head = value;
      continue;
    }
    throw new Error(`unknown argument: ${argument}`);
  }
  if (options.paths.length > 0 && (options.base !== undefined || options.head !== undefined)) {
    throw new Error("cannot mix --path with --base/--head");
  }
  if ((options.base === undefined) !== (options.head === undefined)) {
    throw new Error("base and head must be provided together");
  }
  return options;
}

function formatSummary(
  result: VerificationResult,
  normalizedRange?: NormalizedGitRange,
): string {
  const selection = selectVerification(result.paths, { deletedPaths: result.deletedPaths });
  const commands = verificationCommands(
    selection.markdownFiles,
    selection.commands,
    normalizedRange,
  );
  const commandsById = new Map(commands.map((command) => [command.id, command]));
  const optIn = commands.filter((command) => command.optIn);
  const lines = [
    "paths:",
    ...formatItems(result.paths),
    "scopes:",
    ...formatItems(result.selectedScopes),
    "commands:",
    ...result.commandResults.map((commandResult) => {
      const command = commandsById.get(commandResult.id);
      const status = command?.optIn && commandResult.skipped
        ? "NOT RUN (opt-in)"
        : commandResult.skipped ? "skipped" : commandResult.exitCode === 0 ? "passed" : "failed";
      return `  [${status}] ${JSON.stringify(commandResult.id)}: ${formatCommand(command)}`;
    }),
    "opt-in:",
    ...(optIn.length === 0
      ? ["  none"]
      : optIn.map((command) =>
          `  NOT RUN (opt-in) ${JSON.stringify(command.id)}: ${formatCommand(command)}`
        )),
  ];
  if (result.unknownPaths.length > 0) {
    lines.push("unknown-paths:", ...formatItems(result.unknownPaths));
  }
  lines.push(`exit-code: ${result.exitCode}`);
  return `${lines.join("\n")}\n`;
}

function formatCommand(command: CommandSpec | undefined): string {
  if (command === undefined) return "unknown";
  const cwd = command.cwd === undefined ? "" : ` cwd=${JSON.stringify(command.cwd)}`;
  return `argv=${JSON.stringify(command.argv)}${cwd}`;
}

function formatItems(items: readonly string[]): string[] {
  return items.length === 0 ? ["  none"] : items.map((item) => `  ${JSON.stringify(item)}`);
}

function normalizeExplicitPaths(root: string, paths: readonly string[]): string[] {
  return paths.map((path) => {
    const resolved = resolve(root, path);
    const relativePath = relative(root, resolved);
    if (
      isAbsolute(path) || relativePath === ".." || relativePath.startsWith(`..${sep}`) ||
      isAbsolute(relativePath)
    ) {
      throw new Error(`--path must stay within repository: ${JSON.stringify(path)}`);
    }
    return relativePath.split(sep).join("/") || ".";
  });
}

async function main(): Promise<number> {
  let options: CliOptions;
  try {
    options = parseArguments(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 2;
  }

  const root = process.cwd();
  try {
    const changed = options.paths.length > 0
      ? { paths: normalizeExplicitPaths(root, options.paths), deletedPaths: [] }
      : await collectChangedPathsResult({ root, base: options.base, head: options.head });
    const result = await runVerification({
      root,
      paths: changed.paths,
      deletedPaths: changed.deletedPaths,
      dryRun: options.dryRun,
      normalizedRange: changed.normalizedRange,
    });
    process.stdout.write(formatSummary(result, changed.normalizedRange));
    return result.exitCode;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 2;
  }
}

if (import.meta.main) {
  process.exitCode = await main();
}
