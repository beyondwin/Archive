import { afterEach, describe, expect, it, vi } from "vitest";

import { durationOf, relativeFromNow } from "./format";

describe("format helpers", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats relative time across seconds, minutes, hours, and days", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-03T12:00:00Z"));
    expect(relativeFromNow("2026-01-03T11:59:30Z")).toBe("30s ago");
    expect(relativeFromNow("2026-01-03T11:58:30Z")).toBe("1m ago");
    expect(relativeFromNow("2026-01-03T10:00:00Z")).toBe("2h ago");
    expect(relativeFromNow("2026-01-01T12:00:00Z")).toBe("2d ago");
  });

  it("clamps same-time relative timestamps to one second", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    expect(relativeFromNow("2026-01-01T00:00:00Z")).toBe("1s ago");
  });

  it("returns a dash for missing or invalid relative timestamps", () => {
    expect(relativeFromNow(null)).toBe("-");
    expect(relativeFromNow(undefined)).toBe("-");
    expect(relativeFromNow("not-a-date")).toBe("-");
  });

  it("formats minute-and-second durations", () => {
    expect(
      durationOf("2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"),
    ).toBe("1m00s");
  });

  it("formats short, long, missing, and reversed durations", () => {
    expect(
      durationOf("2026-01-01T00:00:00Z", "2026-01-01T00:00:05Z"),
    ).toBe("5s");
    expect(
      durationOf("2026-01-01T00:00:00Z", "2026-01-01T00:01:05Z"),
    ).toBe("1m05s");
    expect(durationOf(undefined, "2026-01-01T00:01:05Z")).toBe("-");
    expect(durationOf("2026-01-01T00:00:00Z", undefined)).toBe("-");
    expect(
      durationOf("2026-01-01T00:01:05Z", "2026-01-01T00:00:00Z"),
    ).toBe("0s");
  });
});
