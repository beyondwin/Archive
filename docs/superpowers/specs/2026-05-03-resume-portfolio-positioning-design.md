# Resume and Portfolio Positioning Design

Date: 2026-05-03
Owner: 김우승

## Purpose

이 문서는 기존 Typst 이력서와 포트폴리오를 두 가지 지원 포지션에 맞게 재구성하기 위한 문구/구조 설계안이다.

지원동기는 회사별로 별도 작성한다. 본 문서의 목표는 회사와 무관하게 재사용 가능한 핵심 경험, 역량, 프로젝트 증거를 정리하는 것이다.

대상 포지션은 다음 두 가지다.

- 풀스택 개발자
- 모바일 리드 / 앱 아키텍트

## Shared Writing Principles

모든 프로젝트 설명은 단순 경험 나열이 아니라 문제, 역할, 해결, 결과가 드러나야 한다.

프로젝트별 서술 기준:

- Problem: 어떤 비효율, 제약, 비즈니스 문제가 있었는가
- Role: 내가 어디까지 책임졌는가
- Solution: 어떤 구조, 기술, 프로세스로 풀었는가
- Result: 실제 결과가 무엇인가
- Proof: 숫자 또는 검증 가능한 정성 증거

정량 수치는 확실한 것만 사용한다.

- 13년+ 경력
- EOB 미청구 건 병원당 연 10-15% 수준
- AI 폐렴진단 앱 24시간 음성 수집
- App / IoT Device / Server 3지점 온보딩 관측

정량화가 어려운 성과는 과장하지 않고 검증 가능한 정성 성과로 표현한다.

- 운영 서비스 배포
- 공개 저장소와 문서화
- 인증/권한/공개 범위 회귀 점검
- public release scan
- Testcontainers 기반 Redis/Kafka/MySQL 검증
- 연구실 협업 임상 2차 완료
- 릴리스 자동화와 운영 지표 구성

## ReadMates Update Basis

현재 Typst 문서는 ReadMates 최신 저장소보다 이전 상태다. 이력서와 포트폴리오에는 최신 저장소 기준의 기술 요소를 반영한다.

ReadMates 최신 핵심 스택:

- React 19
- React Router 7
- TypeScript
- Vite
- Cloudflare Pages Functions
- Kotlin
- Spring Boot
- Spring Security
- MySQL
- Flyway
- Redis
- Redpanda/Kafka
- Micrometer/Prometheus
- Testcontainers
- Playwright

ReadMates를 단순 개인 프로젝트가 아니라 운영형 풀스택 제품으로 정의한다.

권장 정의:

> 운영 중인 멤버십 독서모임 서비스를 멀티 클럽 구조로 확장하며, 공개 사이트, 멤버 화면, 호스트 운영 도구, 알림, 권한, 배포, 운영 검증까지 직접 설계한 풀스택 제품.

Redis/Kafka 표현은 정확하게 쓴다.

- Redis: session/cache/rate-limit 보조 계층
- Redpanda/Kafka: MySQL transactional outbox 기반 알림 relay/consumer 파이프라인

과장하지 말아야 할 표현:

- 대규모 트래픽 처리
- 고가용성 분산 시스템 운영
- 실시간 대용량 데이터 파이프라인

## Personal Development Harness

"개인 하네스"는 이력서에서 낯설 수 있으므로 의미를 풀어서 쓴다.

권장 표현:

> AI 기반 개인 개발 하네스를 구축해 요구사항 정리, 스펙 작성, 구현 계획, 코드 리뷰 관점 점검, 테스트 케이스 도출, 회귀 점검, 릴리즈 검증을 반복 가능한 개발 루틴으로 운영.

짧은 표현:

> AI 기반 개인 개발 하네스로 요구사항 정리 -> 스펙/계획 -> 구현 -> 테스트/회귀 점검 -> 릴리즈 검증 흐름을 반복 가능한 루틴으로 운영.

이 문구는 단순히 AI를 "쓴다"가 아니라, 업무 방식과 품질 관리 체계를 직접 만들었다는 증거로 배치한다.

## Full-Stack Version

### Positioning

핵심 메시지:

> 문제를 제품 흐름으로 정의하고, 프론트엔드, 백엔드, 인증/권한, 배포, 테스트, 운영 검증까지 끝까지 구현하는 풀스택 개발자.

