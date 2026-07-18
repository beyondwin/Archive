import { afterEach, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { checkMarkdownLinks, formatMarkdownLinkIssue } from "./check-markdown-links";

const fixtureRoots: string[] = [];

afterEach(async () => {
  await Promise.all(fixtureRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

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

test("closes CRLF fenced code before scanning following prose", async () => {
  const issues = await checkMarkdownLinks({
    root: "/fixture",
    files: ["docs/readme.md"],
    readText: async () => [
      "```md",
      "[ignored](ignored.md)",
      "```",
      "[real](missing.md)",
    ].join("\r\n"),
    exists: async () => false,
  });

  expect(issues).toEqual([{ file: "docs/readme.md", target: "missing.md" }]);
});

test("rejects a Markdown document symlink that resolves outside the repository", async () => {
  const { root, outside } = await createRealFixture();
  await writeFile(join(outside, "outside.md"), "outside\n");
  await symlink(join(outside, "outside.md"), join(root, "docs/outside.md"));

  await expect(checkMarkdownLinks({ root, files: ["docs/outside.md"] }))
    .rejects.toThrow("Markdown file resolves outside repository");
});

test("reports a target symlink that resolves outside the repository", async () => {
  const { root, outside } = await createRealFixture();
  await writeFile(join(root, "docs/readme.md"), "[outside](outside.md)\n");
  await writeFile(join(outside, "outside.md"), "outside\n");
  await symlink(join(outside, "outside.md"), join(root, "docs/outside.md"));

  expect(await checkMarkdownLinks({ root, files: ["docs/readme.md"] })).toEqual([
    { file: "docs/readme.md", target: "outside.md" },
  ]);
});

test("reports a broken target symlink", async () => {
  const { root } = await createRealFixture();
  await writeFile(join(root, "docs/readme.md"), "[broken](broken.md)\n");
  await symlink("missing.md", join(root, "docs/broken.md"));

  expect(await checkMarkdownLinks({ root, files: ["docs/readme.md"] })).toEqual([
    { file: "docs/readme.md", target: "broken.md" },
  ]);
});

test("allows document and target symlinks that resolve inside the repository", async () => {
  const { root } = await createRealFixture();
  await writeFile(join(root, "docs/real.md"), "[target](target-link.md)\n");
  await writeFile(join(root, "docs/target.md"), "target\n");
  await symlink("real.md", join(root, "docs/alias.md"));
  await symlink("target.md", join(root, "docs/target-link.md"));

  expect(await checkMarkdownLinks({ root, files: ["docs/alias.md"] })).toEqual([]);
});

test("uses the real repository root when the configured root is an internal symlink", async () => {
  const { root } = await createRealFixture();
  const linkedRoot = join(dirname(root), "repo-link");
  await writeFile(join(root, "docs/readme.md"), "[target](target.md)\n");
  await writeFile(join(root, "docs/target.md"), "target\n");
  await symlink(root, linkedRoot);

  expect(await checkMarkdownLinks({ root: linkedRoot, files: ["docs/readme.md"] })).toEqual([]);
});

test("JSON-encodes untrusted Markdown file and target fields", () => {
  const output = formatMarkdownLinkIssue({
    file: "docs/line\n\u001b[31m.md",
    target: "target\n\u001b[2J.md",
  });

  expect(output).toBe(
    "[markdown-link] file=\"docs/line\\n\\u001b[31m.md\" missing-local-target=\"target\\n\\u001b[2J.md\"",
  );
  expect(output.split("\n")).toHaveLength(1);
});

test("CLI escapes a newline in an input document path", async () => {
  const { root } = await createRealFixture();
  const file = "docs/line\nforged.md";
  await writeFile(join(root, file), "[missing](missing.md)\n");
  const script = join(process.cwd(), "scripts/agent/check-markdown-links.ts");
  const child = Bun.spawn(["bun", script, file], {
    cwd: root,
    stdout: "pipe",
    stderr: "pipe",
  });

  expect(await child.exited).toBe(1);
  expect(await new Response(child.stderr).text()).toBe(
    "[markdown-link] file=\"docs/line\\nforged.md\" missing-local-target=\"missing.md\"\n",
  );
});

async function createRealFixture(): Promise<{ root: string; outside: string }> {
  const base = await mkdtemp(join(tmpdir(), "markdown-links-"));
  fixtureRoots.push(base);
  const root = join(base, "repo");
  const outside = join(base, "outside");
  await mkdir(join(root, "docs"), { recursive: true });
  await mkdir(outside, { recursive: true });
  return { root, outside };
}
