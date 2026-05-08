# forrestchang/andrej-karpathy-skills 상세 분석

작성일: 2026-05-06  
분석 대상: <https://github.com/forrestchang/andrej-karpathy-skills>  
분석 방식: 저장소의 공개 파일, README, `CLAUDE.md`, Cursor rule, Claude Code plugin/skill 메타데이터, 예제 문서를 확인해 정리했습니다. 실제 Claude Code/Cursor 환경에서 벤치마크를 실행한 것은 아니며, 문서·구성·프롬프트 설계 관점의 분석입니다.

---

## 1. 한 줄 결론

이 저장소는 **코딩 에이전트에게 “더 많이 하라”가 아니라 “덜 틀리게 하라”를 가르치는 초경량 행동 규칙 세트**입니다. 코드 라이브러리라기보다 `CLAUDE.md`, Cursor rule, Claude Code Skill/plugin 형태로 배포되는 **AI 코딩 에이전트용 운영 규범**에 가깝습니다.

제 견해로는, 이 저장소의 가치는 “새로운 기법”보다는 **현업 개발자가 LLM 코딩 에이전트에게 반복적으로 해줘야 하는 잔소리를 4개 원칙으로 압축했다는 점**에 있습니다. 특히 기존 코드베이스를 다루는 업무에서는 매우 실용적입니다.

---

## 2. 저장소 개요

| 항목 | 내용 |
|---|---|
| 저장소명 | `forrestchang/andrej-karpathy-skills` |
| 성격 | Claude Code / Cursor 등 AI 코딩 도구에 주입하는 행동 가이드라인 |
| 핵심 산출물 | `CLAUDE.md`, Cursor `.mdc` rule, Claude Code Skill/plugin 구성 |
| 라이선스 | MIT |
| 주요 목표 | LLM 코딩 에이전트의 잘못된 가정, 과잉 설계, 무관한 수정, 검증 없는 실행을 줄이는 것 |
| 실질적 형태 | “코드”보다는 “지속 주입되는 프롬프트/룰/스킬” |

README 기준으로 이 프로젝트는 Andrej Karpathy가 지적한 LLM 코딩의 실패 패턴을 바탕으로, Claude Code의 행동을 개선하기 위한 단일 `CLAUDE.md` 파일에서 출발합니다. 이후 Claude Code plugin, Skill, Cursor rule 형태로 확장되어 여러 환경에서 같은 지침을 적용할 수 있게 되어 있습니다.

---

## 3. 파일 구조와 역할

저장소의 핵심 파일은 다음과 같이 볼 수 있습니다.

```text
andrej-karpathy-skills/
├── CLAUDE.md
├── CURSOR.md
├── EXAMPLES.md
├── README.md
├── README.zh.md
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .cursor/
│   └── rules/
│       └── karpathy-guidelines.mdc
└── skills/
    └── karpathy-guidelines/
        └── SKILL.md
```

### 3.1 `README.md`

README는 이 저장소의 설명서이자 포지셔닝 문서입니다. 문제 정의, 4대 원칙, 설치 방법, Cursor 사용법, 효과 판단 기준, 커스터마이징 방법, 주의할 트레이드오프를 설명합니다.

핵심 역할은 다음과 같습니다.

- 이 저장소가 왜 필요한지 설명한다.
- Karpathy의 관찰을 “LLM 코딩 실패 패턴”으로 정리한다.
- 4개 원칙을 표 형태로 문제와 연결한다.
- Claude Code plugin 방식과 `CLAUDE.md` 직접 추가 방식을 안내한다.
- Cursor project rule과의 관계를 설명한다.

### 3.2 `CLAUDE.md`

이 저장소의 가장 중요한 파일입니다. 실제로 Claude Code가 프로젝트 컨텍스트로 읽어 행동을 조정하게 되는 핵심 지침입니다.

내용은 짧고 압축적입니다. 4개 원칙만 담고 있으며, 프로젝트별 규칙과 병합해 사용하라고 되어 있습니다. 즉, 이 파일은 완성형 개발 표준이라기보다는 **기본 행동 안전장치**입니다.

### 3.3 `skills/karpathy-guidelines/SKILL.md`

Claude Code Skill 형태로 같은 지침을 배포하기 위한 파일입니다. YAML frontmatter에 `name`, `description`, `license`가 들어 있고, 본문에는 4개 원칙이 담겨 있습니다.

