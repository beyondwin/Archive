export interface SafeWaveExecutorInput<T> {
  task_ids: string[];
  concurrency: number;
  execute: (taskId: string) => Promise<T>;
}

export type SafeWaveTaskResult<T> =
  | { task_id: string; status: "fulfilled"; result: T }
  | { task_id: string; status: "rejected"; error: unknown };

export async function executeBoundedSafeWave<T>(
  input: SafeWaveExecutorInput<T>
): Promise<Array<SafeWaveTaskResult<T>>> {
  const concurrency = Math.max(1, Math.min(input.concurrency, input.task_ids.length || 1));
  const results: Array<SafeWaveTaskResult<T>> = [];
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (nextIndex < input.task_ids.length) {
      const index = nextIndex;
      nextIndex += 1;
      const taskId = input.task_ids[index]!;
      try {
        results[index] = { task_id: taskId, status: "fulfilled", result: await input.execute(taskId) };
      } catch (error) {
        results[index] = { task_id: taskId, status: "rejected", error };
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  return results;
}

export function resolveWaveConcurrency(input: {
  provider: string;
  safe_wave_size: number;
  env?: NodeJS.ProcessEnv;
}): number {
  const waveSize = Math.max(1, input.safe_wave_size);
  const configured = Number(input.env?.WAYGENT_WAVE_CONCURRENCY);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.max(1, Math.min(Math.floor(configured), waveSize));
  }
  if (input.provider === "fake") return waveSize;
  return Math.max(1, Math.min(2, waveSize));
}
