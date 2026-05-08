# Codex로 이미지 목업을 “제대로 된 UI”로 구현하게 만드는 방법

> Reddit r/codex 글 **“How to get Codex to create proper UIs out of gpt-image-2 mock ups”** 요약 및 실전용 워크플로우 정리  
> 원문: https://www.reddit.com/r/codex/comments/1t1klni/how_to_get_codex_to_create_proper_uis_out_of/

---

## 1. 핵심 요약

이미지 생성 모델로 만든 UI 목업을 Codex 같은 코딩 에이전트에게 바로 “이 디자인으로 웹앱 만들어줘”라고 넘기면, 반응형이 깨지거나 구현 품질이 낮아질 가능성이 크다.

글쓴이의 핵심 주장은 다음과 같다.

> **이미지 목업 → 바로 구현**이 아니라,  
> **이미지 목업 → 디자인 시스템 추출 → 디자인 시스템 구현 → 화면 구현** 순서로 진행해야 한다.

사람 프론트엔드 개발자도 목업 이미지를 보고 곧바로 전체 앱을 구현하지 않는다. 먼저 색상, 레이아웃, 컴포넌트, 컨트롤, 간격, 반응형 규칙 등으로 디자인 시스템을 정리한 뒤 구현한다. AI 코딩 에이전트에도 같은 과정을 요구해야 결과가 좋아진다는 내용이다.

---

## 2. 흔한 실패 패턴

많은 사용자가 다음처럼 작업한다.

```text
1. “Teams보다 좋은 협업 앱 UI 목업 만들어줘.”
2. 이미지 생성 모델이 목업 이미지를 만든다.
3. “이 디자인 그대로 웹앱으로 구현해줘.”
4. Codex가 깨진 레이아웃, 비반응형 UI, 일관성 없는 컴포넌트를 만든다.
```

이 방식이 실패하는 이유는, Codex가 이미지 한 장에서 다음을 모두 추론해야 하기 때문이다.

- 색상 토큰
- 타이포그래피 규칙
- 버튼, 입력창, 카드, 모달 등 컴포넌트 상태
- 데스크톱·태블릿·모바일 레이아웃 규칙
- 간격, 그리드, 브레이크포인트
- 인터랙션과 접근성 규칙
- 어떤 UI 프레임워크를 사용할지

즉, 구현에 필요한 중간 설계 산출물이 빠져 있다.

---

## 3. 추천 워크플로우

### Step 1. 목업 이미지를 만든다

먼저 원하는 제품/화면의 시각적 방향을 이미지 생성 모델로 만든다.

예시:

```text
Create a high-fidelity UI mockup for a modern team collaboration app.
It should feel like Slack and Teams, but cleaner, faster, and more focused.
```

---

### Step 2. 목업에서 디자인 시스템을 추출한다

목업을 바로 구현하지 말고, 먼저 디자인 시스템으로 분해하도록 요청한다.

원문에서 제안한 프롬프트의 취지는 다음과 같다.

```text
이 목업을 기반으로 디자인 시스템을 만들어줘.
색상, 레이아웃, 컨트롤, 컴포넌트, 타이포그래피 등 각 파트가 독립적으로 설명되도록 필요한 만큼 이미지를 나누어 생성해줘.
```

실전용으로는 이렇게 바꿔 쓸 수 있다.

```text
Analyze this UI mockup and extract a complete design system from it.
Break it down into separate sections:

1. Color palette and semantic color tokens
2. Typography scale
3. Spacing and layout grid
4. Core components
5. Button, input, card, modal, sidebar, top navigation patterns
6. Responsive behavior for desktop, tablet, and mobile
7. Interaction states: hover, focus, disabled, active, error, loading
8. Accessibility rules

Create separate visual references or structured descriptions for each section.
Do not implement the app yet.
```

---

### Step 3. 기존 UI 프레임워크와 맞춘다

