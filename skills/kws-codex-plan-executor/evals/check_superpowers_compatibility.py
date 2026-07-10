#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile
from pathlib import Path
import subprocess, sys

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as raw:
        skills = Path(raw) / "skills"; skills.mkdir()
        bodies = {
            "brainstorming": "---\nname: brainstorming\n---\n# Gate\n<hard-gate> approval before implementation/구현\n",
            "writing-plans": "---\nname: writing-plans\n---\n# Plan\nREQUIRED SUB-SKILL subagent-driven-development\n",
            "subagent-driven-development": "---\nname: subagent-driven-development\n---\n# Review\nfresh implementer and task reviewer; progress ledger\n",
            "verification-before-completion": "---\nname: verification-before-completion\n---\n# Verification\n```bash\npytest\n```\n",
        }
        for name, body in bodies.items():
            path = skills / name; path.mkdir(); (path / "SKILL.md").write_text(body, encoding="utf-8")
        cmd = [sys.executable, str(root / "scripts/audit_superpowers_compatibility.py"), "--superpowers-root", str(skills), "--skill-root", str(root)]
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE)
        payload = json.loads(result.stdout)
        checks = {"semantic_fixture_passes": result.returncode == 0 and payload.get("passed") is True, "thin_bridge_wins": payload.get("recommended_direction") == "thin_stateful_bridge"}
    output = {"passed": all(checks.values()), "checks": checks, "failures": [key for key, value in checks.items() if not value]}
    print(json.dumps(output, indent=2)); return 0 if output["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
