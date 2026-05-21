import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { readRunStateV2, readRunStateV2Result, runStatePath, writeRunStateV2 } from "../src/runState";

describe("Waygent run state v2", () => {
  const unsupportedSchema = ["waygent.run_state", "v1"].join(".");

  test("writes and reads v2 state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
    writeRunStateV2(root, baseState(root, "run_v2"));

    expect(readRunStateV2(root, "run_v2")).toMatchObject({
      schema: "waygent.run_state.v2",
      status: "initializing"
    });
  });

  test("rejects invalid v2 state before writing", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-invalid-write-"));
    const invalid = {
      ...baseState(root, "run_invalid_write"),
      safe_waves: [{ wave_id: "wave_1", ready: [], withheld: [], unexpected: true }]
    };

    expect(() => writeRunStateV2(root, invalid as never)).toThrow();
  });

  test("rejects invalid persisted v2 state on read", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-invalid-read-"));
    const runId = "run_invalid_read";
    mkdirSync(join(root, runId), { recursive: true });
    writeFileSync(runStatePath(root, runId), `${JSON.stringify({
      ...baseState(root, runId),
      safe_waves: [{ wave_id: "wave_1", ready: [], withheld: [], unexpected: true }]
    }, null, 2)}\n`);

    expect(() => readRunStateV2(root, runId)).toThrow();
  });

  test("classifies missing v2 state without throwing", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));

    expect(readRunStateV2Result(root, "missing_run")).toEqual({
      status: "missing",
      reason: "missing_run_state_v2"
    });
  });

  test("classifies unsupported state schemas", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
    const runId = "run_unsupported_state";
    mkdirSync(join(root, runId), { recursive: true });
    writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: unsupportedSchema, run_id: runId }));

    expect(readRunStateV2Result(root, runId)).toMatchObject({
      status: "unsupported",
      reason: "unsupported_run_state",
      schema: unsupportedSchema
    });
  });

  test("classifies invalid v2 state", () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-state-v2-"));
    const runId = "run_invalid_state";
    mkdirSync(join(root, runId), { recursive: true });
    writeFileSync(join(root, runId, "state.json"), JSON.stringify({ schema: "waygent.run_state.v2", run_id: runId }));

    expect(readRunStateV2Result(root, runId)).toMatchObject({
      status: "invalid",
      reason: "invalid_run_state_v2"
    });
  });
});

function baseState(root: string, runId: string) {
  return {
    schema: "waygent.run_state.v2" as const,
    run_id: runId,
    workspace: root,
    source_branch: "main",
    worktree_root: join(root, "worktrees"),
    run_root: join(root, runId),
    artifact_root: join(root, runId, "artifacts"),
    state_path: runStatePath(root, runId),
    event_journal_path: join(root, runId, "events.jsonl"),
    plan_path: null,
    spec_path: null,
    provider_profile: { provider: "fake", execution_mode: "multi-agent" },
    status: "initializing" as const,
    lifecycle_outcome: null,
    current_phase: "preflight" as const,
    tasks: {},
    safe_waves: [],
    provider_attempts: [],
    reviews: [],
    verification: [],
    recovery: [],
    apply: { status: "not_applied" as const },
    context: { snapshot_path: null, basis_hash: null },
    drift: { last_checked_at: null, records: [], unrepaired_blockers: [] },
    completion_audit: null,
    timestamps: {
      started_at: "2026-05-21T00:00:00Z",
      updated_at: "2026-05-21T00:00:00Z",
      completed_at: null
    }
  };
}
