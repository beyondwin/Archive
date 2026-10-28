# Where the old files went

The old product code, skills, and design notes are not in this checkout. Git
still has them. Do not copy them back here. These references identify the
snapshots immediately before each removal; they do not imply current support.

| What | Where in git |
| --- | --- |
| Product code (`apps/`, `packages/`, `native/`) and product docs, including `docs/superpowers/` plans | `44ec2256^` |
| Historical design notes, migration records, and incident reports | `c3dc2af7^:docs/history/` |
| Former `image-workbench` and `korean-writing-editor` skills | `e319b853^:skills/` |
| Legacy executors, runners, and Waygent skill | `910811d1^:skills/_legacy/` |

From the repository root, these commands inspect history without changing
the checkout:

```bash
git ls-tree -r --name-only '44ec2256^'
git show '44ec2256^:README.md'
git ls-tree -r --name-only 'c3dc2af7^' -- docs/history/
git ls-tree -r --name-only 'e319b853^' -- skills/
git ls-tree -r --name-only '910811d1^' -- skills/_legacy/
```

If a reference is unavailable, check whether this is a shallow clone with
`git rev-parse --is-shallow-repository`. For a shallow clone, run
`git fetch --unshallow origin` to retrieve the missing history, then retry.
This downloads Git history without restoring files into the checkout.

Return to the [repository guide](README.md).
