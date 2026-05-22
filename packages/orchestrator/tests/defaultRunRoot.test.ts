import { afterEach, describe, expect, test } from "bun:test";
import { defaultRunRoot } from "../src/orchestrator";

describe("defaultRunRoot — platform paths", () => {
  const origPlatform = process.platform;
  const origXdg = process.env.XDG_DATA_HOME;
  const origLocal = process.env.LOCALAPPDATA;

  function setPlatform(p: NodeJS.Platform): void {
    Object.defineProperty(process, "platform", { value: p, writable: true, configurable: true });
  }

  afterEach(() => {
    setPlatform(origPlatform);
    if (origXdg === undefined) delete process.env.XDG_DATA_HOME;
    else process.env.XDG_DATA_HOME = origXdg;
    if (origLocal === undefined) delete process.env.LOCALAPPDATA;
    else process.env.LOCALAPPDATA = origLocal;
  });

  test("darwin → Library/Application Support", () => {
    setPlatform("darwin");
    expect(defaultRunRoot()).toContain("Library/Application Support/waygent/runs");
  });

  test("linux without XDG → ~/.local/share", () => {
    setPlatform("linux");
    delete process.env.XDG_DATA_HOME;
    expect(defaultRunRoot()).toContain(".local/share/waygent/runs");
  });

  test("linux with XDG", () => {
    setPlatform("linux");
    process.env.XDG_DATA_HOME = "/custom/data";
    expect(defaultRunRoot()).toBe("/custom/data/waygent/runs");
  });

  test("win32 → LOCALAPPDATA", () => {
    setPlatform("win32");
    process.env.LOCALAPPDATA = "C:\\Users\\u\\AppData\\Local";
    expect(defaultRunRoot()).toContain("waygent");
  });

  test("unsupported platform falls back to tmpdir with stderr warning", () => {
    setPlatform("freebsd" as NodeJS.Platform);
    const originalWrite = process.stderr.write.bind(process.stderr);
    let captured = "";
    process.stderr.write = ((chunk: string | Uint8Array) => {
      captured += typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8");
      return true;
    }) as typeof process.stderr.write;
    try {
      const root = defaultRunRoot();
      expect(root).toContain("waygent-runs");
      expect(captured).toContain("unsupported platform");
    } finally {
      process.stderr.write = originalWrite;
    }
  });
});
