#!/usr/bin/env python3
"""Scaffold byte-stability linter (v2.22 §2.B1, Task 5).

Validates the SCAFFOLD/PAYLOAD split contract that ``scripts/dispatch_via_api.py``
(``load_prompt``) relies on. A role-prompt file
(``references/<file-role>-prompt.md``) carries four HTML-comment marker lines:

    <!-- SCAFFOLD_BEGIN -->
    ... cacheable static prefix ...
    <!-- SCAFFOLD_END -->
    <!-- PAYLOAD_BEGIN -->
    ... per-dispatch dynamic content (with {placeholder} tokens) ...
    <!-- PAYLOAD_END -->

The SCAFFOLD region is sent to Anthropic as a ``cache_control: ephemeral`` system
block; its bytes MUST stay identical to the checked-in sibling scaffold file
(``references/_scaffolds/<role>-scaffold.md``, role underscored) or the cache
prefix silently misses on every dispatch. This linter guards that invariant.

Invariants enforced (each violation -> a clear error string; CLI exits non-zero):
  1. All four markers present, exactly once each, ordered
     SCAFFOLD_BEGIN < SCAFFOLD_END < PAYLOAD_BEGIN < PAYLOAD_END.
  2. The sibling scaffold file exists and its bytes equal the SCAFFOLD region
     exactly (same ``"\\n".join(lines[sb+1:se])`` extraction dispatch uses).
  3. The SCAFFOLD region contains no ``{`` character (cache prefix must be
     placeholder-free; literal-brace / JSON sections all live in PAYLOAD).
  4. Reassembly is byte-identical: stripping ONLY the four marker lines from the
     original file equals (preamble + SCAFFOLD + between + PAYLOAD + tail).

Pure stdlib. Importable (``validate_file``, ``scaffold_path_for``,
``reassemble_without_markers``) so tests need no subprocess.

CLI:
    python3 scripts/validate_scaffold_split.py <path-to-role-prompt.md>
Exit 0 if all invariants hold; exit 1 with per-invariant messages otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCAFFOLD_BEGIN = "<!-- SCAFFOLD_BEGIN -->"
SCAFFOLD_END = "<!-- SCAFFOLD_END -->"
PAYLOAD_BEGIN = "<!-- PAYLOAD_BEGIN -->"
PAYLOAD_END = "<!-- PAYLOAD_END -->"

MARKERS = (SCAFFOLD_BEGIN, SCAFFOLD_END, PAYLOAD_BEGIN, PAYLOAD_END)


def scaffold_path_for(prompt_path: str) -> str:
    """Derive the sibling scaffold path from a role-prompt path.

    ``references/plan-reviewer-prompt.md`` ->
    ``references/_scaffolds/plan_reviewer-scaffold.md``.

    The prompt filename uses hyphens for the role token; the scaffold filename
    underscores it (matches ``dispatch_via_api.load_prompt``'s role<->filename
    convention, ``role.replace("_", "-")`` for the prompt, inverse here).
    """
    p = Path(prompt_path)
    name = p.name
    suffix = "-prompt.md"
    if not name.endswith(suffix):
        # Best-effort: still produce a path so the caller reports a clear error.
        file_role = p.stem
    else:
        file_role = name[: -len(suffix)]
    role_underscored = file_role.replace("-", "_")
    return str(p.parent / "_scaffolds" / f"{role_underscored}-scaffold.md")


def _marker_line_indices(lines: list[str]) -> dict[str, list[int]]:
    """Map each marker to the list of line indices where it appears (exact match)."""
    found: dict[str, list[int]] = {m: [] for m in MARKERS}
    for i, line in enumerate(lines):
        if line in found:
            found[line].append(i)
    return found


def reassemble_without_markers(text: str) -> str:
    """Return the file text with ONLY the four marker lines removed (joined by \\n).

    Used by invariant 4: the extracted SCAFFOLD/PAYLOAD regions stitched back
    with the surrounding (preamble/between/tail) lines must reproduce exactly
    this string.
    """
    lines = text.splitlines()
    drop = set()
    for m in MARKERS:
        for i, line in enumerate(lines):
            if line == m:
                drop.add(i)
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)


def validate_file(prompt_path: str) -> list[str]:
    """Validate one role-prompt file. Return a list of error strings (empty == OK)."""
    errors: list[str] = []
    path = Path(prompt_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{prompt_path}: cannot read prompt file: {exc}"]

    lines = text.splitlines()
    found = _marker_line_indices(lines)

    # --- Invariant 1: presence, uniqueness, ordering ----------------------- #
    presence_ok = True
    for m in MARKERS:
        n = len(found[m])
        if n == 0:
            errors.append(f"{prompt_path}: missing marker {m!r} (expected exactly once).")
            presence_ok = False
        elif n > 1:
            errors.append(
                f"{prompt_path}: marker {m!r} appears {n} times "
                f"(expected exactly once).")
            presence_ok = False

    if not presence_ok:
        # Without all four unique markers, region extraction is undefined; the
        # remaining invariants cannot be checked meaningfully.
        return errors

    sb = found[SCAFFOLD_BEGIN][0]
    se = found[SCAFFOLD_END][0]
    pb = found[PAYLOAD_BEGIN][0]
    pe = found[PAYLOAD_END][0]

    if not (sb < se < pb < pe):
        errors.append(
            f"{prompt_path}: markers out of order "
            f"(SCAFFOLD_BEGIN={sb}, SCAFFOLD_END={se}, "
            f"PAYLOAD_BEGIN={pb}, PAYLOAD_END={pe}); required "
            f"SCAFFOLD_BEGIN < SCAFFOLD_END < PAYLOAD_BEGIN < PAYLOAD_END.")
        # Ordering broken -> region slices are meaningless; stop here.
        return errors

    scaffold_region = "\n".join(lines[sb + 1:se])
    payload_region = "\n".join(lines[pb + 1:pe])

    # --- Invariant 2: sibling scaffold file matches byte-for-byte ---------- #
    scaffold_file = Path(scaffold_path_for(prompt_path))
    if not scaffold_file.is_file():
        errors.append(
            f"{prompt_path}: sibling scaffold file does not exist at "
            f"{scaffold_file} (expected for byte-stability check).")
    else:
        on_disk = scaffold_file.read_text(encoding="utf-8")
        if on_disk != scaffold_region:
            errors.append(
                f"{prompt_path}: SCAFFOLD region does not match sibling "
                f"scaffold file {scaffold_file} byte-for-byte "
                f"(prompt={len(scaffold_region)} bytes, "
                f"file={len(on_disk)} bytes) — cache prefix would drift.")

    # --- Invariant 3: no '{' in SCAFFOLD region ---------------------------- #
    if "{" in scaffold_region:
        offending = [
            (sb + 1 + j) for j, ln in enumerate(lines[sb + 1:se]) if "{" in ln]
        errors.append(
            f"{prompt_path}: SCAFFOLD region contains '{{' "
            f"(brace) at line(s) {offending} — the cacheable prefix MUST be "
            f"placeholder-free; move literal-brace/JSON content into PAYLOAD.")

    # --- Invariant 4: reassembly byte-identical ---------------------------- #
    # Stitch the surrounding lines back around the extracted regions and confirm
    # it equals the original with ONLY the four marker lines removed.
    expected = reassemble_without_markers(text)
    stitched = "\n".join(
        lines[:sb]                  # preamble
        + lines[sb + 1:se]          # SCAFFOLD region
        + lines[se + 1:pb]          # between SCAFFOLD_END and PAYLOAD_BEGIN
        + lines[pb + 1:pe]          # PAYLOAD region
        + lines[pe + 1:]            # tail
    )
    if stitched != expected:
        errors.append(
            f"{prompt_path}: reassembly mismatch — stripping the four marker "
            f"lines does not reproduce (preamble + SCAFFOLD + PAYLOAD).")

    # ``payload_region`` is extracted for completeness / future PAYLOAD checks.
    _ = payload_region

    return errors


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print(
            "usage: validate_scaffold_split.py <path-to-role-prompt.md>",
            file=sys.stderr)
        return 2
    errors = validate_file(args[0])
    if errors:
        for e in errors:
            print(f"SCAFFOLD_LINT_FAIL: {e}", file=sys.stderr)
        print(
            f"FAIL: {len(errors)} scaffold-split invariant violation(s) in "
            f"{args[0]}.", file=sys.stderr)
        return 1
    print(f"OK: scaffold-split invariants hold for {args[0]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
