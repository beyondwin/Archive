# Waygent state-root migration (2026-05-22)

## Why

Waygent run state was previously written under
`$TMPDIR/waygent-runs/` (typically `/var/folders/.../T/waygent-runs/`
on macOS). macOS periodically reaps `/var/folders/.../T/`, which means
in-flight runs can be cleared during reboots, low-disk events, or
extended idle periods. Forensic analysis of failed runs (D-09–style
debugging) is impossible once the directory has been reaped.

## New defaults

| Platform | Default `defaultRunRoot()` |
|----------|----------------------------|
| darwin   | `~/Library/Application Support/waygent/runs/` |
| linux    | `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` |
| win32    | `%LOCALAPPDATA%/waygent/runs/` |
| other    | `$TMPDIR/waygent-runs/` (with stderr WARN) |

The directory is auto-created on first use.

## Migration of existing runs

To preserve existing runs, copy them once:

```bash
# macOS example
mkdir -p ~/Library/Application\ Support/waygent/runs/
cp -r "$TMPDIR/waygent-runs/." ~/Library/Application\ Support/waygent/runs/
```

`waygent orphans` (without `--root`) automatically scans BOTH roots
during a transition period and flags legacy-root entries with
`migration_suggested: true`.

## CI compatibility

The `--root <path>` flag is unchanged. CI users pinning a custom root
remain unaffected. The new defaults apply only when `--root` is
omitted.

## Disk usage

Each run averages ~50 MB. Runs accumulate unless pruned via
`waygent orphans --delete <id> --yes`.
