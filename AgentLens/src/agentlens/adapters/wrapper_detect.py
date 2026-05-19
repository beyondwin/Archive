"""Install-time wrapper-signature scanner (spec §S1.4.1 / §3.1).

Layer 1 of install safety: detect shebang scripts that, if recorded as the
``.real`` binary, would either loop, chain into a third-party launcher, or
resolve their target through PATH (and therefore through the AgentLens shim
itself).

Read the first 16 KiB of the candidate file. If the head does not start
with ``b"#!"``, accept it (Mach-O / ELF). Otherwise scan the window with
the patterns in :data:`ANTI_WRAPPER_SIGNATURES` in order — first match
wins.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, NamedTuple, Optional

WrapperCategory = Literal["agentlens_self", "cmux", "path_lookup"]

# (compiled-pattern source, category). Order matters: first match wins.
ANTI_WRAPPER_SIGNATURES: list[tuple[bytes, WrapperCategory]] = [
    # category="agentlens_self"  — self-reference; would loop.
    (rb"agentlens\s+run\s+--agent", "agentlens_self"),
    # category="cmux"  — cmux launcher signatures.
    (rb"find_real_claude", "cmux"),
    (rb"CMUX_AGENT_LAUNCH", "cmux"),
    (rb"CMUX_BUNDLED_CLI_PATH", "cmux"),
    (rb"HOOKS_JSON", "cmux"),
    # category="path_lookup"  — generic "look up binary by name through PATH".
    (rb"command -v (claude|codex)\b", "path_lookup"),
    (rb"which (claude|codex)\b", "path_lookup"),
    (rb"\bexec\b[^\n]*\$PATH[^\n]*(claude|codex)\b", "path_lookup"),
]

_READ_WINDOW = 16 * 1024  # 16 KiB

_REMEDIATIONS: dict[WrapperCategory, str] = {
    "agentlens_self": (
        "agentlens install --real <ultimate binary>: candidate is itself an "
        "AgentLens shim. Pass --real explicitly to the underlying binary."
    ),
    "cmux": (
        "agentlens install --cmux for chained mode, OR "
        "agentlens install --real <ultimate binary> to bypass the cmux "
        "launcher entirely."
    ),
    "path_lookup": (
        "agentlens install --real <ultimate binary>: candidate is a shell "
        "script that resolves the agent through PATH; baking it risks an "
        "exec loop."
    ),
}


class WrapperDetection(NamedTuple):
    """Result of scanning a candidate ``.real`` file.

    ``category`` is ``None`` when the candidate is safe to bake. When set,
    ``matched_pattern`` is the raw byte-pattern source that triggered the
    refusal and ``remediation`` is the human-readable next step.
    """

    category: Optional[WrapperCategory]
    matched_pattern: Optional[bytes]
    remediation: str


_SAFE = WrapperDetection(None, None, "")


def scan_real_candidate(path: Path) -> WrapperDetection:
    """Scan the first 16 KiB of ``path`` for wrapper signatures.

    Returns a :class:`WrapperDetection`. ``category=None`` means the file
    is safe to bake (either non-shebang, or no wrapper signature matched
    inside the 16 KiB window).
    """
    with open(path, "rb") as fh:
        head = fh.read(_READ_WINDOW)
    if not head.startswith(b"#!"):
        return _SAFE
    for pattern, category in ANTI_WRAPPER_SIGNATURES:
        if re.search(pattern, head):
            return WrapperDetection(
                category=category,
                matched_pattern=pattern,
                remediation=_REMEDIATIONS[category],
            )
    return _SAFE
