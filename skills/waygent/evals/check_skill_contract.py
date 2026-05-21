from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

required_skill_phrases = [
    "Waygent",
    "waygent run --latest",
    "waygent status --last",
    "waygent events --run",
    "waygent inspect --run",
    "waygent explain --last",
    "waygent resume --last",
    "waygent apply --run",
    "must not call `skills/kws-codex-plan-executor`",
    "must not call `skills/kws-claude-multi-agent-executor`",
]

required_files = [
    "SKILL.md",
    "README.md",
    "references/commands.md",
    "references/modes.md",
]


def main() -> int:
    missing_files = [name for name in required_files if not (ROOT / name).is_file()]
    if missing_files:
        raise SystemExit(f"missing files: {', '.join(missing_files)}")

    combined = "\n".join((ROOT / name).read_text() for name in required_files)
    missing_phrases = [phrase for phrase in required_skill_phrases if phrase not in combined]
    if missing_phrases:
        raise SystemExit(f"missing contract phrases: {', '.join(missing_phrases)}")

    print("waygent skill contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
