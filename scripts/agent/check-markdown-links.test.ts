import { expect, test } from "bun:test";
import { checkMarkdownLinks } from "./check-markdown-links";

test("reports only missing local targets", async () => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () =>
      "[ok](../README.md) [bad](missing.md) [web](https://openai.com)",
    exists: async (path) => path === "/fixture/README.md",
  });
  expect(issues).toEqual([{ file: "docs/readme.md", target: "missing.md" }]);
});

test("normalizes local targets and ignores non-local links", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "[encoded](guide%20one.md?raw=1#intro)",
      "[directory](../examples/#usage)",
      "[fragment](#local)",
      "[mail](mailto:hello@example.com)",
      "[web](http://example.com)",
    ].join(" "),
    exists: async (path) => {
      checked.push(path);
      return true;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual([
    "/fixture/docs/guide one.md",
    "/fixture/examples",
  ]);
});

test("returns issues sorted by file and target", async () => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["z.md", "a.md"],
    readText: async (path) => path.endsWith("z.md")
      ? "[z](z.md) [a](a.md)"
      : "[b](b.md)",
    exists: async () => false,
  });

  expect(issues).toEqual([
    { file: "a.md", target: "b.md" },
    { file: "z.md", target: "a.md" },
    { file: "z.md", target: "z.md" },
  ]);
});
