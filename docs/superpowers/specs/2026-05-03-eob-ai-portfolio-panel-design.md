# EOB and AI Clinical Portfolio Panel Design

Date: 2026-05-03
Owner: 김우승

## Purpose

풀스택 포트폴리오와 모바일 리드 포트폴리오의 하이케어넷 프로젝트 2개를 더 설득력 있게 보이도록 재구성한다.

대상 프로젝트:

- EOB 전산화
- AI 폐렴진단 임상 앱

현재 문제:

- 오른쪽 패널이 단순 단계 목록처럼 보여 실제 설계/구현 역량이 약하게 보인다.
- 화면 자료가 없는 프로젝트라 비어 보이는 느낌이 있다.
- 문제, 처리 흐름, 검증, 결과가 한눈에 연결되지 않는다.
- EOB는 비즈니스/정산 임팩트가, AI 임상 앱은 모바일 제약 해결 역량이 더 드러나야 한다.

## Chosen Direction

추천안은 `파이프라인 중심 + Before/After 메시지` 하이브리드다.

오른쪽 패널은 가상의 제품 화면처럼 꾸미지 않는다. 실제 캡처가 없는 상태에서 와이어프레임 화면을 만들면 운영 증거가 아니라 장식처럼 보일 수 있기 때문이다.

대신 각 프로젝트의 오른쪽 영역을 다음 구조로 만든다.

- Before: 기존 문제가 무엇이었는가
- Pipeline: 내가 설계한 처리 흐름
- Output: 실제 업무/연구에 전달되는 결과
- Control: 오류, 실패, 제약을 어떻게 다뤘는가
- Result: 정량 또는 검증 가능한 정성 성과

## Layout Concept

기존 `evidence-panel` 단일 박스를 더 구조적인 `pipeline-card` 형식으로 바꾼다.

권장 구성:

```text
┌────────────────────────────────────────────┐
│ BEFORE                                     │
│ 기존 수기/불안정 흐름                      │
├────────────────────────────────────────────┤
│ FLOW                                       │
│ 1. Input/Collect                           │
│ 2. Extract/Filter                          │
│ 3. Structure/Control                       │
│ 4. Validate/Upload                         │
│ 5. Review/Handoff                          │
├────────────────────────────────────────────┤
│ OUTPUT                                     │
│ 정형 데이터 / 임상 데이터                  │
└────────────────────────────────────────────┘
```

시각적으로는 단계별 작은 행을 나열하되, 단순 텍스트 목록이 아니라 `Before`, `Flow`, `Output` 블록이 분리되어 보이게 한다.

## EOB Panel Design

### Message

핵심 메시지:

> 보험사와 병원별로 포맷이 다른 비정형 EOB 문서를 사람이 엑셀로 정리하던 흐름을, 청구·정산 검토 가능한 정형 데이터 흐름으로 전환했다.

### Right Panel Content

오른쪽 패널 제목:

```text
EOB 처리 설계
```

Before:

```text
보험사·병원별 PDF/스캔 EOB를 사람이 엑셀로 정리
포맷 차이와 누락 때문에 청구 후보 확인이 어려움
```

Flow:

```text
INPUT      PDF/스캔 EOB, 수기 엑셀 정리 데이터
EXTRACT    Local AI OCR + 범용 OCR Library로 문서 텍스트와 표 후보 추출
STRUCTURE  LLM으로 payer, patient, DOS, CPT, paid/denied amount 필드 매핑
VALIDATE   병원별 규칙과 금액 정합성 보정 후 누락/오류 후보 분리
REVIEW     검토 테이블, 오류 후보, 원문 근거를 함께 표시
```

Output:

```text
청구·정산 검토 가능한 정형 데이터
회수 후보 목록
```

### Left Project Copy

Problem:

```text
보험사와 병원별 EOB 문서 포맷이 달라 사람이 엑셀로 정리하던 청구 후보 데이터가 누락
```

Role:

```text
문제 제기, 요구사항 정리, OCR/LLM 파이프라인, 프론트엔드/서버 구현
```

Result:

```text
병원당 연 10-15% 수준으로 발생하던 미청구 EOB를 청구 가능한 정형 데이터 흐름으로 전환
```

Bullets:

- 병원·보험사별 포맷이 제각각인 비정형 EOB를 사람이 엑셀로 정리하던 한계를 파악하고 미정산 금액 문제를 가시화
- 도메인 담당자와 실제 청구 검토 흐름을 확인해 문서 인식 결과가 바로 업무에 쓰일 수 있는 필드 구조로 정리
- Local AI OCR, 범용 OCR Library, LLM 조합으로 문서 인식, 필드 추출, 정합성 보정 파이프라인 구축
- 보험사·병원별 EOB 문서를 청구 가능한 정형 데이터로 변환하고, 검토 대상과 오류 후보를 분리하는 처리 흐름 구현