중요한 점은 이 Skill이 특정 프레임워크나 언어에 종속되어 있지 않다는 것입니다. Python, JavaScript, TypeScript, Go, Rust 등 어떤 코드베이스에도 적용될 수 있는 **행동 레벨의 skill**입니다.

### 3.4 `.claude-plugin/plugin.json`

Claude Code plugin으로 설치될 때의 메타데이터입니다. 플러그인 이름, 설명, 버전, 작성자, 라이선스, 키워드, 포함된 skill 경로를 정의합니다.

이 파일을 보면 플러그인의 기능 범위가 매우 제한적입니다. 별도 실행 스크립트, hook, MCP 서버, 외부 명령어가 아니라 `skills` 항목만 가리키는 구조입니다. 따라서 저장소 자체만 놓고 보면 **실행 로직이 아니라 지침 배포용 plugin**에 가깝습니다.

### 3.5 `.claude-plugin/marketplace.json`

Claude Code plugin marketplace에 등록하기 위한 카탈로그 파일입니다. marketplace 이름, plugin 목록, 버전, 카테고리, 키워드 등을 담습니다.

README에 나오는 설치 명령은 이 marketplace 구조를 전제로 합니다.

### 3.6 `.cursor/rules/karpathy-guidelines.mdc`

Cursor에서 같은 지침을 project rule로 적용하기 위한 파일입니다. frontmatter에 `alwaysApply: true`가 들어 있어, Cursor 환경에서 프로젝트를 열면 규칙이 항상 적용되도록 설계되어 있습니다.

이 파일의 의미는 큽니다. 저장소가 Claude Code만을 타깃으로 하지 않고, **AI 코딩 IDE 전반의 지속 규칙 패턴**으로 확장 가능하다는 것을 보여줍니다.

### 3.7 `CURSOR.md`

Cursor에서 이 규칙을 사용하는 방법을 설명합니다. 이 저장소 안에서는 `.cursor/rules/karpathy-guidelines.mdc`가 이미 포함되어 있으므로 별도 설치가 필요 없고, 다른 프로젝트에 적용하려면 해당 `.mdc` 파일을 복사하라고 안내합니다.

### 3.8 `EXAMPLES.md`

실제 예시 기반 문서입니다. 각 원칙별로 “LLM이 흔히 잘못하는 방식”과 “바람직한 방식”을 비교합니다.

이 파일은 저장소의 설득력을 높이는 핵심 보조 자료입니다. `CLAUDE.md`만 보면 원칙은 좋아 보이지만 추상적일 수 있는데, `EXAMPLES.md`는 다음을 보여줍니다.

- 애매한 요구사항을 그대로 구현하면 어떤 문제가 생기는지
- 간단한 함수 하나를 과한 디자인 패턴으로 부풀리는 방식이 왜 나쁜지
- 버그 수정 중 주변 코드를 마음대로 바꾸는 일이 왜 위험한지
- “고쳐줘”를 “실패 테스트 작성 → 통과시키기”로 바꾸면 왜 검증 가능해지는지

---

## 4. 핵심 철학

이 저장소의 철학은 다음 문장으로 요약할 수 있습니다.

> LLM 코딩 에이전트는 능력이 부족해서만 실패하는 것이 아니라, **행동 규율이 부족해서 실패한다.**

일반적인 AI 코딩 실패는 다음 네 가지로 자주 나타납니다.

1. 요구사항이 애매한데도 확인하지 않고 진행한다.
2. 단순한 문제에 과한 추상화와 확장성을 붙인다.
3. 요청과 무관한 파일, 주석, 포맷, 구조를 바꾼다.
4. 성공 기준 없이 “작동하게 만들기” 식으로 구현한다.

이 저장소는 LLM에게 더 많은 도구를 주는 대신, **작업 전 태도와 변경 범위를 통제하는 규칙**을 줍니다. 그래서 기술적으로는 단순하지만, 실제 코드 리뷰·유지보수 비용을 줄이는 방향으로 설계되어 있습니다.

---

## 5. 4대 원칙 상세 분석

## 5.1 Think Before Coding — 코딩 전에 생각하라

### 원칙의 의미

요구사항이 불명확하면 바로 구현하지 말고, 먼저 가정·해석·트레이드오프를 드러내라는 원칙입니다.

