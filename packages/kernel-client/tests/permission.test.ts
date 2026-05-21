import { describe, expect, test } from "bun:test";
import { buildKernelRequest, executeInProcess } from "../src";

describe("kernel permission decisions", () => {
  test("denies disallowed command prefixes before side effects", async () => {
    const result = await executeInProcess(
      buildKernelRequest({
        request_id: "exec_demo",
        run_id: "run_demo",
        task_id: "task_demo",
        cwd: ".",
        argv: ["rm", "-rf", "x"],
        timeout_ms: 1000,
        permission_profile: {
          filesystem: { read: ["."], write: [], deny: [".git/config"] },
          network: "disabled",
          command_prefixes: ["bun"]
        }
      })
    );
    expect(result.exit_code).toBe(1);
    expect(result.permission_decision?.allowed).toBe(false);
  });
});
