# korean-writing-editor

## 1분 시작

이렇게 요청하세요.

```text
이 문장을 자연스럽게 다듬어줘. 뜻과 내 말투는 유지해줘: ...
오탈자만 고쳐줘: ...
고치지 말고 어색한 부분만 알려줘: ...
```

고칠 한국어 원문을 같이 붙이면 됩니다. `correct`와 `polish`의 기본 결과는
다듬은 글만 나옵니다. `diagnose`는 글을 고치지 않고 문제만 말합니다.

## 언제 사용하나

이미 있는 한국어 글을 교정하거나 윤문할 때만 씁니다. 뜻, 사실, 말투는
유지합니다.

쓰지 마세요. 아래는 일반 도우미나 다른 작업으로 두세요.

- 일상 한국어 대화
- 번역
- 초안 작성
- 요약
- 코드·설계 리뷰
- AI 검출 회피나 “사람처럼 보이게” 만들기
- 특정 작가 흉내

암시적으로 켜지려면 한국어 교정·윤문 요청과 원문이 둘 다 있어야 합니다.
둘 중 하나라도 없으면 이 스킬은 시작하지 않습니다.

## 세 가지 모드

유효한 요청이면 기본은 보수적인 `polish`입니다.

| 모드 | 이런 요청 | 하는 일 |
| --- | --- | --- |
| `diagnose` | 고치지 말고 문제만 알려줘 | 어색한 부분과 보류만 말하고 글을 고치지 않습니다. |
| `correct` | 오탈자만 고쳐줘 | 맞춤법·띄어쓰기·분명한 문법만 고칩니다. |
| `polish` | 자연스럽게 다듬어줘 | 뜻과 말투를 유지한 채 읽기만 다듬습니다. |

동작 계약은 [SKILL.md](SKILL.md), 편집 판단은
[editorial-guide.md](references/editorial-guide.md)를 따릅니다.

## 호출 예시

명시 호출은 다음 네 가지입니다.

| 런타임 | 호출 |
| --- | --- |
| Codex | `$korean-writing-editor` |
| Claude Code | `/korean-writing-editor` |
| Cursor | `/korean-writing-editor` |
| Grok Build | `/korean-writing-editor` |

Grok은 Grok Build만 해당합니다. grok.com이나 모바일 앱이 아닙니다.

```text
$korean-writing-editor 오탈자만 고쳐줘: 이 기능은 사용할수 있지만 반드시 켤 필요는 없습니다.
```

```text
/korean-writing-editor 고치지 말고 어색한 부분만 알려줘: 지금 상태에선 배포할수 있다.
```

```text
한국어로 짧게 답해줘. 오늘 날씨가 좋네요.
```

마지막 예는 이 스킬을 쓰지 않습니다. 일상 대화는 일반 도우미에게 두세요.

## 결과 형식

`correct`와 `polish`의 기본 출력은 고친 글만입니다. `diagnose`는 고치지
않고 어색한 점과 보류만 말합니다. 점수, 변경 목록, 모델 이름은 붙지
않습니다. 앞뒤에 작업 설명을 붙이지 않습니다.

`확인 필요`는 뜻을 바꿀 수 있는 모호함이나 보류가 있을 때만 짧게 붙습니다.
그 한 줄에 이유 목록을 붙이지 않습니다. 이유를 물어보면 그때 고친 글,
달라진 점, 보류, 규범 출처를 설명합니다.

## 모델 선택

모델 이름은 고정하지 않습니다. 추가 분류 모델도 부르지 않습니다.

| 티어 | 이런 작업 |
| --- | --- |
| `fast` | 짧은 맞춤법, 띄어쓰기, 문장부호, 분명한 문법 |
| `balanced` | 메일·댓글·리뷰·산문의 평범한 윤문 |
| `frontier` | 의미 모호, 밀도 높은 기술·학술 문장, 위험한 구조 편집 |

활성 런타임이 모델 전환을 지원하지 않으면 지금 켜진 모델로 고칩니다.
전환 여부를 물으면 `routing unavailable`이라고 말합니다. 길이만으로
`frontier`를 고르지 않습니다.

## 설치

정식 원본은 Archive에 추적된
`skills/korean-writing-editor/`입니다. 설치 스크립트는 없습니다.

1. 추적된 Archive 디렉터리를 정식 원본으로 둡니다.
2. Codex, Cursor, Grok Build는 검증된 사본을
   `~/.agents/skills/korean-writing-editor`에 만듭니다.
3. Claude Code는 그 검증된 설치를
   `~/.claude/skills/korean-writing-editor`에 복사하거나 링크합니다.
4. 이미 있는 실제 디렉터리는 내용을 확인하기 전에 덮어쓰지 않습니다.
5. 설치 후 에이전트 세션을 새로 시작합니다.
6. Grok 지원은 Grok Build입니다. grok.com이나 모바일이 아닙니다.