### 겨냥하는 실패 패턴

LLM은 사용자의 짧은 요청을 보고 내부적으로 하나의 해석을 선택한 뒤, 그것을 정답처럼 밀고 나가는 경향이 있습니다. 예를 들어 “사용자 데이터 export 기능 추가”라는 요청에 대해 다음을 멋대로 결정할 수 있습니다.

- 전체 사용자를 export할지, 선택된 사용자만 export할지
- JSON인지 CSV인지
- 브라우저 다운로드인지 서버 파일 생성인지
- 개인정보 필드를 어디까지 포함할지
- 대량 데이터 처리 방식은 어떻게 할지

이 원칙은 그런 숨은 결정을 표면화하게 만듭니다.

### 좋은 점

- 요구사항 오해로 인한 재작업을 줄입니다.
- 보안·개인정보·성능 이슈를 초기에 드러냅니다.
- 사용자가 정말 원하는 결과를 더 빨리 좁힐 수 있습니다.

### 주의점

모든 작업에서 질문을 남발하면 생산성이 떨어집니다. 예를 들어 오타 수정, 명백한 import 정리, 간단한 테스트 이름 변경 같은 작업에 매번 장황한 확인을 요구하면 오히려 사용 경험이 나빠집니다.

### 제 평가

이 원칙은 가장 기본적이면서도 가장 자주 무시됩니다. 특히 제품 기능, 데이터 처리, 권한, 결제, 보안, 마이그레이션 관련 작업에서는 매우 중요합니다. 다만 “질문해야 할 모호성”과 “그냥 처리해도 되는 명백함”을 구분하는 추가 규칙이 있으면 더 좋겠습니다.

---

## 5.2 Simplicity First — 단순함을 우선하라

### 원칙의 의미

요청받은 문제를 해결하는 데 필요한 최소한의 코드만 작성하라는 원칙입니다. 아직 요구되지 않은 확장성, 설정 가능성, 추상화, 범용성을 미리 넣지 말라는 뜻입니다.

### 겨냥하는 실패 패턴

LLM은 “잘 설계된 코드”를 만들려다 오히려 필요 이상의 구조를 만듭니다.

예를 들어 단순 할인 계산 함수 하나면 충분한데 다음을 만들 수 있습니다.

- strategy pattern
- abstract base class
- protocol/interface
- config object
- factory
- validator
- future extension hook

이런 코드는 겉보기에는 전문적으로 보이지만, 실제 요구사항이 단순하면 유지보수 비용만 키웁니다.

### 좋은 점

- 코드 리뷰가 쉬워집니다.
- 버그 표면적이 줄어듭니다.
- 테스트 작성이 쉬워집니다.
- 변경 의도를 파악하기 쉽습니다.

### 주의점

“단순함”이 항상 “짧은 코드”는 아닙니다. 보안, 트랜잭션, 동시성, 데이터 정합성, 장애 복구 같은 영역에서는 충분한 방어 로직이 필요합니다. `No error handling for impossible scenarios`라는 취지는 이해되지만, 무엇이 “불가능한 시나리오”인지 잘못 판단하면 위험합니다.

### 제 평가

이 저장소의 가장 실용적인 원칙 중 하나입니다. 현재 AI 코딩 에이전트의 대표적인 문제는 “모르는 것을 묻지 않는 것”과 함께 “요청보다 더 큰 구조를 만들어 버리는 것”입니다. 다만 이 원칙은 프로젝트 성숙도에 따라 다르게 적용해야 합니다. 스타트업 MVP, 내부 도구, 실험 코드에서는 강하게 적용해도 좋지만, 금융·의료·보안·인프라 코드에서는 “단순함”과 “필수적 견고함”의 경계를 명시해야 합니다.

---

## 5.3 Surgical Changes — 외과 수술처럼 필요한 곳만 바꿔라

### 원칙의 의미

기존 코드 수정 시 요청과 직접 관련된 부분만 건드리라는 원칙입니다. 주변 코드 정리, 포맷 변경, 주석 변경, 스타일 변경, 리팩터링을 임의로 하지 말라는 것입니다.

### 겨냥하는 실패 패턴

AI 코딩 에이전트는 작은 버그 수정을 하면서도 다음 행동을 자주 합니다.