## AI Clinical Panel Design

### Message

핵심 메시지:

> 임상 연구에서 필요한 24시간 기침 음성 수집을 모바일 제약 안에서 안정적으로 수행하고, 연구실 AI 모델 검증에 사용할 데이터로 전달하는 수집·전처리·전송 파이프라인을 만들었다.

### Right Panel Content

오른쪽 패널 제목:

```text
모바일 수집 설계
```

Before:

```text
24시간 기침 음성 수집이 필요하지만 모바일 환경은 앱 종료, 배터리, 저장공간, 네트워크 제약이 큼
```

Flow:

```text
COLLECT   24시간 백그라운드 녹음, 세션 단위 파일 분할, 수집 상태 유지
FILTER    온디바이스 오디오 정제, 무음/잡음 구간 제외, 기침 후보 선별
CONTROL   배터리, 저장공간, 네트워크 상태에 따라 수집·전송 전략 조정
UPLOAD    서버 업로드 큐와 재시도 흐름으로 장시간 수집 데이터 전송
MONITOR   수집 상태, 업로드 상태, 실패 원인을 확인할 수 있도록 처리 단계 분리
HANDOFF   연구실 AI 모델 학습/검증에 사용할 임상 음성 데이터로 전달
```

Output:

```text
임상 연구용 기침 음성 데이터
전처리된 서버 업로드 데이터
AI 모델 검증용 데이터셋
```

### Left Project Copy

Problem:

```text
임상 연구용 기침 음성을 24시간 수집하고 모바일 제약 안에서 안정적으로 전송해야 함
```

Role:

```text
Android 수집 앱, 온디바이스 필터링, 서버 업로드 파이프라인 설계·구현
```

Result:

```text
24시간 기침 음성 수집, 온디바이스 정제/필터링, 서버 전송 파이프라인으로 임상 2차 프로젝트 완료
```

Bullets:

- 임상 연구 요구사항 분석부터 24시간 기침 음성 수집, 온디바이스 정제/필터링, 서버 전송 파이프라인 설계·구현
- 진단 AI 모델은 연구실이 담당하고, 모바일 수집·전처리·전송 구간을 단독 담당
- 장시간 백그라운드 녹음 중 앱 종료, 네트워크 불안정, 저장공간 부족 상황을 고려해 수집 상태와 재전송 흐름을 설계
- 배터리, 저장공간, 네트워크 제약 하에서 장시간 녹음이 가능한 모바일 수집 전략 설계

## Apply To Both Portfolio Versions

동일한 하이케어넷 프로젝트 패널을 다음 두 파일에 반영한다.

- `recruit/resume/typst/portfolio-fullstack.typ`
- `recruit/resume/typst/portfolio-mobile-lead.typ`

두 포트폴리오 모두 EOB와 AI 임상 앱을 같은 수준으로 보여준다. 다만 문서 전체 순서는 유지한다.

Full-stack portfolio order:

1. ReadMates
2. 주유주유소
3. EOB 전산화
4. AI 폐렴진단 임상 앱
5. Awair Business
6. Awair Home

Mobile lead portfolio order:

1. 주유주유소
2. ReadMates
3. EOB 전산화
4. AI 폐렴진단 임상 앱
5. Awair Home
6. Awair Business

## Implementation Constraints

- 각 포트폴리오는 A4 3페이지를 유지한다.
- 새 패널은 캡처 화면처럼 보이게 꾸미지 않는다.
- 실제 운영 화면이 없는 프로젝트이므로 가상의 UI 테이블, 버튼, 대시보드는 만들지 않는다.
- 패널은 “시스템/업무 흐름을 설명하는 증거 자료”처럼 보여야 한다.
- 텍스트가 많아지면 bullet을 줄이고, 패널의 단계는 유지한다.

## Verification Plan

구현 후 다음을 확인한다.

- `./build.sh` 성공
- `김우승_포트폴리오_fullstack.pdf` 3페이지 유지
- `김우승_포트폴리오_mobile_lead.pdf` 3페이지 유지
- 두 PDF 모두 `EOB 처리 설계`, `모바일 수집 설계` 또는 동등한 제목 포함
- 두 PDF 모두 `BEFORE`, `FLOW`, `OUTPUT` 구조가 시각적으로 구분됨
- `pdftotext`에서 `EXTRACT`, `STRUCTURE`, `REVIEW`, `CONTROL`, `MONITOR`, `HANDOFF` 확인
- 렌더링 PNG에서 오른쪽 패널이 비어 보이지 않고 텍스트가 겹치지 않음
