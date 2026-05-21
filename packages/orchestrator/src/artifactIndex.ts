import type { ArtifactIndexEntry, ArtifactReference, ExecutionPhaseName } from "@waygent/contracts";

export type ArtifactProducerPhase = ExecutionPhaseName | "task_packet" | "combined_apply" | "decision";

export function artifactIndexEntry(input: {
  artifact: ArtifactReference;
  producer_phase: ArtifactProducerPhase;
  task_id: string | null;
  created_at?: string;
}): ArtifactIndexEntry {
  return {
    ref: input.artifact.path,
    media_type: input.artifact.media_type,
    sha256: input.artifact.sha256,
    byte_length: input.artifact.byte_length,
    producer_phase: input.producer_phase,
    task_id: input.task_id,
    created_at: input.created_at ?? new Date().toISOString()
  };
}

export function mergeArtifactIndex(
  existing: ArtifactIndexEntry[] | undefined,
  incoming: ArtifactIndexEntry[]
): ArtifactIndexEntry[] {
  const byRef = new Map<string, ArtifactIndexEntry>();
  for (const entry of existing ?? []) byRef.set(entry.ref, entry);
  for (const entry of incoming) byRef.set(entry.ref, entry);
  return [...byRef.values()].sort((a, b) => a.ref.localeCompare(b.ref));
}