- 파일 전체 포맷팅
- quote style 변경
- 타입 힌트 추가
- 함수명 변경
- 주석 재작성
- 근처 dead code 삭제
- 구조 개선이라는 이름의 리팩터링

문제는 이런 변경이 버그 수정과 섞이면 리뷰가 어려워지고, 회귀 버그가 생겨도 원인 추적이 어려워진다는 점입니다.

### 좋은 점

- diff가 작아집니다.
- 코드 리뷰 비용이 크게 줄어듭니다.
- regression 원인 추적이 쉬워집니다.
- 팀의 기존 스타일과 관성을 존중합니다.

### 주의점

때로는 문제의 원인이 구조적일 수 있습니다. 그 경우 surgical change만 고집하면 근본 문제를 덮는 patch가 될 수 있습니다. 따라서 이 원칙에는 다음 보완 규칙이 필요합니다.

> 요청 범위를 넘어서는 구조적 문제가 보이면 직접 고치지 말고, 별도 제안으로 분리하라.

이 저장소도 “무관한 dead code는 삭제하지 말고 언급하라”는 취지를 담고 있어 이 방향과 잘 맞습니다.

### 제 평가

팀 개발 환경에서는 가장 효과가 큰 원칙입니다. AI가 만든 PR이 싫어지는 큰 이유는 “내가 요청한 것보다 훨씬 많은 것을 바꿔놨기 때문”입니다. 이 원칙은 AI를 똑똑한 설계자가 아니라 **리뷰 가능한 변경을 만드는 협업자**로 제한합니다. 저는 이 원칙을 모든 AI 코딩 환경에 기본값으로 넣는 편이 좋다고 봅니다.

---

## 5.4 Goal-Driven Execution — 성공 기준 중심으로 실행하라

### 원칙의 의미

“이걸 해줘”라는 명령을 “무엇을 만족하면 성공인지”로 바꾸라는 원칙입니다. 특히 테스트를 먼저 작성하고, 그 테스트를 통과시키는 식의 검증 루프를 강조합니다.

### 겨냥하는 실패 패턴

LLM은 “고쳐줘”, “개선해줘”, “리팩터링해줘” 같은 요청을 받으면 성공 기준을 임의로 정합니다. 그러면 구현은 많이 했지만 실제 문제가 해결됐는지 불분명해집니다.

이 원칙은 다음과 같은 변환을 요구합니다.

| 막연한 요청 | 더 나은 목표 표현 |
|---|---|
| validation 추가 | 잘못된 입력을 재현하는 테스트를 만들고 통과시키기 |
| bug 수정 | 버그를 재현하는 실패 테스트를 만든 뒤 통과시키기 |
| refactor | 리팩터링 전후 테스트가 모두 통과함을 확인하기 |
| 성능 개선 | 현재 지표 측정 → 목표 지표 정의 → 개선 후 재측정 |

### 좋은 점

- AI가 스스로 반복 개선할 수 있는 루프가 생깁니다.
- 결과 검증이 쉬워집니다.
- 사용자가 구현 세부사항을 일일이 지시하지 않아도 됩니다.
- 테스트 중심 개발과 잘 맞습니다.

### 주의점

테스트가 부실하거나 테스트 실행 환경이 준비되어 있지 않으면 이 원칙의 효과가 제한됩니다. 또한 UI/UX, 문서, 디자인, 데이터 분석처럼 정량 테스트가 어려운 작업에서는 성공 기준을 더 섬세하게 정의해야 합니다.

### 제 평가

4개 원칙 중 가장 “agentic coding”에 잘 맞는 원칙입니다. 코딩 에이전트는 긴 루프를 돌며 시도하고 검증하는 데 강점이 있으므로, 성공 기준을 명확히 주면 성능이 좋아집니다. 반대로 성공 기준이 없으면 빠르게 많이 만들 뿐, 맞는 것을 만들었다고 보기 어렵습니다.

---

## 6. 이 저장소가 실제로 해결하려는 문제

이 저장소는 프롬프트 품질 문제가 아니라 **AI 협업 프로토콜 문제**를 다룹니다.

