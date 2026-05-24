export function logicalCommandLines(raw: string): string[] {
  const commands: string[] = [];
  let current = "";
  for (const line of raw.split(/\r?\n/)) {
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

export function commandSegments(command: string): string[] {
  return command
    .replace(/\s+/g, " ")
    .trim()
    .split(/\s+&&\s+/)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

export function commandTokens(command: string): string[] {
  return command
    .split(/\s+/)
    .map((token) => token.replace(/^['"]|['"]$/g, ""))
    .filter(Boolean);
}
