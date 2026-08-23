# kws-image-workbench

## 1분 시작

프로젝트 안에서 쓸 래스터 이미지는 자연어로 바로 요청하면 됩니다.

- `$kws-image-workbench 이 프로젝트 랜딩 페이지 hero 이미지를 만들어줘.`
- `$kws-image-workbench 이 상품 사진은 그대로 두고 배경만 바꿔줘.`
- `$kws-image-workbench 생성하지 말고 이미지 브리프만 정리해줘.`
- `$kws-image-workbench 이 자산이 모바일 크롭과 다크 모드에 맞는지 검토해줘.`

앞의 두 요청은 각각 새 생성과 편집입니다. 세 번째는 `brief`, 네 번째는
`audit`입니다. 먼저 비슷한 요청을 구분합니다. 프로젝트 맥락 없는 재미용
이미지는 일반 bundled imagegen을 쓰고, SVG·아이콘·실제 UI·데이터 차트·정확한
다이어그램은 이 스킬이 아니라 native workflow로 보냅니다.

## 언제 사용하나

로컬 프로젝트에 저장하거나 통합할 래스터 asset, 기존 래스터 편집, 이미지
brief, 또는 asset audit에 사용합니다. 소비 surface, 대상 경로, supplied target
중 하나를 확인할 수 있어야 합니다. 단순 이미지 검색이나 저작권 조사만 하는
일에는 사용하지 않습니다.

## 네 가지 모드

| 모드 | 하는 일 | 이미지 생성 호출 |
| --- | --- | --- |
| `brief` | `ImageSpec`과 확인 조건을 준비 | 하지 않음 |
| `generate` | 새 래스터 asset을 생성·검사·저장 | 명확한 생성 요청일 때만 bundled executor 사용 |
| `edit` | 하나의 식별된 edit target을 수정 | 명확한 편집 요청일 때만 bundled executor 사용 |
| `audit` | 파일과 handoff 상태를 읽기 전용으로 검사 | 하지 않음 |

`brief`와 `audit`은 생성·편집·교체·통합을 승인하지 않습니다. bundled executor가
없으면 hold와 명시적 fallback을 보고하며, 다른 provider·CLI로 조용히 전환하지
않습니다.

## 참조 이미지 역할

각 입력 이미지는 정확히 하나의 역할을 가집니다: `edit_target`,
`subject_reference`, `style_reference`, 또는 `compositing_input`.
`edit_target`만 실제 변경 대상이며, 참조 이미지는 사람·mark·보호된 작업을
복제할 권한을 주지 않습니다. 복잡한 요청은 [ImageSpec reference](references/image-spec.md)를
따릅니다.

## 하이브리드 경계

정확한 한국어 문구, 수치·차트, 기존 로고·아이콘, 실제 UI·반응형 layout은
생성 결과만으로 확정하지 않습니다. 필요한 경우 배경·illustration은 생성하고,
문구·데이터·mark·layout은 프로젝트의 native tool로 추가하는 hybrid route를
사용합니다. 결과는 [quality rubric](references/quality-rubric.md)의 시각·기계
검사를 모두 통과해야 handoff할 수 있습니다.

## 저장과 결과 보고

프로젝트 결과물은 기본적으로 새 파일 또는 versioned sibling에 저장합니다. 기존
파일 교체는 명시적으로 승인된 경우에만 합니다. 최종 보고에는 path 또는 preview,
operation/route, 간결한 prompt, 핵심 evidence status, consuming code 또는 metadata
변경 여부를 포함합니다. 필요하면 `inspect_asset.py`가 format, dimensions, alpha,
byte size, SHA-256, path readiness를 확인하지만 SHA-256은 권리나 provenance의
증거가 아닙니다.

## 설치

이 v1 설치 지침은 Codex 전용입니다. 추적되는 Archive source
`skills/kws-image-workbench/`가 canonical입니다. mutation 전에 명시적 target
`/Users/kws/.agents/skills/kws-image-workbench`의 type과 destination을 확인합니다.
없거나 canonical source를 안전하게 가리키는 경우에만 복사 또는 link를 선택하고,
기존 real directory는 절대 덮어쓰지 않습니다.

```bash
KWS_IMAGE_SOURCE="/Users/kws/source/private/Archive/skills/kws-image-workbench"
KWS_IMAGE_TARGET="/Users/kws/.agents/skills/kws-image-workbench"
test -e "$KWS_IMAGE_TARGET" -o -L "$KWS_IMAGE_TARGET"
readlink "$KWS_IMAGE_TARGET"
```

위 검사는 상태만 확인합니다. 설치를 자동화하는 script나 제거 command는 제공하지
않습니다. 안전한 식별 후에만 사람이 copy/link를 선택합니다. discovery를 새로
읽으려면 새 Codex task를 시작하거나 app을 재시작합니다. Claude Code, Cursor,
Gemini, Grok은 `not_measured`이며 유사성으로 compatible하다고 주장하지 않습니다.

## 업데이트와 제거

업데이트는 canonical tracked source의 검증과 target 확인을 먼저 합니다. target이
기존 real directory이거나 다른 destination을 가리키면 변경하지 않고 `blocked`로
보고합니다. 제거는 이 문서의 자동 작업 범위가 아니며 destructive command를
제공하지 않습니다.

## 개인정보 권리 출처

private reference, prompt, output을 Git fixture로 저장하지 않습니다. 새 외부 upload,
불명확한 인물·mark·example image 권리, 또는 불명확한 consent는 hold 사유입니다.
source URL, repository code license, output hash, C2PA provenance은 각각 다른
정보일 뿐 ownership, consent, truth, commercial-use permission을 증명하지 않습니다.
근거와 pin은 [evidence register](references/sources.md)에 기록합니다.

## 검증과 한계

오프라인 contract evidence는 결정 fixture, 문서, inspector 계약을 검사할 뿐 live
image quality, rights clearance, provider superiority를 증명하지 않습니다. live
canary는 opt-in이고 별도 보고합니다.

```bash
python3 skills/kws-image-workbench/evals/run.py --self-test
python3 skills/kws-image-workbench/evals/run.py --scope fixtures
python3 skills/kws-image-workbench/evals/run.py --scope core
python3 skills/kws-image-workbench/evals/run.py --scope full
python3 skills/kws-image-workbench/scripts/inspect_asset.py --self-test
```

변경 범위와 SemVer 규칙은 [Change Protocol](CHANGE_PROTOCOL.md)을 따릅니다.
