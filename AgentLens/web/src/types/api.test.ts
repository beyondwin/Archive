import { describe, expect, it } from "vitest";

import fixture from "../../../tests/fixtures/format_snapshots/show.json";
import { ShowSchema } from "./api";

describe("generated ShowSchema", () => {
  it("parses the fixture", () => {
    expect(() => ShowSchema.parse(fixture)).not.toThrow();
  });
});
