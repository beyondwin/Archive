import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import type { ArtifactReference } from "@waygent/contracts";

export function sha256(data: string | Uint8Array): string {
  return createHash("sha256").update(data).digest("hex");
}

export function writeArtifact(
  runRoot: string,
  relativePath: string,
  data: string | Uint8Array,
  mediaType = "application/json"
): ArtifactReference {
  const absolute = join(runRoot, "artifacts", relativePath);
  mkdirSync(dirname(absolute), { recursive: true });
  writeFileSync(absolute, data);
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  return {
    path: relative(runRoot, absolute),
    sha256: sha256(bytes),
    byte_length: bytes.byteLength,
    media_type: mediaType
  };
}
