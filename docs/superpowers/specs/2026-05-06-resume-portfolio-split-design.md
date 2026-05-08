# Resume and Portfolio Split Design

Date: 2026-05-06
Owner: 김우승

## Purpose

이 문서는 기존 Typst 이력서와 포트폴리오를 두 가지 지원 포지션에 맞게 완전 분리형으로 재구성하기 위한 설계안이다.

대상 포지션은 다음 두 가지다.

- 풀스택 / 백엔드 포함 제품 개발자
- 모바일 리드 / Android 앱 아키텍트

기존 근거 문서는 유지한다.

- `recruit/resume/typst/resume-portfolio-evidence-notes.md`
- `recruit/resume/typst/resume-portfolio-review-framework.md`

이 설계의 목표는 두 문서가 같은 경력에서 출발하더라도, 채용 담당자와 면접관이 처음 30초 안에 각 포지션에 맞는 사람으로 인식하게 만드는 것이다.

## Chosen Direction

선택한 방향은 포지션별 완전 재구성이다.

기존 4개 Typst 파일을 유지하되, 각 버전의 상단 요약, 프로젝트 순서, 강조 역량, 포트폴리오 페이지 구성을 다르게 만든다.

- `resume-fullstack.typ`: 풀스택 이력서, 2페이지
- `portfolio-fullstack.typ`: 풀스택 포트폴리오, 6-8페이지
- `resume-mobile-lead.typ`: 모바일 리드 이력서, 2페이지
- `portfolio-mobile-lead.typ`: 모바일 리드 포트폴리오, 6-8페이지

PDF 결과물 이름도 기존 파일명을 유지한다.

- `김우승_이력서_fullstack.pdf`
- `김우승_포트폴리오_fullstack.pdf`
- `김우승_이력서_mobile_lead.pdf`
- `김우승_포트폴리오_mobile_lead.pdf`

## Shared Rules

모든 버전에 공통으로 적용할 규칙이다.

- 이력서는 각 버전 2페이지 안에 유지한다.
- 포트폴리오는 각 버전 6-8페이지 안에 유지한다.
- 기술 나열보다 문제, 판단, 결과를 우선한다.
- 수치 표현은 근거 문서와 일치시킨다.
- ReadMates는 "AI API 직접 구현"이 아니라 "AI-assisted 운영 워크플로우"로 표현한다.
- EOB 전산화와 Awair Display Mode는 "기존 담당 업무 범위 밖에서 직접 제안·기획·설계·개발·운영"한 경험으로 강조한다.
- 공개 프로젝트인 ReadMates와 GasStation은 GitHub/서비스 링크를 유지한다.
- 비공개 회사 프로젝트는 역할, 구조, 의사결정, 수치, 운영 결과로 증명한다.
- 기본 `resume.typ`과 `portfolio.typ`는 기준 문서로 유지하고, 포지션별 파일만 업데이트한다.

## Full-Stack Version

### Positioning

핵심 메시지:

> 도메인 문제를 발견하고, 직접 제안·기획·설계·개발·운영까지 연결해 실제 제품/업무 시스템으로 완성하는 풀스택 엔지니어.

강조 역량:

- 운영 중인 풀스택 서비스 설계와 배포
- 프론트엔드, BFF, 서버, DB, 배포, 테스트를 연결하는 end-to-end 구현
- 인증/권한/보안 경계 설계
- AI/OCR/LLM 기반 업무 전산화
- 업무 외 문제 발견과 제품화 제안
- 운영 검증과 릴리즈 안전성

### Resume Structure

풀스택 이력서는 2페이지 시니어형으로 구성한다.

1페이지는 "제품/업무 문제를 시스템으로 전환하는 사람"을 보여준다.

- 상단 요약: 풀스택 제품 개발자 포지셔닝
- 핵심 역량: 문제 발견, 제안/기획, 풀스택 설계, 운영 검증, AI/OCR/LLM 활용
- 대표 프로젝트 3개:
  - ReadMates
  - EOB 전산화
  - Awair Display Mode

2페이지는 경력 상세와 보조 증거를 배치한다.

- 하이케어넷 경력 상세: EOB 전산화, AI 폐렴진단, 웹/모바일/AI 프로젝트 병행
- Awair 경력 상세: Display Mode, Awair Business
- 기술 스택: Fullstack, Backend, Frontend, AI/OCR, Infra/Testing
- AI 하네스 엔지니어링: 작업 분해, 명세화, 리뷰, 테스트, 릴리즈 검증 루프