글쓴이는 Codex가 모든 컨트롤을 처음부터 직접 만들게 하기보다, 원하는 디자인과 가까운 UI 프레임워크를 조사해 선택하게 하는 것이 더 낫다고 말한다.

예시 프롬프트:

```text
Based on this design system, research which UI framework or component library is closest to the intended visual style.
Compare options such as shadcn/ui, Radix UI, MUI, Chakra UI, Mantine, Tailwind UI, or other relevant frameworks.
Recommend one primary option and explain how to adapt it to this design system.
```

이 접근의 장점:

- 기본 컴포넌트 품질이 높아진다.
- 접근성, 상태 처리, 키보드 인터랙션을 직접 구현할 필요가 줄어든다.
- 디자인 시스템을 토큰과 컴포넌트 레벨에서 안정적으로 적용할 수 있다.
- 구현 시간이 줄어든다.

---

### Step 4. 디자인 시스템부터 구현한다

앱 화면을 바로 만들지 말고, 다음 순서로 구현한다.

```text
1. 디자인 토큰
   - 색상
   - 폰트
   - 간격
   - radius
   - shadow
   - z-index

2. 레이아웃 시스템
   - page shell
   - sidebar
   - top bar
   - content grid
   - responsive containers

3. 기본 컴포넌트
   - Button
   - Input
   - Select
   - Card
   - Modal
   - Tabs
   - Navigation

4. 컴포넌트 상태
   - hover
   - focus
   - active
   - disabled
   - loading
   - error

5. 실제 화면 조립
   - dashboard
   - settings
   - detail page
   - empty state
   - mobile view
```

---

### Step 5. 한 번에 다 시키지 말고 단계별 리뷰한다

댓글에서 글쓴이는 “사람 주니어 개발자에게도 한 번에 전부 맡기지 않는다”는 비유를 든다. AI 에이전트도 마찬가지로 작은 단위로 작업시키고, 각 단계마다 리뷰해야 한다.

권장 방식:

```text
1. 레이아웃 컨테이너만 구현
2. 리뷰
3. 커밋
4. 색상/타이포그래피 토큰 구현
5. 리뷰
6. 커밋
7. 버튼/입력창 등 핵심 컴포넌트 구현
8. 리뷰
9. 커밋
10. 실제 화면 조립
```

이렇게 하면 특정 단계가 잘못되었을 때 되돌리기 쉽고, 잘못된 추론이 전체 앱으로 번지는 것을 막을 수 있다.

---

## 4. 구현 순서 예시 프롬프트

### 4.1 레이아웃 먼저 구현

```text
Look at the design system, especially the layout section.
Implement only the responsive layout containers first.

Requirements:
- Desktop, tablet, and mobile breakpoints must be handled explicitly.
- Do not implement detailed components yet.
- Use placeholder blocks for cards, buttons, and content.
- Keep the implementation minimal and reviewable.
- Explain the layout decisions after implementation.
```

---

### 4.2 토큰 구현

```text
Implement the design tokens from the design system.

Include:
- semantic colors
- typography scale
- spacing scale
- border radius
- shadows
- component density

Do not build full screens yet.
Create a small visual token preview page so I can review the system.
```

---

### 4.3 컴포넌트 구현

```text
Now implement the core components based on the design system.

Start with:
- Button
- Input
- Card
- Sidebar item
- Top navigation item

For each component, include states:
- default
- hover
- focus
- active
- disabled
- loading if relevant

Create a component preview page for review.
Do not build the final app screen yet.
```

---

### 4.4 실제 화면 조립

```text
Using the implemented design tokens, layout containers, and core components,
assemble the target screen from the original mockup.

Rules:
- Do not introduce new colors or spacing values unless necessary.
- Reuse existing components.
- Preserve responsive behavior.
- If something is missing from the design system, stop and list what needs to be added before implementing it.
```

---

## 5. AGENTS.md 또는 프로젝트 메모리에 남길 내용

