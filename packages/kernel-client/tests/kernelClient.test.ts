import { describe, expect, test } from "bun:test";
import { buildKernelRequest, result } from "../src";

describe("kernel client", () => {
  test("builds and validates execution result schema", () => {
    const request = buildKernelRequest({
      request_id: "exec_demo",
      run_id: "run_demo",
      task_id: "task_demo",
      cwd: ".",
      argv: ["printf", "hello"],
      timeout_ms: 1000
    });
    expect(result(request, 0, "hello", "", false).stdout_sha256).toHaveLength(64);
  });
});