| 문제 | 일반적인 AI 행동 | 이 저장소가 유도하는 행동 |
|---|---|---|
| 요구사항 모호성 | 알아서 가정하고 진행 | 가정과 해석을 먼저 드러냄 |
| 과잉 구현 | 미래 요구까지 추측해 구조화 | 현재 요구만 최소 구현 |
| 무관한 변경 | 주변 코드까지 개선 | 요청과 직접 관련된 줄만 수정 |
| 검증 부재 | 구현 후 “완료”라고 말함 | 테스트·검증 기준을 먼저 정의 |
| 리뷰 난이도 | 큰 diff 생성 | 작은 diff와 명확한 변경 이유 유지 |

핵심은 “AI가 더 많은 코드를 쓰게 하는 것”이 아니라 **AI가 변경 권한을 남용하지 않게 하는 것**입니다.

---

## 7. Claude Code 관점 분석

Claude Code는 `CLAUDE.md`를 통해 프로젝트별 지속 지침을 읽을 수 있습니다. 공식 문서상 `CLAUDE.md`는 프로젝트, 사용자, 조직 범위에서 사용할 수 있는 기억/지침 파일이며, 세션 시작 시 컨텍스트로 로드됩니다. 따라서 이 저장소의 접근 방식은 Claude Code의 설계와 잘 맞습니다.

다만 중요한 한계가 있습니다.

`CLAUDE.md`는 강제 정책 엔진이 아닙니다. 모델이 읽고 따르도록 유도하는 컨텍스트입니다. 그러므로 다음과 같은 보완책이 필요합니다.

- 테스트 실행을 실제 워크플로우에 포함한다.
- lint/typecheck/CI를 반드시 통과하게 한다.
- PR 리뷰에서 “요청과 무관한 변경”을 별도 체크한다.
- 위험한 변경은 인간 승인을 요구한다.
- security, data migration, auth 등 고위험 영역은 별도 프로젝트 규칙을 추가한다.

즉, 이 저장소는 **좋은 기본 프롬프트**이지 **품질 보증 시스템 전체**는 아닙니다.

---

## 8. Cursor 관점 분석

Cursor는 `.cursor/rules` 아래의 project rule을 통해 에이전트 동작에 지속 지침을 줄 수 있습니다. 이 저장소는 `.cursor/rules/karpathy-guidelines.mdc` 파일을 제공하고, `alwaysApply: true`로 설정해 Cursor에서 항상 적용되도록 합니다.

이 접근은 장점이 있습니다.

- 팀 저장소에 rule을 커밋하면 팀원들이 같은 규칙을 공유할 수 있습니다.
- Claude Code를 쓰지 않는 사람도 Cursor에서 비슷한 효과를 얻을 수 있습니다.
- IDE 단위에서 지속적으로 같은 행동 규범을 적용할 수 있습니다.

하지만 `alwaysApply: true`는 과도할 수도 있습니다. 모든 작업에 항상 포함되면 컨텍스트를 조금씩 차지하고, 아주 단순한 작업에서도 모델이 필요 이상으로 조심할 수 있습니다. 팀 환경에서는 다음처럼 조정하는 것도 좋습니다.

- 기본 원칙은 always apply로 유지한다.
- 긴 예시나 세부 프로토콜은 agent-requested rule로 분리한다.
- 특정 폴더별 규칙은 path-scoped rule로 분리한다.

---

## 9. Plugin/Skill 구조 분석

이 저장소의 plugin 구성은 단순합니다.

- `.claude-plugin/plugin.json`은 plugin 메타데이터와 skill 경로를 지정합니다.
- `.claude-plugin/marketplace.json`은 marketplace 설치를 위한 카탈로그 역할을 합니다.
- `skills/karpathy-guidelines/SKILL.md`가 실제 행동 지침입니다.

실행 코드나 외부 명령 hook이 중심이 아니라, **재사용 가능한 Skill 배포**가 중심입니다. 이 점은 보안상 비교적 안심할 수 있는 구조입니다. 다만 어떤 plugin이든 설치 전에는 파일 내용을 확인하는 습관이 필요합니다. 특히 AI 도구 plugin은 향후 hook, MCP 서버, command 등을 포함할 수 있으므로 저장소 구조와 manifest를 먼저 확인해야 합니다.

---

## 10. 장점

## 10.1 매우 작고 이해하기 쉽다

이 저장소는 복잡한 프레임워크가 아닙니다. 핵심은 Markdown 지침입니다. 그래서 도입 비용이 거의 없습니다. 복사해서 `CLAUDE.md`에 넣거나 Cursor rule로 추가하면 됩니다.

