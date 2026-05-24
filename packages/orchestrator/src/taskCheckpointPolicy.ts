export function taskRequiresCheckpoint(task: { file_claims?: Array<{ mode?: string }> }): boolean {
  const claims = Array.isArray(task.file_claims) ? task.file_claims : [];
  if (claims.length === 0) return true;
  return claims.some((claim) => claim.mode !== "read_only");
}

export function taskIsReadOnlyOnly(task: { file_claims?: Array<{ mode?: string }> }): boolean {
  return !taskRequiresCheckpoint(task);
}
