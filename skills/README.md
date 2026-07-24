# skills/

이 디렉터리는 Archive 레포에서 관리되는 **개인용 runner/executor 스킬**의
단일 출처(source of truth)입니다. 순차 plan 실행은 provider별 독립 runner를
사용하고, 전문화된 multi-agent executor는 별도 계약으로 유지합니다.

## 포함된 스킬

| 스킬 | 용도 |
|------|------|
| [`kws-codex-plan-runner`](./kws-codex-plan-runner/) | 승인된 Superpowers spec과 순서가 있는 plan들을 Codex로 자율 구현하는 durable sequential runner. |
| [`kws-claude-plan-runner`](./kws-claude-plan-runner/) | 같은 공통 완료·복구 계약을 Claude Code transport로 독립 구현한 durable sequential runner. |
| [`kws-claude-multi-agent-executor`](./kws-claude-multi-agent-executor/) | Opus orchestrator와 Sonnet sub-agent 역할 분리를 사용하는 전문화된 multi-agent executor. 순차 Claude runner와 독립적으로 설치·사용합니다. |
| [`waygent`](./waygent/) | 활성 제품 런타임 스킬. 자연어 실행, 상태, 이벤트, 검사, 설명, 재개, 적용 요청을 Waygent CLI로 변환합니다. KWS executor 스킬은 별도 비제품 executor 계약으로 유지됩니다. |

각 스킬 디렉터리의 `SKILL.md`가 정식 진입점입니다. 자세한 사용법은 먼저
실제로 존재하는 `README.md`를 확인하고, 해당 스킬이 제공하는 추가 파일을
따르세요.

## 버전과 릴리스 상태

`kws-codex-plan-runner`와 `kws-claude-plan-runner`의 최초 greenfield
릴리스는 각각 `1.0.0`입니다. 발견성에 사용하는 현재 버전은 각
`SKILL.md`의 `metadata.version`, 릴리스 이력은 같은 디렉터리의
`CHANGELOG.md`가 단일 출처입니다.

사용자 홈에 심볼릭 링크를 추가하거나 문서만 정리하는 작업은 런타임 계약을
바꾸지 않으므로 버전을 올리지 않습니다. CLI, 상태, 복구, 검증, 완료 의미가
바뀌면 SemVer에 따라 `SKILL.md`, `CHANGELOG.md`, README, 계약 테스트를
같이 갱신합니다.

## Waygent Boundary

Waygent 요청은 `skills/waygent/`에서 CLI로 라우팅하고, 런타임 상태와
스케줄링은 Waygent가 소유합니다. `kws-*` 스킬은 로컬 executor 계약이며
Waygent 제품 런타임 의존성이 아닙니다.

## 공통 순차 실행 계약

두 plan runner는 provider 구현은 독립적이지만 완료 의미는 같습니다.
task의 `reported_done`은 provider 보고이며, plan의 `implemented`는 해당
plan의 Git 결과와 durable ledger가 봉인되었다는 plan-local 상태입니다.
둘 다 전체 실행 완료를 뜻하지 않습니다. 모든 plan이 구현되고 동일한
최종 candidate HEAD에서 선언된 verification set과 fresh final review가
성공해야 run-level `ready_for_integration`이 됩니다.

`--spec`과 `--plan`은 각각 반복할 수 있으며 CLI 입력 순서를 보존합니다.
모든 spec은 immutable common context이고, plan은 전달 순서대로 하나의
worktree와 branch에서 순차 구현합니다. `spec[i]`와 `plan[i]`를 위치로
짝짓지 않으며 runner가 문서를 병합하거나 재작성하지 않습니다. 각 provider
packet은 현재 plan만 작업 대상으로 표시하고 이후 plan은 노출하지 않습니다.

두 runner 모두 미리 설치된 uv-managed normal-GIL CPython
`>=3.13,<3.14`를 사용하며 active run/resume 중 Python을 다운로드하거나
system Python으로 fallback하지 않습니다. 최초 준비는 한 번 명시적으로
실행합니다.

```bash
uv python install 3.13
```

