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

test("rejects relative and root-relative targets outside the repository", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture/repo",
    files: ["docs/readme.md"],
    readText: async () => [
      "[relative](../../outside.md)",
      "[root](/../../outside.md)",
      "[in-root](../README.md)",
      "[root-in](/README.md)",
    ].join(" "),
    exists: async (path) => {
      checked.push(path);
      return true;
    },
  });

  expect(issues).toEqual([
    { file: "docs/readme.md", target: "../../outside.md" },
    { file: "docs/readme.md", target: "/../../outside.md" },
  ]);
  expect(checked).toEqual([
    "/fixture/repo/README.md",
    "/fixture/repo/README.md",
  ]);
});

test("ignores links inside fenced code, inline code, and HTML comments", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "```md",
      "[fenced](fenced.md)",
      "```",
      "~~~",
      "[tilde](tilde.md)",
      "~~~",
      "`[inline](inline.md)`",
      "<!-- [comment](comment.md) -->",
      "[real](real.md)",
    ].join("\n"),
    exists: async (path) => {
      checked.push(path);
      return true;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual(["/fixture/docs/real.md"]);
});

test("supports nested labels and balanced or escaped destinations", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "[outer [inner]](dir/(balanced).md)",
      String.raw`[escaped](dir/\(escaped\).md)`,
      "[angle](<dir/space name.md> \"title\")",
    ].join(" "),
    exists: async (path) => {
      checked.push(path);
      return true;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual([
    "/fixture/docs/dir/(balanced).md",
    "/fixture/docs/dir/(escaped).md",
    "/fixture/docs/dir/space name.md",
  ]);
});

test("decodes before ignoring encoded web and mail schemes", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "[web](https%3A%2F%2Fopenai.com)",
      "[mail](mailto%3Ahello%40example.com)",
    ].join(" "),
    exists: async (path) => {
      checked.push(path);
      return false;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual([]);
});

test.each([
  ["inline code", "`<!--` [real](missing.md)"],
  ["fenced code", "```md\n<!--\n```\n[real](missing.md)"],
])("code context wins over comment markers inside $0", async (_name, contents) => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => contents,
    exists: async () => false,
  });

  expect(issues).toEqual([{ file: "docs/readme.md", target: "missing.md" }]);
});

test("masks indented code and resumes scanning prose after the block", async () => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "Before",
      "",
      "    [spaces](spaces.md)",
      "\t[tabs](tabs.md)",
      "",
      "After [real](missing.md)",
    ].join("\n"),
    exists: async () => false,
  });

  expect(issues).toEqual([{ file: "docs/readme.md", target: "missing.md" }]);
});

test("parses valid reference definitions and their titles", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "[basic]: basic.md",
      "[angle]: <dir/space name.md> \"Angle title\"",
      String.raw`[escaped]: dir/\(name\).md 'Escaped title'`,
    ].join("\n"),
    exists: async (path) => {
      checked.push(path);
      return true;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual([
    "/fixture/docs/basic.md",
    "/fixture/docs/dir/space name.md",
    "/fixture/docs/dir/(name).md",
  ]);
});

test("ignores malformed reference definitions", async () => {
  const checked: string[] = [];
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "[missing-close: target.md",
      "[no-colon] target.md",
      "[empty]:",
      "[angle]: <unterminated.md",
    ].join("\n"),
    exists: async (path) => {
      checked.push(path);
      return false;
    },
  });

  expect(issues).toEqual([]);
  expect(checked).toEqual([]);
});

test.each(["../outside.md", "/outside.md"])(
  "rejects Markdown input outside root before reading: %s",
  async (file) => {
    let read = false;
    const result = checkMarkdownLinks({
      root: "/fixture/repo",
      files: [file],
      readText: async () => {
        read = true;
        return "";
      },
    });

    expect(result).rejects.toThrow(`Markdown file must stay within repository: ${JSON.stringify(file)}`);
    expect(read).toBe(false);
  },
);