## 10.2 실제 개발자가 겪는 AI 코딩 문제를 정확히 겨냥한다

LLM 코딩 에이전트의 문제는 “코드를 못 씀”이 아니라 다음과 같은 행동 문제인 경우가 많습니다.

- 자신 없는 부분을 숨김
- 사용자의 의도를 추측함
- 너무 많이 바꿈
- 너무 복잡하게 만듦
- 검증 없이 완료 선언

이 저장소는 이 문제를 정확히 찌릅니다.

## 10.3 도구 독립적이다

Claude Code 중심으로 시작했지만 Cursor rule과 Skill 형태를 제공하기 때문에 다른 agent 환경에도 쉽게 이식할 수 있습니다. AGENTS.md, GEMINI.md, Copilot instructions 등에도 유사하게 적용할 수 있습니다.

## 10.4 코드 리뷰 친화적이다

“Surgical Changes” 원칙은 PR 품질과 직결됩니다. AI가 만든 diff가 작아지고, 변경 의도가 명확해지며, 리뷰어가 본질적인 변경에 집중할 수 있습니다.

## 10.5 테스트 중심 루프와 잘 맞는다

“Goal-Driven Execution”은 테스트 주도 개발과 매우 잘 맞습니다. AI에게 구현 세부 지시를 던지는 대신, 실패 테스트와 성공 기준을 주면 더 안정적인 결과를 얻을 수 있습니다.

---

## 11. 한계와 리스크

## 11.1 강제력이 없다

이 지침은 모델에게 컨텍스트로 주입되는 텍스트입니다. 모델이 항상 따르는 것은 아닙니다. 특히 긴 세션, 상충되는 지시, 압박적인 사용자 요청, 복잡한 코드베이스에서는 일부 원칙이 희석될 수 있습니다.

## 11.2 프로젝트별 맥락이 없다

이 저장소의 규칙은 범용적입니다. 따라서 다음 정보는 각 프로젝트에서 반드시 추가해야 합니다.

- 빌드 명령
- 테스트 명령
- 린트/포맷 명령
- 아키텍처 경계
- 코딩 스타일
- 보안 규칙
- API 호환성 정책
- 데이터베이스 마이그레이션 규칙
- 배포/릴리즈 프로세스

범용 규칙만 넣고 프로젝트 규칙을 생략하면 “예의 바른 AI”는 만들 수 있어도 “프로젝트를 아는 AI”는 만들기 어렵습니다.

## 11.3 지나친 보수성

이 저장소는 속도보다 신중함에 치우쳐 있습니다. 이것은 장점이지만, 모든 상황에 맞지는 않습니다.

다음 작업에서는 오히려 답답할 수 있습니다.

- 빠른 프로토타이핑
- throwaway script 작성
- 대략적인 탐색 코드
- 초기 설계 브레인스토밍
- 명백한 일괄 포맷팅
- 사용자가 명시적으로 대규모 리팩터링을 원하는 경우

## 11.4 “단순함”의 오해 가능성

단순함은 중요하지만, 시스템 프로그래밍·보안·분산 시스템·금융 거래·권한 모델에서는 단순함만으로 충분하지 않습니다. “불가능해 보이는 오류”가 실제 운영에서는 자주 발생합니다. 그러므로 고위험 프로젝트에서는 다음 문장을 추가하는 것이 좋습니다.

```markdown
For security, data integrity, concurrency, and irreversible operations, do not omit necessary validation or error handling in the name of simplicity.
```

## 11.5 성공 기준을 만들기 어려운 작업에는 약하다

테스트 가능한 코드 변경에는 잘 맞지만, 다음 작업은 별도 기준이 필요합니다.

- UI 시각 품질
- UX copy 개선
- 문서 톤 조정
- 데이터 분석 해석
- 제품 전략
- 아키텍처 의사결정

이런 경우에는 테스트 대신 acceptance criteria, screenshot comparison, checklist, reviewer approval 같은 기준을 써야 합니다.

---

## 12. 실무 도입 방법

## 12.1 개인 프로젝트

가장 간단한 방식은 `CLAUDE.md`에 이 저장소의 내용을 추가하는 것입니다.

추천 방식:

