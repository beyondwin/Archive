import {
  defaultRunRoot,
  eventsRun,
  explainRun,
  applyRun,
  costRun,
  decisionsRun,
  inspectRun,
  intentToCommand,
  orphansRun,
  parseClaimFlag,
  parseNaturalLanguageIntent,
  resumeRun,
  runPlanChain,
  runWaygent,
  runWaygentDemo,
  scaffoldWaygentTask,
  statusRun,
  verifyRun,
  watchRunCommand
} from "@waygent/orchestrator";
import type { RunCommandOptions, WatchRunOptions } from "@waygent/orchestrator";
import { FakeExtractorProvider, lintDesign, lintPlan } from "@waygent/design-contract";
import { readFileSync } from "node:fs";
import { join as joinPath } from "node:path";

type FlagValue = string | boolean | string[];

export interface ParsedCli {
  command: string;
  flags: Record<string, FlagValue>;
}

export function parseCli(argv: string[]): ParsedCli {
  const [command = "help", ...rest] = argv;
  const flags: ParsedCli["flags"] = {};
  for (let index = 0; index < rest.length; index += 1) {
    const item = rest[index];
    if (item === "-h") {
      flags.help = true;
      continue;
    }
    if (!item?.startsWith("--")) continue;
    const key = item.slice(2);
    const next = rest[index + 1];
    if (next && !next.startsWith("--")) {
      flags[key] = appendFlagValue(flags[key], next);
      index += 1;
    } else {
      flags[key] = appendFlagValue(flags[key], true);
    }
  }
  return { command, flags };
}

const usage = "waygent run|run-chain|status|events|inspect|explain|resume|verify|apply|decisions|cost|watch|orphans|scaffold-plan|lint-design|lint-plan";
const commandUsage: Record<string, string> = {
  run: "waygent run --plan <waygent-task.md> [--spec <design.md>] [--run <id>] [--provider codex|claude|fake] [--execution-mode multi-agent|single-agent] [--profile max-quality|balanced|cost-saver] [--main-model <name>] [--main-reasoning medium|high|xhigh] [--subagent-model <name>] [--subagent-reasoning medium|high|xhigh] [--role-model implement=<name>,review=<name>,verify_assist=<name>] [--role-reasoning implement=medium|high|xhigh,...] [--plan-preflight off|deterministic|full]",
  "run-chain": "waygent run-chain --plan <p1> [--spec <s1>] --plan <p2> [--spec <s2>]",
  demo: "waygent demo [--provider fake]",
  status: "waygent status --run <run_id>|--last",
  events: "waygent events --run <run_id>|--last",
  inspect: "waygent inspect --run <run_id>|--last",
  explain: "waygent explain --run <run_id>|--last",
  resume: "waygent resume --run <run_id>|--last",
  verify: "waygent verify --run <run_id>|--last [--task <task_id>]",
  apply: "waygent apply --run <run_id>",
  decisions: "waygent decisions --run <run_id>|--last",
  cost: "waygent cost --run <run_id>|--last",
  watch: "waygent watch --run <run_id>|--last [--json] [--filter all|task_transition|failure|cost]",
  orphans: "waygent orphans [--root <run_root>] [--delete <id> --yes]",
  "scaffold-plan": "waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>"
};

export type ProfilePreset = "max-quality" | "balanced" | "cost-saver";

export type WorkerRoleSlot = "implement" | "review" | "verify_assist";
const WORKER_ROLE_SLOTS: readonly WorkerRoleSlot[] = ["implement", "review", "verify_assist"];

interface ProfilePresetSpec {
  main_model: string;
  main_reasoning: "medium" | "high" | "xhigh";
  subagent_model: string;
  subagent_reasoning: "medium" | "high" | "xhigh";
  role_models?: Partial<Record<WorkerRoleSlot, string>>;
  role_reasoning?: Partial<Record<WorkerRoleSlot, "medium" | "high" | "xhigh">>;
}

