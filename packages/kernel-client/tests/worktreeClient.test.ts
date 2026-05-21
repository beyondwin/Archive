import { describe, expect, test } from "bun:test";
import { validateExplicitApply } from "../src";

describe("worktree client", () => {
  test("refuses dirty source apply", () => {
    expect(validateExplicitApply({ run_id: "run_demo", source_dirty: true, checkpoint_ref: "checkpoint_demo" }).allowed).toBe(false);
  });
});
