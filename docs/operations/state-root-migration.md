# State root

Run state used to live under `$TMPDIR/waygent-runs/` (on macOS, often
`/var/folders/.../T/waygent-runs/`). That directory can disappear on reboot or
low disk.

## Defaults now

| Platform | `defaultRunRoot()` |
| --- | --- |
| macOS | `~/Library/Application Support/waygent/runs/` |
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` |
| Windows | `%LOCALAPPDATA%/waygent/runs/` |
| other | `$TMPDIR/waygent-runs/` (stderr WARN) |

The directory is created on first use. `--root <path>` is unchanged.

## Copy old runs

```bash
# macOS
mkdir -p ~/Library/Application\ Support/waygent/runs/
cp -r "$TMPDIR/waygent-runs/." ~/Library/Application\ Support/waygent/runs/
```

`waygent orphans` without `--root` scans both roots and flags
`migration_suggested: true`.

Each run is about 50 MB. Prune with `waygent orphans --delete <id> --yes`.
