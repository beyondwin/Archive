import { describe, expect, test } from "bun:test";
import { selectTaskContext } from "../src";

describe("task-scoped context", () => {
  test("uses file claims and failure evidence as seeds", () => {
    const packet = selectTaskContext(
      { id: "task", dependencies: [], file_claims: [{ path: "packages/contracts", mode: "owned" }], resource_locks: [], risk: "low", status: "READY" },
      [
        { path: "packages/contracts/src/index.ts", extension: ".ts", byte_size: 10, symbols: [] },
        { path: "apps/cli/src/index.ts", extension: ".ts", byte_size: 10, symbols: [] }
      ],
      20
    );
    expect(packet.included_paths).toEqual(["packages/contracts/src/index.ts"]);
  });
});