export const PROFILE_PRESETS: Record<ProfilePreset, ProfilePresetSpec> = {
  "max-quality": { main_model: "opus", main_reasoning: "high", subagent_model: "opus", subagent_reasoning: "high" },
  "balanced": {
    main_model: "opus",
    main_reasoning: "high",
    subagent_model: "sonnet",
    subagent_reasoning: "medium",
    role_models: { implement: "opus" },
    role_reasoning: { implement: "high" }
  },
  "cost-saver": {
    main_model: "haiku",
    main_reasoning: "medium",
    subagent_model: "sonnet",
    subagent_reasoning: "medium",
    role_models: { review: "haiku", verify_assist: "haiku" },
    role_reasoning: { review: "medium", verify_assist: "medium" }
  }
};

function isProfilePreset(value: unknown): value is ProfilePreset {
  return value === "max-quality" || value === "balanced" || value === "cost-saver";
}

export type WaygentHost = "claude" | "codex" | "unknown";

export function detectHost(env: NodeJS.ProcessEnv = process.env): WaygentHost {
  if (env.WAYGENT_HOST === "claude" || env.WAYGENT_HOST === "codex") return env.WAYGENT_HOST;
  if (env.CLAUDECODE === "1" || typeof env.CLAUDE_CODE_ENTRYPOINT === "string") return "claude";
  if (env.CODEX_APP === "1" || env.CODEX_CLI === "1" || typeof env.CODEX_ENTRYPOINT === "string") return "codex";
  return "unknown";
}

export function resolveCliProfile(
  parsed: ParsedCli,
  env: NodeJS.ProcessEnv = process.env
): NonNullable<Parameters<typeof runWaygentDemo>[0]["profile"]> {
  const host = detectHost(env);
  const defaultProvider = parsed.command === "demo"
    ? "fake"
    : host === "claude"
      ? "claude"
      : "codex";
  if (parsed.command === "demo" && parsed.flags.provider && parsed.flags.provider !== "fake") {
    throw new Error("waygent demo only supports the offline fake provider; use waygent run for live providers");
  }
  const profile: NonNullable<Parameters<typeof runWaygentDemo>[0]["profile"]> = {
    provider: parsed.flags.provider === "claude" ? "claude" : parsed.flags.provider === "fake" ? "fake" : parsed.flags.provider === "codex" ? "codex" : defaultProvider,
    execution_mode: parsed.flags["execution-mode"] === "single-agent" ? "single-agent" : "multi-agent"
  };
  if (isProfilePreset(parsed.flags.profile)) {
    const preset = PROFILE_PRESETS[parsed.flags.profile];
    profile.main_model = preset.main_model;
    profile.main_reasoning = preset.main_reasoning;
    profile.subagent_model = preset.subagent_model;
    profile.subagent_reasoning = preset.subagent_reasoning;
    if (preset.role_models) profile.role_models = { ...preset.role_models };
    if (preset.role_reasoning) profile.role_reasoning = { ...preset.role_reasoning };
  } else if (parsed.flags.profile !== undefined) {
    throw new Error(`unknown --profile preset '${String(parsed.flags.profile)}'; expected one of: max-quality, balanced, cost-saver`);
  }
  if (typeof parsed.flags["main-model"] === "string") profile.main_model = parsed.flags["main-model"];
  if (isReasoning(parsed.flags["main-reasoning"])) profile.main_reasoning = parsed.flags["main-reasoning"];
  if (typeof parsed.flags["subagent-model"] === "string") profile.subagent_model = parsed.flags["subagent-model"];
  if (isReasoning(parsed.flags["subagent-reasoning"])) profile.subagent_reasoning = parsed.flags["subagent-reasoning"];
  const roleModelFlag = stringValueOf(parsed.flags["role-model"]);
  if (roleModelFlag !== null) {
    profile.role_models = { ...(profile.role_models ?? {}), ...parseRoleModelFlag(roleModelFlag) };
  }
  const roleReasoningFlag = stringValueOf(parsed.flags["role-reasoning"]);
  if (roleReasoningFlag !== null) {
    profile.role_reasoning = { ...(profile.role_reasoning ?? {}), ...parseRoleReasoningFlag(roleReasoningFlag) };
  }
  return profile;
}