1. 저장소의 `CLAUDE.md` 내용을 복사한다.
2. 프로젝트 루트의 `CLAUDE.md`에 붙여 넣는다.
3. 아래 프로젝트별 정보를 추가한다.
   - 실행 명령
   - 테스트 명령
   - package manager
   - 코드 스타일
   - 금지 사항
   - 배포 전 체크리스트

예시:

```markdown
## Project-Specific Rules

- Use pnpm, not npm.
- Run `pnpm test` after behavior changes.
- Run `pnpm typecheck` before declaring completion.
- Do not modify database migrations unless explicitly asked.
- Keep API response shapes backward compatible unless the task says otherwise.
```

## 12.2 팀 프로젝트

팀에서는 단순 복사보다 다음 구조를 추천합니다.

```text
CLAUDE.md
.claude/
  rules/
    testing.md
    security.md
    api-compatibility.md
.cursor/
  rules/
    karpathy-guidelines.mdc
```

운영 방식:

- `CLAUDE.md`: 전역 개발 원칙과 주요 명령
- `.cursor/rules`: Cursor 사용자용 persistent rule
- `testing.md`: 테스트 전략
- `security.md`: 보안·권한·비밀정보 처리
- `api-compatibility.md`: API breaking change 정책

## 12.3 PR 리뷰 기준으로 연결

AI가 만든 PR에서 다음 체크리스트를 사용하면 좋습니다.

```markdown
## AI Change Review Checklist

- [ ] 변경된 모든 줄이 요청과 직접 관련되는가?
- [ ] 요구사항이 모호한데 AI가 임의로 가정한 부분은 없는가?
- [ ] 과한 추상화, 설정, 확장 포인트가 추가되지 않았는가?
- [ ] 실패 테스트 또는 재현 케이스가 있는가?
- [ ] 기존 테스트/lint/typecheck가 통과했는가?
- [ ] 무관한 포맷팅, 주석 변경, drive-by refactor가 없는가?
```

---

## 13. 내가 권장하는 보강판

이 저장소의 원칙은 좋지만, 그대로 쓰기보다는 아래 내용을 덧붙이면 더 안정적입니다.

```markdown
## Risk-Based Behavior

Classify the task before editing:

- Trivial: typo, comment, one-line obvious fix. Proceed directly and summarize.
- Normal: localized code change. State a short plan and verify with relevant tests.
- Risky: auth, payments, data migration, security, concurrency, public API, irreversible operations. Stop and state assumptions, risks, rollback plan, and verification strategy before editing.

## Verification Discipline

Before saying the task is complete:

- Say exactly what was changed.
- Say what was not changed.
- List verification commands run and results.
- If verification was not run, say why clearly.

## Change Boundary

Do not combine unrelated cleanup with the requested change.
If you find unrelated issues, report them under “Follow-up suggestions” instead of changing them.

## Simplicity Exception

Prefer simple code, but do not remove necessary validation, authorization checks, transaction safety, or error handling for external systems.
```

이 보강판은 원 저장소의 철학을 유지하면서도, 실무에서 중요한 위험도 분류와 검증 보고를 추가합니다.

---

## 14. 어떤 사람에게 유용한가

## 14.1 특히 유용한 경우

- Claude Code, Cursor, Copilot Agent 등으로 실제 코드 수정을 자주 하는 개발자
- AI가 만든 diff가 너무 커서 리뷰하기 힘든 팀
- AI가 요구사항을 추측해서 엉뚱한 기능을 만드는 경험을 자주 하는 사람
- 기존 코드베이스에서 작은 수정·버그 픽스·테스트 보강을 많이 하는 팀
- AI coding workflow를 팀 표준으로 만들고 싶은 조직

## 14.2 덜 유용한 경우

- 단순 질문 답변 위주로 AI를 쓰는 사용자
- 코딩 에이전트가 실제 파일을 수정하지 않는 환경
- 빠른 실험과 throwaway code가 대부분인 경우
- 이미 매우 정교한 내부 agent policy와 CI guardrail을 갖춘 조직

---

## 15. 이 저장소의 본질적 가치

이 저장소의 가치는 파일 수나 코드 복잡도가 아니라 **문제 정의의 정확성**에 있습니다.

많은 AI 코딩 도구 사용자는 처음에 “모델이 더 똑똑해지면 해결될 것”이라고 생각합니다. 하지만 실제로는 모델이 똑똑해져도 다음 문제는 남습니다.

