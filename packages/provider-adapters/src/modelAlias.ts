// Family-level canonicalization for provider model identifiers.
//
// Providers expose user-facing aliases ("opus", "sonnet", "haiku", "gpt-5.5")
// that the host resolves to a dated build identifier ("claude-opus-4-7",
// "claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5.5-2026-01-15"). When the
// orchestrator compares the requested model against the worker-attested
// actual model it must treat alias and resolved name as equal, otherwise
// every Anthropic-hosted run trips `lens.model_attestation_mismatch`.
//
// Rule:
//   exact string match -> match.
//   requested is a family alias ("opus"/"sonnet"/"haiku"/"gpt-5"/"gpt-5.5"),
//   actual resolves to the same family -> match.
//   otherwise -> mismatch.
//
// This preserves attestation strength when the operator pins a specific
// build ("claude-opus-4-7") but waives it when they pass the bare alias.

const familyRules: Array<{ family: string; matcher: RegExp }> = [
  { family: "opus", matcher: /(?:^|[^a-z])opus(?:$|[^a-z])|claude-opus/i },
  { family: "sonnet", matcher: /(?:^|[^a-z])sonnet(?:$|[^a-z])|claude-sonnet/i },
  { family: "haiku", matcher: /(?:^|[^a-z])haiku(?:$|[^a-z])|claude-haiku/i },
  { family: "gpt-5", matcher: /\bgpt-?5(?:\.\d+)?\b/i }
];

const familyAliasExact: RegExp[] = [
  /^opus$/i,
  /^sonnet$/i,
  /^haiku$/i,
  /^gpt-?5(?:\.\d+)?$/i
];

export function canonicalModelFamily(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (trimmed.length === 0) return null;
  for (const rule of familyRules) {
    if (rule.matcher.test(trimmed)) return rule.family;
  }
  return null;
}

export function isFamilyAlias(raw: string | null | undefined): boolean {
  if (typeof raw !== "string") return false;
  const trimmed = raw.trim();
  if (trimmed.length === 0) return false;
  return familyAliasExact.some((rx) => rx.test(trimmed));
}

export function modelsMatch(requested: string | null | undefined, actual: string | null | undefined): boolean {
  if (typeof requested !== "string" || typeof actual !== "string") return false;
  const requestedTrim = requested.trim();
  const actualTrim = actual.trim();
  if (requestedTrim.length === 0 || actualTrim.length === 0) return false;
  if (requestedTrim === actualTrim) return true;
  if (!isFamilyAlias(requestedTrim)) return false;
  const requestedFamily = canonicalModelFamily(requestedTrim);
  const actualFamily = canonicalModelFamily(actualTrim);
  if (!requestedFamily || !actualFamily) return false;
  return requestedFamily === actualFamily;
}