function stringValueOf(value: FlagValue | undefined): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string").join(",");
  return null;
}

export function parseRoleModelFlag(raw: string): Partial<Record<WorkerRoleSlot, string>> {
  const out: Partial<Record<WorkerRoleSlot, string>> = {};
  for (const pair of raw.split(",")) {
    const trimmed = pair.trim();
    if (trimmed.length === 0) continue;
    const equals = trimmed.indexOf("=");
    if (equals < 0) throw new Error(`--role-model entry must be key=value: '${trimmed}'`);
    const key = trimmed.slice(0, equals).trim();
    const value = trimmed.slice(equals + 1).trim();
    if (!isWorkerRoleSlot(key)) {
      throw new Error(`--role-model unknown role '${key}'; expected one of: ${WORKER_ROLE_SLOTS.join(", ")}`);
    }
    if (value.length === 0) throw new Error(`--role-model entry missing value for '${key}'`);
    out[key] = value;
  }
  return out;
}

export function parseRoleReasoningFlag(raw: string): Partial<Record<WorkerRoleSlot, "medium" | "high" | "xhigh">> {
  const out: Partial<Record<WorkerRoleSlot, "medium" | "high" | "xhigh">> = {};
  for (const pair of raw.split(",")) {
    const trimmed = pair.trim();
    if (trimmed.length === 0) continue;
    const equals = trimmed.indexOf("=");
    if (equals < 0) throw new Error(`--role-reasoning entry must be key=value: '${trimmed}'`);
    const key = trimmed.slice(0, equals).trim();
    const value = trimmed.slice(equals + 1).trim();
    if (!isWorkerRoleSlot(key)) {
      throw new Error(`--role-reasoning unknown role '${key}'; expected one of: ${WORKER_ROLE_SLOTS.join(", ")}`);
    }
    if (!isReasoning(value)) {
      throw new Error(`--role-reasoning unknown level '${value}' for '${key}'; expected one of: medium, high, xhigh`);
    }
    out[key] = value;
  }
  return out;
}

function isWorkerRoleSlot(value: string): value is WorkerRoleSlot {
  return value === "implement" || value === "review" || value === "verify_assist";
}

