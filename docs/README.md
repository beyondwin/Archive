# Repository guide

People start at [README.md](../README.md). AI agents start at
[AGENTS.md](../AGENTS.md). Both point here.

## File roles

| File | Purpose |
| --- | --- |
| [README.md](../README.md) | Repository purpose and starting points |
| [AGENTS.md](../AGENTS.md) | Shared rules for AI agents |
| [history.md](history.md) | Read-only access to old code, skills, and notes |
| [CLAUDE.md](../CLAUDE.md), [GEMINI.md](../GEMINI.md), [Copilot](../.github/copilot-instructions.md), [Cursor](../.cursor/rules/archive.mdc) | Tool entry points that link to the shared rules |
| [.gitignore](../.gitignore) | Excludes secrets and local tool state |
| [archive.yml](../.github/workflows/archive.yml) | Checks the archive boundary and local file links |

Keep this layout small. Historical material belongs in Git history; use
[history.md](history.md) to make it discoverable instead of restoring it here.
There are no product dependencies, build steps, or application tests.

## Archive check

GitHub Actions runs the check on every push and pull request. The workflow
contains its full implementation; no project package or separate checker is
needed.

- Only the files listed in the workflow may be tracked, and all must exist as
  regular, non-executable files. This also rejects product code, symlinks,
  submodules, and accidentally tracked local state.
- Local inline links in tracked `.md` and `.mdc` files must point to tracked
  files inside this repository. Ignored and untracked files cannot satisfy a
  link, and local tool notes are not scanned.
- Use inline links with relative file paths. External HTTP(S) URLs, email
  links, heading anchors, reference-style links, and code examples are not
  validated by this file-link check.

When adding or moving an archive file, update the workflow's allowed file
list and the relevant links in the same change. Keep shared rules in
[AGENTS.md](../AGENTS.md) and use the tool entry points only to link there.
Review `git status --short --untracked-files=all` and `git diff --check` before
committing. The GitHub check validates the committed tree, not ignored local
folders.
