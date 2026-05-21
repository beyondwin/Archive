import type { ProviderLogCategory, ProviderLogSummary } from "@waygent/contracts";

const categories: ProviderLogCategory[] = ["error", "warning", "mcp", "plugin_manifest", "skill_loader", "other"];

export function summarizeProviderStderr(stderr: string, sampleLimit = 8): ProviderLogSummary {
  const counts = Object.fromEntries(categories.map((category) => [category, 0])) as Record<ProviderLogCategory, number>;
  const samples: ProviderLogSummary["samples"] = [];
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (const line of lines) {
    const category = categorizeProviderLogLine(line);
    counts[category] += 1;
    if (samples.length < sampleLimit && !samples.some((sample) => sample.category === category && sample.line === line)) {
      samples.push({ category, line });
    }
  }
  return { total_lines: lines.length, counts, samples };
}

export function categorizeProviderLogLine(line: string): ProviderLogCategory {
  if (/ERROR/i.test(line)) return "error";
  if (/mcp|rmcp/i.test(line)) return "mcp";
  if (/manifest|defaultPrompt|plugin/i.test(line)) return "plugin_manifest";
  if (/skill|SKILL\.md|codex_core_skills/i.test(line)) return "skill_loader";
  if (/WARN|warning/i.test(line)) return "warning";
  return "other";
}
