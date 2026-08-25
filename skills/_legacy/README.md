# Legacy skills

이 디렉터리는 카탈로그가 아닙니다. 기본 설치 대상도 아닙니다.

Frozen local execution trees live here: plan runners, plan executors,
the Claude multi-agent executor, and the former Waygent skill. Keep their
directory names. Do not treat them as general skills.

Agent rules:

- Do not load any path under `skills/_legacy/` unless the user explicitly
  names that path.
- If the user names a path, follow that tree's `SKILL.md`.
- Waygent product execution is the `waygent` CLI, not `waygent/` in this
  directory.
- Do not add new usage guides here. Historical documents stay as-is.
