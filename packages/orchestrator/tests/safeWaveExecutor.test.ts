import { describe, expect, test } from "bun:test";
import { executeBoundedSafeWave, resolveWaveConcurrency } from "../src/safeWaveExecutor";

describe("executeBoundedSafeWave", () => {
  test("runs scheduler-approved tasks with bounded concurrency and stable result order", async () => {
    let running = 0;
    let maxRunning = 0;
    const results = await executeBoundedSafeWave({
      task_ids: ["a", "b", "c"],
      concurrency: 2,
      execute: async (taskId) => {
        running += 1;
        maxRunning = Math.max(maxRunning, running);
        await Bun.sleep(taskId === "a" ? 20 : 5);
        running -= 1;
        return taskId.toUpperCase();
      }
    });

    expect(maxRunning).toBe(2);
    expect(results).toEqual([
      { task_id: "a", status: "fulfilled", result: "A" },
      { task_id: "b", status: "fulfilled", result: "B" },
      { task_id: "c", status: "fulfilled", result: "C" }
    ]);
  });

  test("keeps successful sibling results when one task throws", async () => {
    const results = await executeBoundedSafeWave({
      task_ids: ["ok", "boom", "after"],
      concurrency: 3,
      execute: async (taskId) => {
        if (taskId === "boom") throw new Error("task exploded");
        return taskId;
      }
    });

    expect(results[0]).toEqual({ task_id: "ok", status: "fulfilled", result: "ok" });
    expect(results[1]).toMatchObject({ task_id: "boom", status: "rejected" });
    expect(results[2]).toEqual({ task_id: "after", status: "fulfilled", result: "after" });
  });

  test("uses full fake-provider wave width and clamps configured concurrency", () => {
    expect(resolveWaveConcurrency({ provider: "fake", safe_wave_size: 4, env: {} })).toBe(4);
    expect(resolveWaveConcurrency({ provider: "codex", safe_wave_size: 4, env: {} })).toBe(2);
    expect(resolveWaveConcurrency({
      provider: "codex",
      safe_wave_size: 4,
      env: { WAYGENT_WAVE_CONCURRENCY: "10" }
    })).toBe(4);
    expect(resolveWaveConcurrency({
      provider: "codex",
      safe_wave_size: 4,
      env: { WAYGENT_WAVE_CONCURRENCY: "0" }
    })).toBe(2);
  });
});
