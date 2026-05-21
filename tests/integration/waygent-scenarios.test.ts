import { mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { describe, expect, test } from "bun:test";
import {
  loadWaygentScenario,
  runWaygentScenario,
  type NormalizedWaygentReplay,
  type WaygentScenarioExpectedReplay
} from "../../packages/testkit/src";

const scenarioDir = join(import.meta.dir, "..", "waygent-scenarios");
const scenarioFiles = readdirSync(scenarioDir)
  .filter((file) => file.endsWith(".json"))
  .sort();

describe("waygent scenario golden replays", () => {
  for (const file of scenarioFiles) {
    test(basename(file, ".json"), async () => {
      const scenario = loadWaygentScenario(join(scenarioDir, file));

      expect(["fake-success", "malformed-provider", "live-provider"]).toContain(scenario.provider_fixture);
      expect(typeof scenario.source_dirty_before_apply).toBe("boolean");
      expect(typeof scenario.force_missing_checkpoint).toBe("boolean");

      const run = await runWaygentScenario(scenario, {
        root: mkdtempSync(join(tmpdir(), `waygent-scenario-${scenario.id}-`))
      });

      expectReplay(run.normalized, scenario.expected);
    });
  }
});

function expectReplay(actual: NormalizedWaygentReplay, expected: WaygentScenarioExpectedReplay): void {
  expect(actual.run_status).toBe(expected.run_status);
  expect(actual.apply_status).toBe(expected.apply_status);
  expect(actual.event_types).toEqual(expected.event_types);
  if (expected.total_events !== undefined) expect(actual.total_events).toBe(expected.total_events);
  if (expected.safe_wave !== undefined) expect(actual.safe_wave).toEqual(expected.safe_wave);
  if (expected.checkpoints !== undefined) expect(actual.checkpoints).toEqual(expected.checkpoints);
  if (expected.blockers !== undefined) expect(actual.blockers).toEqual(expected.blockers);
  if (expected.combined_patch_ref !== undefined) expect(actual.combined_patch_ref).toBe(expected.combined_patch_ref);
  if (expected.provider_attempts !== undefined) {
    expect(actual.provider_attempts?.length).toBe(expected.provider_attempts.length);
    expected.provider_attempts.forEach((attempt, index) => {
      expect(actual.provider_attempts?.[index]).toMatchObject(attempt);
    });
  }
}