새 경로를 만든 뒤에, 이 스킬의 이전 설치임이 확인된 `~/.agents/skills/kws-korean-writing-editor`(및 대응 Claude 경로)만 제거한다. 지원하는 호출 이름이 아니다.

작업 전용 변수만 복사·삭제 대상으로 씁니다. `$HOME`, `$CODEX_HOME`,
`~/.agents/skills` 같은 상위 경로는 복사하거나 지우지 마세요.

```bash
EDITOR_SOURCE="/absolute/path/to/Archive/skills/korean-writing-editor"
EDITOR_AGENTS_TARGET="$HOME/.agents/skills/korean-writing-editor"
EDITOR_CLAUDE_TARGET="$HOME/.claude/skills/korean-writing-editor"

ls -ld "$EDITOR_SOURCE"
ls -ld "$EDITOR_AGENTS_TARGET" "$EDITOR_CLAUDE_TARGET"
```

두 대상이 없을 때만 아래를 진행합니다. 실제 디렉터리가 있으면 중단하세요.

```bash
EDITOR_SOURCE="/absolute/path/to/Archive/skills/korean-writing-editor"
EDITOR_AGENTS_TARGET="$HOME/.agents/skills/korean-writing-editor"
EDITOR_CLAUDE_TARGET="$HOME/.claude/skills/korean-writing-editor"

mkdir -p "$(dirname "$EDITOR_AGENTS_TARGET")" \
         "$(dirname "$EDITOR_CLAUDE_TARGET")"
cp -R "$EDITOR_SOURCE" "$EDITOR_AGENTS_TARGET"
ln -s "$EDITOR_AGENTS_TARGET" "$EDITOR_CLAUDE_TARGET"
```

Claude 대상이 이미 실제 디렉터리이면 링크를 강제하지 말고 내용을 확인하세요.

## 업데이트와 제거

같은 변수로 대상만 다룹니다. 상위 홈이나 스킬 부모 디렉터리는 지우지 않습니다.

```bash
EDITOR_SOURCE="/absolute/path/to/Archive/skills/korean-writing-editor"
EDITOR_AGENTS_TARGET="$HOME/.agents/skills/korean-writing-editor"
EDITOR_CLAUDE_TARGET="$HOME/.claude/skills/korean-writing-editor"

ls -ld "$EDITOR_AGENTS_TARGET" "$EDITOR_CLAUDE_TARGET"
```

이 스킬의 사본임이 확인된 뒤에만 갱신합니다.

```bash
EDITOR_SOURCE="/absolute/path/to/Archive/skills/korean-writing-editor"
EDITOR_AGENTS_TARGET="$HOME/.agents/skills/korean-writing-editor"

rm -rf "$EDITOR_AGENTS_TARGET"
cp -R "$EDITOR_SOURCE" "$EDITOR_AGENTS_TARGET"
```

Claude 대상이 위 사본을 가리키는 심볼릭 링크이면 그대로 두고, 없으면 다시
링크합니다. 실제 디렉터리이면 덮어쓰지 마세요.

제거할 때도 대상을 확인한 뒤 정확한 경로만 지웁니다.

```bash
EDITOR_AGENTS_TARGET="$HOME/.agents/skills/korean-writing-editor"
EDITOR_CLAUDE_TARGET="$HOME/.claude/skills/korean-writing-editor"

rm -rf "$EDITOR_AGENTS_TARGET"
rm -- "$EDITOR_CLAUDE_TARGET"
```

갱신·제거 뒤에도 에이전트 세션을 새로 시작하세요.

## 개인정보와 한계

사용자 글을 픽스처, 로그, 말투 프로필로 저장하지 않습니다. 비공식 맞춤법
웹 서비스로 보내거나, 요청 없이 사실을 찾아오지 않습니다.

규범 근거는 [sources.md](references/sources.md)에 있고 규칙 목록이나 말뭉치는
복사하지 않습니다. 이 스킬은 사람이 썼다는 점수나 검출 회피를 목표로 하지
않습니다.

## 검증

오프라인 계약 확인:

```bash
python3 skills/korean-writing-editor/evals/run.py --scope full
```

통과는 31개 픽스처와 문서 계약이 맞다는 뜻이지, 실제 모델 품질 증거가
아닙니다. 라이브 카나리는 별도 선택이며 따로 보고합니다. 라이브 양성
프롬프트에는 원고와 교정 요청만 넣습니다. 모델에게 CANARY나
skill_used를 적으라고 시키지 않습니다. 본문을 보고 판정합니다. 변경
동기화는 [CHANGE_PROTOCOL.md](CHANGE_PROTOCOL.md)를 따릅니다.

개발용 교차 모델 평가는 [교차 모델 평가 가이드](evals/README.md)를 따릅니다.
기본 `--dry-run`은 공급자를 호출하지 않으며, 실제 실행은 명시적인
`--execute`와 별도 라이브 증거 보고가 필요합니다.
