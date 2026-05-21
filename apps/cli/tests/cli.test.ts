import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import { parseCli, runCli } from "../src/index";

describe("Waygent CLI", () => {
  test("parses run flags", () => {
    expect(parseCli(["run", "--plan", "plan.md", "--provider", "codex"]).flags.provider).toBe("codex");
  });

  test("supports stable command surface", async () => {
    expect(await runCli(["apply", "--run", "run_demo"])).toEqual({ command: "apply", status: "requires_clean_source_checkout" });
    expect((await runCli(["intent", "--text", "최근 승인된 플랜 실행해줘"])) as { command: string }).toEqual({ command: "waygent run --latest" });
  });

  test("status reads a run created by run", async () => {
    const root = mkdtempSync(join(tmpdir(), "waygent-cli-"));
    await runCli(["run", "--root", root, "--run", "run_cli"]);
    expect(await runCli(["status", "--root", root, "--last"])).toMatchObject({
      run_id: "run_cli",
      status: "completed"
    });
  });
});
