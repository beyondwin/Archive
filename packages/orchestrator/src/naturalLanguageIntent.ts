import type { ProfileOverride } from "./executionProfile";
import { nlLexicon } from "./nlLexicon";

export interface WaygentIntent {
  command: "run" | "status" | "events" | "inspect" | "explain" | "resume" | "apply";
  latest?: boolean;
  last?: boolean;
  topic?: string;
  provider?: ProfileOverride["provider"];
  execution_mode?: ProfileOverride["execution_mode"];
  main_model?: string;
  main_reasoning?: ProfileOverride["main_reasoning"];
  subagent_model?: string;
  subagent_reasoning?: ProfileOverride["subagent_reasoning"];
}

export function parseNaturalLanguageIntent(text: string): WaygentIntent {
  const lower = text.toLowerCase();
  const provider = includesAny(lower, nlLexicon.provider.claude) ? "claude" : includesAny(lower, nlLexicon.provider.codex) ? "codex" : undefined;
  const executionMode = includesAny(lower, nlLexicon.execution_mode["single-agent"]) ? "single-agent" : includesAny(lower, nlLexicon.execution_mode["multi-agent"]) ? "multi-agent" : undefined;
  if (includesAny(lower, nlLexicon.explain)) return { command: "explain", last: true };
  if (includesAny(lower, nlLexicon.resume)) return { command: "resume", last: true };
  if (includesAny(lower, nlLexicon.apply)) return { command: "apply", last: true };
  if (includesAny(lower, nlLexicon.status)) return { command: "status", last: true };
  if (includesAny(lower, nlLexicon.events)) return { command: "events", last: true };
  const topicMatch = text.match(/topic[:=]\s*["']?([^"']+)["']?/i) ?? text.match(/"([^"]+)"/);
  const intent: WaygentIntent = {
    command: "run",
    latest: includesAny(lower, nlLexicon.latest)
  };
  if (topicMatch?.[1]) intent.topic = topicMatch[1];
  if (provider) intent.provider = provider;
  if (executionMode) intent.execution_mode = executionMode;
  applyModelKeywords(lower, intent);
  if (lower.includes("xhigh") || lower.includes("초고")) intent.main_reasoning = "xhigh";
  else if (lower.includes("high") || lower.includes("높")) intent.main_reasoning = "high";
  if (lower.includes("medium") || lower.includes("보통")) intent.subagent_reasoning = "medium";
  else if (lower.includes("high") || lower.includes("높")) intent.subagent_reasoning = "high";
  return intent;
}

function includesAny(haystack: string, needles: readonly string[]): boolean {
  return needles.some((needle) => haystack.includes(needle));
}

function applyModelKeywords(lower: string, intent: WaygentIntent): void {
  const mainMatch = lower.match(/main(?:[ _-]?(?:agent|model))?\s*(?:은|는|=|:)?\s*(opus|sonnet|haiku|claude-[a-z0-9.-]+)/);
  const subMatch = lower.match(/(?:subagent|sub[ _-]agent|sub[ _-]?model|서브(?:에이전트|모델)?)\s*(?:은|는|=|:)?\s*(opus|sonnet|haiku|claude-[a-z0-9.-]+)/);
  if (mainMatch?.[1]) intent.main_model = mainMatch[1];
  if (subMatch?.[1]) intent.subagent_model = subMatch[1];
  if (intent.main_model && intent.subagent_model) return;
  const generic = lower.match(/\b(opus|sonnet|haiku)\b/);
  if (!generic?.[1]) return;
  if (!intent.main_model) intent.main_model = generic[1];
  if (!intent.subagent_model) intent.subagent_model = generic[1];
}

export function intentToCommand(intent: WaygentIntent): string {
  const args = ["waygent", intent.command];
  if (intent.latest) args.push("--latest");
  if (intent.last) args.push("--last");
  if (intent.topic) args.push("--topic", JSON.stringify(intent.topic));
  if (intent.provider) args.push("--provider", intent.provider);
  if (intent.execution_mode) args.push("--execution-mode", intent.execution_mode);
  if (intent.main_model) args.push("--main-model", intent.main_model);
  if (intent.main_reasoning) args.push("--main-reasoning", intent.main_reasoning);
  if (intent.subagent_model) args.push("--subagent-model", intent.subagent_model);
  if (intent.subagent_reasoning) args.push("--subagent-reasoning", intent.subagent_reasoning);
  return args.join(" ");
}