### Resume Project Order

1. ReadMates
2. EOB 전산화
3. Awair Display Mode
4. AI 폐렴진단
5. Awair Business

GasStation과 Awair Home은 풀스택 이력서에서는 비중을 낮추거나 기술 스택/보조 사례로만 다룬다.

### Portfolio Structure

풀스택 포트폴리오는 6-8페이지 안에서 "이력서 주장의 증거" 역할을 한다.

권장 구성은 7페이지다.

1. Cover / Positioning
   - 풀스택 제품 개발자 포지셔닝
   - 핵심 프로젝트 5개 요약
   - 키워드: Fullstack, BFF, Spring, React, MySQL, AI/OCR/LLM, 운영 검증
2. ReadMates: 운영형 풀스택 서비스
   - 독서모임 운영/기록/피드백 문제
   - React, Cloudflare BFF, Spring Boot, MySQL, Redis/Kafka 구조
   - 인증/권한, 피드백 문서 접근 제어, 테스트/배포/공개 저장소 안전성
3. ReadMates: 운영·검증·AI-assisted 콘텐츠
   - 멀티 클럽 지원 구조
   - Google OAuth, HttpOnly cookie, BFF secret, public-safe error contract
   - AI-assisted 하이라이트/한줄평/개인별 피드백 운영 흐름
   - 테스트 수치와 릴리즈 검증
4. EOB 전산화
   - 기존 담당 업무 범위 밖에서 직접 제안·기획·설계·개발·운영
   - 직원 4명 10일 이상 수작업, 누락/오류/히스토리 부재
   - OCR/LLM/정합성 보정/검토 흐름
   - 연 단위 처리 10초 이내, 10-15% 미청구 후보 가시화, 반려 항목 부분 수동 처리
5. Awair Display Mode
   - 기존 담당 업무 범위 밖에서 직접 제안한 신규 제품화 사례
   - B2B 고객의 대형 화면 공기질 표시 니즈
   - 기존 IoT 데이터를 실시간 Display Mode로 확장
   - 신규 수요와 기존 고객 추가 구매, 구독형 제품 라인업
6. AI 폐렴진단 임상 앱
   - 풀스택 버전에서는 보조 사례
   - 한양대 의대 협업
   - 모바일 수집·전처리·전송 설계
   - AI 제품 기반 데이터 파이프라인 경험
7. Awair Business / Summary
   - 3인 팀 리드와 앱 리빌딩 경험을 짧게 정리
   - 반복 패턴: 문제 발견, 제안/기획, 시스템 설계, 구현, 운영/검증, 제품 또는 비즈니스 성과

## Mobile Lead Version

### Positioning

핵심 메시지:

> 모바일 제품의 구조, 장시간 동작 안정성, IoT 디바이스 연동, 실시간 데이터 처리, 팀 리드를 설계부터 운영 품질까지 책임지는 앱 아키텍트.

강조 역량:

- Android 멀티모듈/Compose/Flow/MVVM
- 장시간 백그라운드 녹음과 모바일 전송 안정성
- BLE/MQTT/IoT 실시간 데이터 처리
- 3인 팀 모바일 리드
- 온보딩 관측성, Grafana, CS 감소
- 공개 포트폴리오 앱과 운영형 개인 프로젝트

### Resume Structure

모바일 리드 이력서도 2페이지 시니어형으로 구성한다.

1페이지는 "모바일 구조와 운영 안정성을 설계하는 사람"을 보여준다.

- 상단 요약: 모바일 리드 / Android 앱 아키텍트 포지셔닝
- 핵심 역량: Android 아키텍처, 장시간 백그라운드, IoT/BLE/MQTT, 실시간 스트림, 팀 리드
- 대표 프로젝트 3개:
  - GasStation
  - AI 폐렴진단
  - Awair Business

2페이지는 실무 경력과 운영 품질 증거를 배치한다.

- Awair Home: MQTT 실시간 업데이트, Grafana 온보딩 관측성, CS 90% 감소
- ReadMates: 모바일 외 풀스택 확장성 보조 증거
- 기술 스택: Android, Kotlin, Compose, Flow, BLE/MQTT, Testing, CI/CD
- 협업/리드: 해외 프리랜서, 국내 동료, iOS/server 협업, 연구실 협업

### Resume Project Order

1. GasStation
2. AI 폐렴진단
3. Awair Business
4. Awair Home
5. ReadMates