- 무엇을 바꾸면 안 되는지 모른다.
- 요구사항의 모호성을 인간처럼 조심스럽게 다루지 않는다.
- 좋은 설계와 과잉 설계를 구분하지 못한다.
- 검증 기준 없이 완료했다고 말한다.

이 저장소는 그 문제를 “프롬프트 한 파일”로 완전히 해결한다고 보기는 어렵지만, **기본 실패율을 낮추는 저비용 장치**로는 매우 훌륭합니다.

---

## 16. 내 견해

저는 이 저장소를 **AI 코딩 에이전트 시대의 `.editorconfig` 같은 것**으로 봅니다. `.editorconfig`가 코드 포맷의 기본 마찰을 줄이듯, 이 저장소는 AI 에이전트의 행동 마찰을 줄입니다.

다만 `.editorconfig`가 코드 품질 전체를 보장하지 않듯, 이 저장소도 AI 코딩 품질 전체를 보장하지는 않습니다. 반드시 테스트, 타입 체크, 린트, 코드 리뷰, 보안 리뷰와 함께 써야 합니다.

제 평가는 다음과 같습니다.

| 평가 항목 | 점수 | 의견 |
|---|---:|---|
| 문제 정의 | 9/10 | AI 코딩에서 실제로 반복되는 문제를 잘 잡았습니다. |
| 실용성 | 9/10 | 복사해서 바로 쓸 수 있을 정도로 가볍습니다. |
| 완성도 | 7/10 | 범용 지침으로는 충분하지만 프로젝트별 보강은 필수입니다. |
| 안전성 | 8/10 | 실행 코드 중심이 아니라 위험은 낮지만, plugin 설치 전 검토는 필요합니다. |
| 확장성 | 8/10 | Claude Code, Cursor, Skill 구조로 확장 가능합니다. |
| 총평 | 8.5/10 | AI 코딩을 진지하게 쓰는 사람이라면 기본값으로 넣을 만합니다. |

가장 마음에 드는 부분은 **“AI를 더 적극적으로 만들지 않고, 더 절제 있게 만든다”**는 점입니다. 현재 AI 코딩 도구는 대체로 실행력은 충분한데 절제력이 부족합니다. 이 저장소는 그 균형을 잡는 데 도움이 됩니다.

반대로 아쉬운 점은 **위험도별 행동 차등화가 부족하다**는 것입니다. 오타 수정과 결제 로직 변경은 같은 수준의 신중함이 필요하지 않습니다. 향후 개선판이 나온다면 task risk classification, verification report format, rollback plan 같은 섹션이 추가되면 더 실무적일 것입니다.

---

## 17. 최종 추천

저는 이 저장소를 그대로 설치하거나 복사해서 쓰되, 반드시 프로젝트별 규칙을 덧붙이는 방식을 추천합니다.

추천 적용 순서는 다음과 같습니다.

1. `CLAUDE.md` 또는 Cursor rule로 기본 4대 원칙을 추가한다.
2. 프로젝트별 build/test/lint/typecheck 명령을 추가한다.
3. 보안·인증·결제·DB migration 등 고위험 영역 규칙을 별도로 추가한다.
4. AI가 작업 완료 시 “변경 내용 / 검증 결과 / 미검증 사항”을 보고하게 한다.
5. PR 리뷰에서 “요청과 무관한 변경 없음”을 체크한다.

결론적으로, 이 저장소는 **작지만 매우 효과적인 AI 코딩 행동 가드레일**입니다. AI coding agent를 실무에 쓰고 있다면, 도입하지 않을 이유보다 도입할 이유가 훨씬 큽니다.

---

## 18. 참고한 주요 출처

- GitHub repository: <https://github.com/forrestchang/andrej-karpathy-skills>
- README raw: <https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/README.md>
- CLAUDE.md raw: <https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/CLAUDE.md>
- EXAMPLES.md raw: <https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/EXAMPLES.md>
- Cursor rule raw: <https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/.cursor/rules/karpathy-guidelines.mdc>
- Skill raw: <https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/skills/karpathy-guidelines/SKILL.md>
- Claude Code memory docs: <https://code.claude.com/docs/en/memory>
- Claude Code plugins docs: <https://code.claude.com/docs/en/plugins>
- Cursor rules docs: <https://docs.cursor.com/context/rules>