export async function runCli(argv = process.argv.slice(2)): Promise<unknown> {
  const parsed = parseCli(argv);
  if (isHelpRequest(parsed)) {
    return { usage: commandUsage[parsed.command] ?? usage };
  }
  if (parsed.command === "intent") {
    return { command: intentToCommand(parseNaturalLanguageIntent(String(parsed.flags.text ?? ""))) };
  }
  if (parsed.command === "scaffold-plan") {
    return {
      markdown: scaffoldWaygentTask({
        id: String(parsed.flags.id ?? ""),
        title: String(parsed.flags.title ?? ""),
        dependencies: typeof parsed.flags.dependencies === "string" ? String(parsed.flags.dependencies).split(",").filter(Boolean) : [],
        file_claims: valuesForFlag(argv, "--claim").map(parseClaimFlag),
        risk: parsed.flags.risk === "medium" || parsed.flags.risk === "high" ? parsed.flags.risk : "low",
        verify: valuesForFlag(argv, "--verify")
      })
    };
  }
  if (parsed.command === "run-chain") {
    return runPlanChain({
      root: String(parsed.flags.root ?? defaultRunRoot()),
      workspace: String(parsed.flags.workspace ?? process.cwd()),
      profile: resolveCliProfile({ ...parsed, command: "run" }),
      chain_id: typeof parsed.flags.run === "string" ? parsed.flags.run : "chain_demo",
      plans: stringValues(parsed.flags.plan),
      specs: stringValues(parsed.flags.spec)
    });
  }
  if (parsed.command === "run" || parsed.command === "demo") {
    const plans = stringValues(parsed.flags.plan);
    const specs = stringValues(parsed.flags.spec);
    if (parsed.command === "run" && (plans.length > 1 || specs.length > 1)) {
      return runPlanChain({
        root: String(parsed.flags.root ?? defaultRunRoot()),
        workspace: String(parsed.flags.workspace ?? process.cwd()),
        profile: resolveCliProfile(parsed),
        chain_id: typeof parsed.flags.run === "string" ? parsed.flags.run : "chain_demo",
        plans,
        specs
      });
    }
    const options: Parameters<typeof runWaygentDemo>[0] = {
      root: String(parsed.flags.root ?? defaultRunRoot()),
      workspace: String(parsed.flags.workspace ?? process.cwd()),
      profile: resolveCliProfile(parsed)
    };
    if (typeof parsed.flags.run === "string") options.run_id = parsed.flags.run;
    if (typeof parsed.flags.plan === "string") options.plan = parsed.flags.plan;
    if (typeof parsed.flags.plan === "string") options.plan_path = parsed.flags.plan;
    if (typeof parsed.flags.spec === "string") options.spec = parsed.flags.spec;
    if (isPlanPreflight(parsed.flags["plan-preflight"])) options.plan_preflight = parsed.flags["plan-preflight"];
    if (parsed.flags["spec-slice"] === "off" || parsed.flags["spec-slice"] === "manifest") options.spec_slice = parsed.flags["spec-slice"];
    if (typeof parsed.flags["budget-cap"] === "string") options.budget_cap_usd = Number(parsed.flags["budget-cap"]);
    if (parsed.flags["budget-action"] === "warn" || parsed.flags["budget-action"] === "pause" || parsed.flags["budget-action"] === "off") options.budget_action = parsed.flags["budget-action"];
    if (typeof parsed.flags["hook-config"] === "string") options.hook_config = parsed.flags["hook-config"];
    if (parsed.flags["require-evidence"] || parsed.flags["require-method-evidence"]) options.require_method_evidence = true;
    if (parsed.flags["require-cost-data"]) (options as RunCommandOptions & { require_cost_data?: boolean }).require_cost_data = true;
    if (parsed.flags.latest) options.latest = true;
    if (typeof parsed.flags.topic === "string") options.topic = parsed.flags.topic;
    if (parsed.command === "run") {
      return runWaygent(options);
    }
    return runWaygentDemo(options);
  }
  if (parsed.command === "status") {
    return statusRun(runCommandOptions(parsed));
  }
  if (parsed.command === "inspect") {
    return inspectRun(runCommandOptions(parsed));
  }
  if (parsed.command === "explain") {
    return explainRun(runCommandOptions(parsed));
  }
  if (parsed.command === "resume") {
    return resumeRun({ ...runCommandOptions(parsed), dry_run: true });
  }
  if (parsed.command === "verify") {
    const options: Parameters<typeof verifyRun>[0] = runCommandOptions(parsed);
    if (typeof parsed.flags.task === "string") options.task = parsed.flags.task;
    return verifyRun(options);
  }
  if (parsed.command === "apply") {
    return applyRun({
      ...runCommandOptions(parsed),
      workspace: String(parsed.flags.workspace ?? process.cwd()),
      require_method_evidence: Boolean(parsed.flags["require-evidence"] || parsed.flags["require-method-evidence"])
    });
  }
  if (parsed.command === "events") {
    return eventsRun(runCommandOptions(parsed));
  }
  if (parsed.command === "decisions") {
    return decisionsRun(runCommandOptions(parsed));
  }
  if (parsed.command === "cost") {
    return costRun(runCommandOptions(parsed));
  }
  if (parsed.command === "watch") {
    const watchOptions: WatchRunOptions = {
      ...runCommandOptions(parsed),
      json: Boolean(parsed.flags.json),
      filter: parsed.flags.filter === "task_transition" || parsed.flags.filter === "failure" || parsed.flags.filter === "cost" ? parsed.flags.filter : "all"
    };
    const timeoutMs = parseDurationMs(typeof parsed.flags.timeout === "string" ? parsed.flags.timeout : undefined);
    if (timeoutMs !== undefined) watchOptions.timeout_ms = timeoutMs;
    return watchRunCommand(watchOptions);
  }
  if (parsed.command === "lint-design" || parsed.command === "lint-plan") {
    const pathFlag = parsed.flags.path;
    if (typeof pathFlag !== "string") {
      return { command: parsed.command, error: `${parsed.command} requires --path <markdown>` };
    }
    const cacheRoot = typeof parsed.flags["cache-root"] === "string"
      ? parsed.flags["cache-root"]
      : joinPath(process.cwd(), ".waygent", "design-contract-cache");
    const markdown = readFileSync(pathFlag, "utf8");
    const provider = new FakeExtractorProvider(new Map());
    const lintFn = parsed.command === "lint-design" ? lintDesign : lintPlan;
    const result = await lintFn(markdown, pathFlag, { cacheRoot, provider });
    return { command: parsed.command, parser: result.parser, report: result.report };
  }
  if (parsed.command === "orphans") {
    const orphanOptions: Parameters<typeof orphansRun>[0] = {
      root: String(parsed.flags.root ?? defaultRunRoot()),
      last: false,
      yes: Boolean(parsed.flags.yes)
    };
    if (typeof parsed.flags.delete === "string") orphanOptions.delete = parsed.flags.delete;
    return orphansRun(orphanOptions);
  }
  return { usage };
}