댓글에서 글쓴이는 Codex가 실수한 부분을 수정한 뒤, 그 교정 내용을 `AGENTS.md`나 별도 스킬 파일에 기록하라고 조언한다. 이렇게 하면 같은 실수를 반복할 가능성을 줄일 수 있다.

예시:

```md
# UI Implementation Rules

## Design system first
- Never implement a screen directly from a visual mockup.
- First extract or read the design system.
- Implement tokens, layout primitives, and components before assembling screens.

## Responsive layout
- Always implement desktop, tablet, and mobile layouts explicitly.
- Use layout containers before detailed content.
- Do not rely on fixed pixel widths unless the design system requires it.

## Component reuse
- Reuse existing components whenever possible.
- Do not introduce one-off button, card, input, or navigation styles.
- If a new visual pattern is needed, propose a design system addition first.

## Review discipline
- Implement in small steps.
- After each major step, provide a review summary and list any assumptions.
- Do not proceed to final screen assembly until tokens, layout, and components are complete.
```

---

## 6. 중요한 관점: AI에게도 “업무 맥락”을 줘야 한다

글쓴이의 가장 중요한 메시지는 단순한 프롬프트 기술이 아니라 **업무 방식의 재현**이다.

사람 주니어 개발자는 보통 다음 맥락을 가진다.

- 회의에서 요구사항을 들었다.
- 문서를 읽었다.
- 질문을 했다.
- 중간 결과를 리뷰받았다.
- 잘못된 방향이면 피드백을 받았다.

AI 에이전트에게는 이런 맥락이 자동으로 주어지지 않는다. 따라서 사용자가 직접 다음을 제공해야 한다.

- 목표
- 디자인 시스템
- 기술 스택
- 구현 순서
- 리뷰 기준
- 허용되는 변경 범위
- 되돌릴 수 있는 작은 작업 단위

---

## 7. 반론 및 주의점

댓글에는 “이건 진짜 디자인 시스템이 아니라 이미지 모음에 가깝다”는 비판도 있었다. 전문적인 디자인 시스템은 단순한 시각 자료가 아니라 다음을 포함해야 한다.

- 명확한 토큰 체계
- 컴포넌트 API
- 사용 규칙
- 접근성 기준
- 콘텐츠 규칙
- 반응형 원칙
- 디자인/개발 간 동기화 방식
- 확장 가능한 거버넌스

따라서 이 글의 방법은 **전문 디자이너가 만드는 완성형 디자인 시스템**이라기보다, **AI 코딩 에이전트가 UI를 더 안정적으로 구현하도록 돕는 중간 산출물 생성 전략**으로 보는 편이 정확하다.

---

## 8. 바로 적용 가능한 체크리스트

Codex에게 UI 구현을 시키기 전에 아래를 확인한다.

- [ ] 목업 이미지만 주고 바로 구현시키지 않았다.
- [ ] 색상, 타이포그래피, 간격, radius, shadow를 토큰으로 정리했다.
- [ ] 레이아웃 규칙을 데스크톱/태블릿/모바일로 나눴다.
- [ ] 컴포넌트 목록과 상태를 정의했다.
- [ ] 기존 UI 라이브러리와의 매핑을 검토했다.
- [ ] 디자인 시스템 구현을 먼저 시켰다.
- [ ] 화면 구현 전 컴포넌트 프리뷰를 리뷰했다.
- [ ] 작업 단위를 작게 나누고 중간 커밋을 했다.
- [ ] 수정한 내용은 `AGENTS.md` 또는 프로젝트 규칙 파일에 남겼다.

---

## 9. 한 줄 결론

**Codex가 좋은 UI를 만들게 하려면, 이미지 목업을 구현 지시로 쓰지 말고 디자인 시스템의 원천 자료로 써야 한다.**

가장 좋은 흐름은 다음과 같다.

```text
목업 생성
→ 디자인 시스템 추출
→ UI 프레임워크 선택
→ 토큰 구현
→ 레이아웃 구현
→ 컴포넌트 구현
→ 화면 조립
→ 리뷰 및 교정 내용 기록
```
