import { describe, expect, test } from "bun:test";
import type { ArtifactReference } from "@waygent/contracts";
import { artifactIndexEntry } from "../src/artifactIndex";

describe("artifact index", () => {
  test("builds deterministic index entries from artifact refs", () => {
    const artifact: ArtifactReference = {
      path: "artifacts/worker/task_a.json",
      sha256: "a".repeat(64),
      byte_length: 27,
      media_type: "application/json"
    };

    expect(artifactIndexEntry({
      artifact,
      producer_phase: "provider",
      task_id: "task_a",
      created_at: "2026-05-22T00:00:00.000Z"
    })).toEqual({
      ref: "artifacts/worker/task_a.json",
      media_type: "application/json",
      sha256: "a".repeat(64),
      byte_length: 27,
      producer_phase: "provider",
      task_id: "task_a",
      created_at: "2026-05-22T00:00:00.000Z"
    });
  });
});
