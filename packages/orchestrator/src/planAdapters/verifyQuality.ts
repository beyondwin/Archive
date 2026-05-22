export const TRIVIAL_TOKENS: ReadonlySet<string> = new Set([
  "printf",
  "true",
  ":",
  "echo",
  "/usr/bin/true",
  "/bin/true"
]);

export function isTrivialVerifyCommand(cmd: string): boolean {
  const trimmed = cmd.trim();
  if (!trimmed) return true;
  const token = trimmed.split(/\s+/)[0] ?? "";
  return TRIVIAL_TOKENS.has(token);
}

export interface VerifyTheaterResult {
  is_theater: boolean;
  reasons: string[];
}

export interface DetectVerifyTheaterInput {
  verify: ReadonlyArray<string>;
  file_claims: ReadonlyArray<{ path: string }>;
}

export function detectVerifyTheater(input: DetectVerifyTheaterInput): VerifyTheaterResult {
  const reasons: string[] = [];
  if (input.verify.length === 0) {
    reasons.push("no verify commands");
  } else if (input.verify.every(isTrivialVerifyCommand)) {
    reasons.push("all verify commands are trivial");
  }
  if (input.file_claims.length > 0) {
    const claimPatterns = input.file_claims.map((claim) => globToRegex(claim.path));
    const verifyTokens = input.verify.flatMap((cmd) => extractPathTokens(cmd));
    const hasMatch = verifyTokens.some((token) =>
      claimPatterns.some((pattern) => pattern.test(token))
    );
    if (!hasMatch) {
      reasons.push("verify does not reference any claimed file");
    }
  }
  return { is_theater: reasons.length > 0, reasons };
}

function extractPathTokens(command: string): string[] {
  return command
    .split(/\s+/)
    .map((token) => token.replace(/^['"]|['"]$/g, ""))
    .filter((token) => token.length > 0 && !token.startsWith("-"));
}

function globToRegex(pattern: string): RegExp {
  let result = "";
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern[i] ?? "";
    if (ch === "*") {
      if (pattern[i + 1] === "*") {
        result += ".*";
        i += 2;
        continue;
      }
      result += "[^/]*";
      i += 1;
      continue;
    }
    if (/[.+^${}()|[\]\\]/.test(ch)) {
      result += `\\${ch}`;
    } else {
      result += ch;
    }
    i += 1;
  }
  return new RegExp(`^${result}$`);
}