강조할 역량:

- 제품 문제 구조화
- 프론트엔드와 서버를 연결한 End-to-End 구현
- 인증/권한/보안 경계 설계
- Redis/Kafka 기반 운영 기능 확장
- 테스트와 릴리즈 검증 루틴
- AI 기반 개발 하네스 활용

### Resume Summary Draft

13년+ 경력의 풀스택 엔지니어입니다. Android 네이티브에서 시작해 React, React Router, TypeScript, Kotlin/Spring Boot, Cloudflare Pages Functions 기반 BFF까지 확장하며 모바일, 웹, 서버를 하나의 제품 흐름으로 연결해왔습니다.

강점은 현장의 비효율을 요구사항과 데이터 흐름으로 구조화하고, 인증/권한, 배포, 테스트, 운영 검증까지 실제 서비스 가능한 형태로 구현하는 실행력입니다. 하이케어넷에서는 보험사와 병원별 비정형 EOB 문서를 청구 가능한 정형 데이터로 전환하는 AI OCR/LLM 파이프라인을 제안, 기획, 구현했고, ReadMates에서는 멀티 클럽 멤버십 서비스의 공개 사이트, 멤버 화면, 호스트 운영 도구, 인증/권한, Redis cache/rate-limit, Kafka 알림 파이프라인, 운영 지표와 릴리즈 검증까지 직접 설계, 구현했습니다.

AI는 제품 기능 구현과 개발 업무 자동화 양쪽에 활용합니다. OCR/LLM 기반 문서 처리, 임상 데이터 수집 앱처럼 AI가 포함된 제품을 직접 구현했고, AI 기반 개인 개발 하네스로 요구사항 정리, 스펙 작성, 구현 계획, 코드 리뷰 관점 점검, 테스트/회귀 점검, 릴리즈 검증을 반복 가능한 개발 루틴으로 운영합니다.

### Portfolio Order

1. ReadMates
2. 주유주유소
3. EOB 전산화
4. AI 폐렴진단 임상 앱
5. Awair Business
6. Awair Home

### ReadMates Bullets

- 멀티 클럽 기반 멤버십 독서모임 서비스로 확장하며 클럽별 공개 사이트, 멤버 화면, 호스트 운영 화면, 알림함을 하나의 제품 흐름으로 설계
- Google OAuth, HttpOnly 공유 session cookie, Cloudflare Pages Functions BFF, BFF secret 검증으로 브라우저와 Spring API 사이의 신뢰 경계를 분리
- 게스트, 둘러보기 멤버, 정식 멤버, 호스트, 플랫폼 관리자 권한을 club-scoped URL과 서버 권한 검증으로 분리
- MySQL/Flyway를 source of truth로 두고 Redis 기반 cache/rate-limit, Kafka transactional outbox 기반 이메일/in-app 알림 파이프라인을 구성
- Micrometer/Prometheus 운영 지표, Testcontainers 기반 Redis/Kafka/MySQL 테스트, Playwright E2E로 운영 전 회귀를 점검
- 공개 저장소 배포를 전제로 secret, private path, DB/BFF/OAuth token 형태를 검사하는 public release scan 스크립트 구축

### ReadMates Result

> 멀티 클럽 공개 사이트, 멤버 세션 준비, 호스트 운영, 알림, 피드백 문서 접근 제어까지 포함한 운영형 풀스택 서비스를 배포.

## Mobile Lead / App Architect Version

### Positioning

핵심 메시지:

> 모바일 제품의 구조, 품질, 릴리스, 디바이스/서버 연동을 책임지는 모바일 리드 겸 앱 아키텍트.

강조할 역량:

- Android 아키텍처 설계와 전환
- Compose/Flow/MVVM/Clean Architecture
- BLE/MQTT/IoT 디바이스 연동
- 서버/인증/알림/운영 도구를 이해하는 모바일 리드
- 연구/제품/서버 이해관계자 협업
- 장시간 수집, 배터리, 저장공간, 네트워크 제약 해결

### Resume Summary Draft