각 runner 하위 트리를 변경할 때는 그 디렉터리의 `AGENTS.md`, `SKILL.md`,
`README.md`를 먼저 읽고 `./evals/run.sh`를 실행합니다. 공통 parity와
cutover 단위 테스트는 repository verification map에서 함께 선택됩니다.

```bash
./scripts/agent/check-plan-runner-parity
./scripts/agent/plan-runner-cutover self-test
```

위 명령은 offline 검증이며 provider를 호출하거나 operator home을
감사하지 않습니다. 실제 provider 호환성 확인은 자동 offline scope에
포함하지 않고 다음 canary를 명시적으로 선택한 경우에만 실행합니다.

```bash
./scripts/agent/plan-runner-live-canary --provider codex --mode all
./scripts/agent/plan-runner-live-canary --provider claude --mode all
```

## 심볼릭 링크 셋업

아래 예제에서 `ARCHIVE_REPO`를 현재 Archive checkout의 절대 루트로
설정합니다. Provider별 순차 runner는 해당 provider 홈에만 설치합니다.
Claude multi-agent executor와 Waygent는 필요한 도구 쪽에 별도로 설치합니다.

### Claude Code (`~/.claude/skills/`)

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-runner" \
        ~/.claude/skills/kws-claude-plan-runner
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-multi-agent-executor" \
        ~/.claude/skills/kws-claude-multi-agent-executor
ln -sfn "$ARCHIVE_REPO/skills/waygent" \
        ~/.claude/skills/waygent
```

### Codex (`~/.codex/skills/`)

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-runner" \
        ~/.codex/skills/kws-codex-plan-runner
ln -sfn "$ARCHIVE_REPO/skills/waygent" \
        ~/.codex/skills/waygent
```

> `ln -sfn` 은 기존 심링크를 안전하게 갱신합니다(`-f` 강제, `-n` 디렉터리 타깃 보호). 실제 디렉터리를 덮어쓰지 않으려면 대상 경로가 심링크인지 먼저 확인하세요.

새 링크를 추가한 뒤에는 Codex를 재시작하거나 새 task를 시작해 스킬 카탈로그를
다시 로드하세요. 이미 열린 task의 시작 시점 카탈로그에는 새 스킬이 나타나지
않을 수 있습니다.

### 확인

```bash
ls -l ~/.claude/skills/ | grep -E 'kws-|waygent'
ls -l ~/.codex/skills/  | grep -E 'kws-|waygent'
```

신규 설치 대상은 Codex 홈의 Codex plan runner와 Claude 홈의 Claude plan
runner입니다. Claude multi-agent executor는 위의 독립 링크로 유지합니다.
모든 링크가 `ARCHIVE_REPO/skills/...` 아래의 정확한 source를 가리키는지
확인하세요.

레거시 executor 실행이나 재개 가능한 state가 남아 있으면 새 runner 링크와
기존 executor 링크가 일시적으로 공존할 수 있습니다. 이때 기존 링크나 source를
수동으로 제거하지 마세요. `scripts/agent/plan-runner-cutover audit`가
zero-blocker를 확인한 뒤 정식 cutover 절차로만 제거합니다.

## 수정 워크플로우

1. 이 디렉터리 안에서 직접 편집 (`skills/<skill>/SKILL.md` 등).
2. `git status` 로 Archive 레포에 변경 사항이 잡히는지 확인.
3. 해당 provider는 심볼릭 링크를 통해 즉시 새 내용을 사용합니다.
4. 의미 있는 런타임 변경이면 각 스킬의 `SKILL.md` 프론트매터 버전과
   실제로 존재하는 README, 계약 테스트, 관련 문서를 함께 갱신합니다.
   문서만 정리한 경우에는 버전 bump가 필요하지 않습니다.

## 참고

- 다른 일반 스킬(reflective-writing-coach, archive-docs-organizer 등)은 별도의 `kws-skills` 플러그인에서 관리되며 이 디렉터리에는 포함되지 않습니다.
- executor 스킬을 Archive 레포로 옮긴 배경은 커밋 `d7039d5`, `17ff639`, `da8782c` 참고.