function appendFlagValue(existing: FlagValue | undefined, next: string | boolean): FlagValue {
  if (existing === undefined) return next;
  return [...(Array.isArray(existing) ? existing : [existing]).filter((item): item is string => typeof item === "string"), next].filter((item): item is string => typeof item === "string");
}

function stringValues(value: FlagValue | undefined): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value;
  return [];
}

function isPlanPreflight(value: unknown): value is "off" | "deterministic" | "full" {
  return value === "off" || value === "deterministic" || value === "full";
}

function isReasoning(value: unknown): value is "medium" | "high" | "xhigh" {
  return value === "medium" || value === "high" || value === "xhigh";
}

function runCommandOptions(parsed: ParsedCli): RunCommandOptions {
  const options: RunCommandOptions = {
    root: String(parsed.flags.root ?? defaultRunRoot()),
    last: Boolean(parsed.flags.last)
  };
  if (typeof parsed.flags.run === "string") options.run = parsed.flags.run;
  return options;
}

function parseDurationMs(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const match = value.match(/^(\d+)(ms|s|m)?$/);
  if (!match) return undefined;
  const amount = Number(match[1]);
  const unit = match[2] ?? "ms";
  if (unit === "m") return amount * 60_000;
  if (unit === "s") return amount * 1_000;
  return amount;
}

function valuesForFlag(argv: string[], flag: string): string[] {
  const values: string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === flag && argv[index + 1] && !argv[index + 1]!.startsWith("--")) {
      values.push(argv[index + 1]!);
    }
  }
  return values;
}

function isHelpRequest(parsed: ParsedCli): boolean {
  return parsed.command === "help" || parsed.command === "--help" || parsed.command === "-h" || parsed.flags.help === true;
}

if (import.meta.main) {
  try {
    const output = await runCli();
    console.log(JSON.stringify(output, null, 2));
  } catch (error) {
    console.error(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }, null, 2));
    process.exit(1);
  }
}
