import { describe, expect, test } from "bun:test";
import { parseCli, runCli } from "../src/index";

describe("Waygent CLI", () => {
  test("parses run flags", () => {
    expect(parseCli(["run", "--plan", "plan.md", "--provider", "codex"]).flags.provider).toBe("codex");
  });

  test("supports stable command surface", async () => {
    expect(await runCli(["status", "--run", "run_demo"])).toEqual({ command: "status", run: "run_demo", status: "not_started" });
    expect((await runCli(["intent", "--text", "최근 승인된 플랜 실행해줘"])) as { command: string }).toEqual({ command: "waygent run --latest" });
  });
});
