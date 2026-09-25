# Where the old files went

The old product code and its design notes are not in this checkout. Git still
has them. Do not copy them back here.

| What | Where in git |
| --- | --- |
| Old product code (`apps/`, `packages/`, `native/`, old docs) | `44ec2256^` — the commit before the product was removed |
| Old design notes, plans, and incident reports | `c3dc2af7^:docs/history/` — the commit before they were removed |

```bash
git ls-tree -r --name-only 44ec2256^          # list the old product files
git show 44ec2256^:README.md                  # read one old file
git ls-tree -r --name-only c3dc2af7^ docs/history/   # list the old notes
```
