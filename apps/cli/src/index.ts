import {
  defaultRunRoot,
  explainRun,
  intentToCommand,
  parseNaturalLanguageIntent,
  resumeRun,
  runWaygent,
  runWaygentDemo,
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

export async function runCli(argv = process.argv.slice(2)): Promise<unknown> {
  const parsed = parseCli(argv);
  if (parsed.command === "intent") {
    return { command: intentToCommand(parseNaturalLanguageIntent(String(parsed.flags.text ?? ""))) };
  }
  if (parsed.command === "run" || parsed.command === "demo") {
    const options: Parameters<typeof runWaygentDemo>[0] = {
      root: String(parsed.flags.root ?? defaultRunRoot()),
      profile: {
        provider: parsed.flags.provider === "claude" ? "claude" : parsed.flags.provider === "codex" ? "codex" : "fake",
        execution_mode: parsed.flags["execution-mode"] === "single-agent" ? "single-agent" : "multi-agent"
      }
    };
    if (typeof parsed.flags.run === "string") options.run_id = parsed.flags.run;
    if (typeof parsed.flags.plan === "string") options.plan = parsed.flags.plan;
    if (typeof parsed.flags.spec === "string") options.spec = parsed.flags.spec;
    if (parsed.command === "run") {
      return runWaygent(options);
    }
    return runWaygentDemo(options);
  }
  if (parsed.command === "status" || parsed.command === "inspect") {
    return statusRun(runCommandOptions(parsed));
  }
  if (parsed.command === "explain") {
    return explainRun(runCommandOptions(parsed));
  }
  if (parsed.command === "resume") {
    return resumeRun({ ...runCommandOptions(parsed), dry_run: true });
  }
  if (parsed.command === "apply") {
    return {
      command: "apply",
      status: "requires_clean_source_checkout"
    };
  }
  if (parsed.command === "events") {
    return {
      command: "events",
      run: parsed.flags.run ?? (parsed.flags.last ? "last" : "latest"),
      status: "not_started"
    };
  }
  return { usage: "waygent run|status|events|inspect|explain|resume|apply" };
}

function runCommandOptions(parsed: ParsedCli): RunCommandOptions {
  const options: RunCommandOptions = {
    root: String(parsed.flags.root ?? defaultRunRoot()),
    last: Boolean(parsed.flags.last)
  };
  if (typeof parsed.flags.run === "string") options.run = parsed.flags.run;
  return options;
}

if (import.meta.main) {
  const output = await runCli();
  console.log(JSON.stringify(output, null, 2));
}
