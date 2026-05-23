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
    "waygent:scenarios",
    "WAYGENT_LIVE_PROVIDER",
    "dirty_source_checkout",
    "verified checkpoint",
    "resume --last",
    "must not call `skills/kws-codex-plan-executor`",
    "must not call `skills/kws-claude-multi-agent-executor`",
    "extra-high reasoning",
    "GPT-5.5 with high reasoning",
    "host-agent execution preference",
    "design.md plan.md 멀티에이전트로 구현해줘",
    "waygent run --plan plan.md --spec design.md --execution-mode multi-agent",
    "Do not use host `spawn_agent`",
    "The Waygent runtime owns worktree creation",
    "If no `waygent run` occurs, no Waygent worktree will be created",
    "intake_decision_required",
    "normalized plan",
    "recovery report",
]

required_files = [
    "SKILL.md",
    "README.md",
    "references/commands.md",
    "references/modes.md",
    "references/nl-lexicon.md",
]


def main() -> int:
    missing_files = [name for name in required_files if not (ROOT / name).is_file()]
    if missing_files:
        raise SystemExit(f"missing files: {', '.join(missing_files)}")

    combined = "\n".join((ROOT / name).read_text() for name in required_files)
    missing_phrases = [phrase for phrase in required_skill_phrases if phrase not in combined]
    if missing_phrases:
        raise SystemExit(f"missing contract phrases: {', '.join(missing_phrases)}")

    lexicon = (ROOT / "references/nl-lexicon.md").read_text()
    required_lexicon_phrases = [
        "waygent.nl_lexicon.v1",
        "Explicit CLI flags",
        "최근",
        "승인",
        "멀티",
        "waygent run --latest",
    ]
    missing_lexicon = [phrase for phrase in required_lexicon_phrases if phrase not in lexicon]
    if missing_lexicon:
        raise SystemExit(f"missing lexicon phrases: {', '.join(missing_lexicon)}")

    print("waygent skill contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
