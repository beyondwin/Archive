import {
  defaultRunRoot,
  eventsRun,
  explainRun,
  applyRun,
  inspectRun,
  intentToCommand,
  parseClaimFlag,
  parseNaturalLanguageIntent,
  resumeRun,
  runWaygent,
  runWaygentDemo,
  scaffoldWaygentTask,
  statusRun
} from "@waygent/orchestrator";
import type { RunCommandOptions } from "@waygent/orchestrator";

export interface ParsedCli {
  command: string;
  flags: Record<string, string | boolean>;
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
      flags[key] = next;
      index += 1;
    } else {
      flags[key] = true;
    }
  }
  return { command, flags };
}

const usage = "waygent run|status|events|inspect|explain|resume|apply|scaffold-plan";
const commandUsage: Record<string, string> = {
  run: "waygent run --plan <waygent-task.md> [--spec <design.md>] [--provider codex|claude|fake] [--execution-mode multi-agent|single-agent]",
  demo: "waygent demo [--provider fake]",
  status: "waygent status --run <run_id>|--last",
  events: "waygent events --run <run_id>|--last",
  inspect: "waygent inspect --run <run_id>|--last",
  explain: "waygent explain --run <run_id>|--last",
  resume: "waygent resume --run <run_id>|--last",
  apply: "waygent apply --run <run_id>",
  "scaffold-plan": "waygent scaffold-plan --id <task_id> --title <title> --claim <path:mode> --risk <low|medium|high> --verify <command>"
};

export function resolveCliProfile(parsed: ParsedCli): NonNullable<Parameters<typeof runWaygentDemo>[0]["profile"]> {
  const defaultProvider = parsed.command === "demo" ? "fake" : "codex";
  if (parsed.command === "demo" && parsed.flags.provider && parsed.flags.provider !== "fake") {
    throw new Error("waygent demo only supports the offline fake provider; use waygent run for live providers");
  }
  const profile: NonNullable<Parameters<typeof runWaygentDemo>[0]["profile"]> = {
    provider: parsed.flags.provider === "claude" ? "claude" : parsed.flags.provider === "fake" ? "fake" : parsed.flags.provider === "codex" ? "codex" : defaultProvider,
    execution_mode: parsed.flags["execution-mode"] === "single-agent" ? "single-agent" : "multi-agent"
  };
  if (typeof parsed.flags["main-model"] === "string") profile.main_model = parsed.flags["main-model"];
  if (isReasoning(parsed.flags["main-reasoning"])) profile.main_reasoning = parsed.flags["main-reasoning"];
  if (typeof parsed.flags["subagent-model"] === "string") profile.subagent_model = parsed.flags["subagent-model"];
  if (isReasoning(parsed.flags["subagent-reasoning"])) profile.subagent_reasoning = parsed.flags["subagent-reasoning"];
  return profile;
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
  if (parsed.command === "run" || parsed.command === "demo") {
    const options: Parameters<typeof runWaygentDemo>[0] = {
      root: String(parsed.flags.root ?? defaultRunRoot()),
      workspace: String(parsed.flags.workspace ?? process.cwd()),
      profile: resolveCliProfile(parsed)
    };
    if (typeof parsed.flags.run === "string") options.run_id = parsed.flags.run;
    if (typeof parsed.flags.plan === "string") options.plan = parsed.flags.plan;
    if (typeof parsed.flags.plan === "string") options.plan_path = parsed.flags.plan;
    if (typeof parsed.flags.spec === "string") options.spec = parsed.flags.spec;
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
  if (parsed.command === "apply") {
    return applyRun({ ...runCommandOptions(parsed), workspace: String(parsed.flags.workspace ?? process.cwd()) });
  }
  if (parsed.command === "events") {
    return eventsRun(runCommandOptions(parsed));
  }
  return { usage };
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