EOB 전산화와 Awair Display Mode는 모바일 리드 이력서에서는 비중을 낮추거나 제외한다. 필요하면 경력 상세에서 제품 문제 해결 경험으로 짧게만 언급한다.

### Portfolio Structure

모바일 리드 포트폴리오는 6-8페이지 안에서 모바일 구조, 장시간 안정성, 디바이스/서버 연동, 팀 리드를 증명한다.

권장 구성은 7페이지다.

1. Cover / Positioning
   - 모바일 리드 / Android 앱 아키텍트 포지셔닝
   - 핵심 프로젝트 5개 요약
   - 키워드: Android, Kotlin, Compose, Flow, Room, BLE/MQTT, Background, Observability
2. GasStation: Android Reference App
   - 17개 Gradle 모듈
   - Compose/Flow/MVVM
   - Room cache snapshot, watchlist fallback, retry policy
   - demo/prod flavor, unit/Compose/UI/benchmark 검증
   - GitHub 링크
3. AI 폐렴진단 임상 앱
   - 한양대 의대 협업
   - 전체 설계 주도
   - 48시간 연속 녹음 검증
   - 1분 단위 파일 분할, 온디바이스 전처리, 로컬 DB 상태 관리, 실패 재시도/정리 스케줄
4. Awair Business
   - 3인 팀 모바일 리드
   - Upwork 미국 프리랜서 인터뷰/고용, 6개월 협업
   - 한국 동료와 협업
   - 전체 리빌딩, BLE 주요 모듈, 메인 리스트 화면, Compose/Flow/MVVM 전환
5. Awair Home
   - 20대 이상 디바이스, 2-3초 단위 MQTT 업데이트
   - RxJava 스트림 병합/필터링/스케줄링
   - UI 성능 최적화
   - Grafana 기반 온보딩 관측성, iOS/server 협업, CS 90% 이상 감소
6. ReadMates
   - 모바일 리드 버전에서는 보조 사례
   - 모바일 개발자를 넘어 풀스택/운영까지 확장 가능한 사람이라는 증거
   - React/Spring/MySQL/BFF/배포/테스트를 짧게 정리
7. Summary / Working Principles
   - 상태와 데이터 흐름 분리
   - 실패 재시도와 로컬 저장 기본 설계
   - 장시간 백그라운드 안정성
   - 디바이스·앱·서버 관측성
   - 팀이 같이 개발 가능한 구조 만들기

## Implementation Order

실제 구현은 다음 순서로 진행한다.

1. `resume-fullstack.typ`
   - 상단 summary를 풀스택/제품 문제 해결 중심으로 재작성
   - ReadMates, EOB, Display Mode를 1페이지 핵심 프로젝트로 강화
   - GasStation 비중은 낮추거나 보조 사례로 이동
2. `resume-mobile-lead.typ`
   - 상단 summary를 모바일 아키텍트/리드 중심으로 재작성
   - GasStation, AI 폐렴진단, Awair Business를 1페이지 핵심 프로젝트로 강화
   - EOB/Display Mode 비중을 낮춤
3. `portfolio-fullstack.typ`
   - ReadMates 2페이지
   - EOB 1페이지
   - Display Mode 1페이지
   - AI 폐렴진단/Awair Business 보조 페이지
   - Summary 페이지
4. `portfolio-mobile-lead.typ`
   - GasStation 1페이지
   - AI 폐렴진단 1페이지
   - Awair Business 1페이지
   - Awair Home 1페이지
   - ReadMates 보조 페이지
   - Summary 페이지

## Verification

구현 완료 후 다음을 확인한다.

- Typst 빌드가 성공한다.
- 각 이력서는 2페이지 안에 유지된다.
- 각 포트폴리오는 6-8페이지 안에 유지된다.
- 프로젝트 순서가 이 문서의 순서와 일치한다.
- 수치 표현이 근거 문서와 일치한다.
- 풀스택 첫 페이지에서는 ReadMates, EOB, Display Mode가 먼저 읽힌다.
- 모바일 첫 페이지에서는 GasStation, AI 폐렴진단, Awair Business가 먼저 읽힌다.
- ReadMates의 AI 표현은 "AI-assisted 운영 워크플로우"로 유지된다.
- EOB와 Awair Display Mode는 업무 외 직접 제안·기획·설계·개발·운영 경험으로 표현된다.
- 기존 근거 문서의 미커밋 변경은 덮어쓰거나 되돌리지 않는다.

