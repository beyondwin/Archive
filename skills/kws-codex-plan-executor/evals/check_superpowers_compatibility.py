#!/usr/bin/env python3
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
import subprocess, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_superpowers_compatibility import assert_superpowers_compatible
from cpe_runtime.plan_compiler import CompileBlocked


def override_is_fail_closed(plan: Path, workspace: Path, raw_root: str) -> bool:
    previous = os.environ.get("CPE_SUPERPOWERS_ROOT")
    os.environ["CPE_SUPERPOWERS_ROOT"] = raw_root
    try:
        assert_superpowers_compatible(plan, workspace)
    except CompileBlocked as exc:
        return exc.category == "superpowers_incompatible"
    finally:
        if previous is None:
            os.environ.pop("CPE_SUPERPOWERS_ROOT", None)
        else:
            os.environ["CPE_SUPERPOWERS_ROOT"] = previous
    return False

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
        plan = Path(raw) / "plan.md"
        plan.write_text("# Plan\n\n```yaml waygent-task\nname: fixture\n```\n", encoding="utf-8")
        malformed_root = Path(raw) / "malformed-superpowers-root"
        malformed_root.write_text("not a capability directory\n", encoding="utf-8")
        checks = {
            "semantic_fixture_passes": result.returncode == 0 and payload.get("passed") is True,
            "thin_bridge_wins": payload.get("recommended_direction") == "thin_stateful_bridge",
            "missing_environment_root_fails_closed": override_is_fail_closed(
                plan, Path(raw), str(Path(raw) / "missing-superpowers-root")
            ),
            "malformed_environment_root_fails_closed": override_is_fail_closed(
                plan, Path(raw), str(malformed_root)
            ),
        }
    output = {"passed": all(checks.values()), "checks": checks, "failures": [key for key, value in checks.items() if not value]}
    print(json.dumps(output, indent=2)); return 0 if output["passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
