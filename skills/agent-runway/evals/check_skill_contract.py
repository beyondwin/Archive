from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required = [
        ROOT / "SKILL.md",
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "scripts" / "agentrunway.py",
        ROOT / "scripts" / "agentrunway" / "runner.py",
        ROOT / "references" / "protocol.md",
        ROOT / "references" / "schemas" / "task_packet.v1.json",
        ROOT / "references" / "schemas" / "worker_result.v1.json",
        ROOT / "references" / "schemas" / "event.v1.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        print("missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if "do not orchestrate workers from conversation context" not in skill:
        print("skill must keep host thin", file=sys.stderr)
        return 1
    docs_text = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "references" / "agentlens-events.md").read_text(encoding="utf-8"),
        ]
    )
    required_terms = {
        "agentrunway.*",
        "agentrunway.event.v1",
        "AgentRunway is the only supported AgentLens executor integration",
    }
    missing_terms = sorted(term for term in required_terms if term not in docs_text)
    if missing_terms:
        print("missing AgentLens contract terms: " + ", ".join(missing_terms), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
