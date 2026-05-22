const RUN_BLOCK = /^Run(?:\s+[^:]*)?:\s*\r?\n\s*```(?:bash|sh|shell)?\r?\n([\s\S]*?)\r?\n```/gim;

function logicalCommandLines(rawCommands: string): string[] {
  const commands: string[] = [];
  let current = "";
  for (const line of rawCommands.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (trimmed.endsWith("\\")) {
      current += `${trimmed.slice(0, -1).trim()} `;
      continue;
    }
    commands.push(`${current}${trimmed}`.trim());
    current = "";
  }
  if (current.trim()) commands.push(current.trim());
  return commands;
}

function isProviderInstructionCommand(command: string): boolean {
  const normalized = command.replace(/\s+/g, " ").trim();
  if (!normalized) return false;
  return !/^git\s+(add|commit|push|reset|checkout|merge|rebase|stash|clean|worktree|cherry-pick)\b/.test(normalized);
}

export function extractInstructionLines(section: string): string[] {
  const normalized = section.replace(RUN_BLOCK, (_block, rawCommands: string) => {
    const implementationCommands = logicalCommandLines(rawCommands).filter(isProviderInstructionCommand);
    if (implementationCommands.length === 0) return "";
    return ["Run:", "```bash", ...implementationCommands, "```"].join("\n");
  });
  return normalized
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
    .slice(0, 160);
}