13년+ 경력의 모바일 리드 겸 앱 아키텍트입니다. Android 네이티브 개발에서 출발해 IoT 디바이스 연동, BLE/MQTT, React Native, Kotlin/Spring Boot 기반 서버 연동까지 모바일 제품의 구조와 운영 품질을 함께 설계해왔습니다.

강점은 복잡한 사용자 흐름과 디바이스/서버 연동 문제를 모바일 아키텍처로 정리하고, 릴리스 가능한 품질까지 끌고 가는 실행력입니다. Awair에서는 B2B/B2C 공기질 모니터링 제품군의 앱 구조 개선, SSO, Feature Flag, CI/CD, 온보딩 관측 체계를 주도했고, 하이케어넷에서는 24시간 기침 음성 수집과 전처리가 필요한 AI 폐렴진단 임상 앱을 설계, 구현했습니다.

협업 방식은 문제를 먼저 구조화하고, 제품, 서버, 연구, 운영 이해관계자가 같은 기준으로 판단할 수 있게 만드는 데 초점을 둡니다. AI 기반 개인 개발 하네스로 요구사항 정리, 설계 검토, 코드 작성, 테스트/회귀 점검을 반복 가능한 개발 루틴으로 운영합니다.

### Portfolio Order

1. 주유주유소
2. ReadMates
3. AI 폐렴진단 임상 앱
4. Awair Home
5. Awair Business

### Project Emphasis

주유주유소:

- 최신 Android 구조, Compose/Flow/MVVM, 멀티모듈 아키텍처
- 위치 기반 탐색, 공공 API 연동, 내비 앱 전환까지 모바일 사용자 흐름 완성

ReadMates:

- 모바일 웹 사용 흐름을 기준으로 멤버 세션 준비, RSVP, 질문/서평 작성, 알림, 피드백 문서 열람을 설계
- 서버 권한 검증과 운영 도구까지 연결해 모바일 경험이 제품 전체 구조와 충돌하지 않도록 구현

AI 폐렴진단 임상 앱:

- 연구 요구사항 분석
- 24시간 기침 음성 수집
- 온디바이스 정제/필터링
- 배터리, 저장공간, 네트워크 제약 하의 장시간 수집 전략

Awair Home:

- BLE/MQTT 기반 IoT 디바이스 제어
- 사용자 온보딩
- 스마트홈 연동

Awair Business:

- MVP/RxJava에서 MVVM/Compose/Flow로 전환
- SSO, Feature Flag, CI/CD
- App / Device / Server 3지점 온보딩 이벤트 표준화와 Grafana 기반 페인포인트 추적

## Files to Create During Implementation

기존 `resume.typ`과 `portfolio.typ`는 현재 기준 문서로 유지한다. 새 파일을 만들어 버전별 문서를 관리한다.

- `resume-fullstack.typ`
- `resume-mobile-lead.typ`
- `portfolio-fullstack.typ`
- `portfolio-mobile-lead.typ`

빌드 결과물은 다음 이름으로 생성한다.

- `김우승_이력서_fullstack.pdf`
- `김우승_이력서_mobile_lead.pdf`
- `김우승_포트폴리오_fullstack.pdf`
- `김우승_포트폴리오_mobile_lead.pdf`

## Implementation Constraints

- 전체 PDF 페이지 수는 각 문서별 3페이지를 우선 목표로 한다.
- 문구가 길어지면 글자 크기를 먼저 줄이지 말고, 우선순위가 낮은 bullet을 줄인다.
- ReadMates 최신 기술 스택을 반영하되, 실제 운영 규모를 과장하지 않는다.
- 지원동기 문구는 본 문서에 고정하지 않는다.
- 회사별 지원동기는 별도 커버레터 또는 지원서 답변에서 작성한다.

## Verification Plan

구현 후 다음을 확인한다.

- Typst 빌드 성공
- 이력서/포트폴리오 각 3페이지 유지
- ReadMates 스택에 Redis, Redpanda/Kafka, Micrometer/Prometheus, Testcontainers 반영
- 개인 개발 하네스 문구 반영
- 풀스택 버전과 모바일 리드 버전의 프로젝트 순서가 서로 다름
- 각 프로젝트가 Problem / Role / Solution / Result 관점으로 읽힘
- PDF 렌더링에서 문구가 겹치거나 지나치게 붙어 보이지 않음
