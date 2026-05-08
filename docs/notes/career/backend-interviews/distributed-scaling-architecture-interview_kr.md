# 분산처리·서버 확장 전략과 아키텍처 개선: 실제 사례와 면접 질문/답변

## 목차

1. [전체 접근 원칙](#1-전체-접근-원칙)
2. [Load Balancer + 서버 수평 확장](#2-load-balancer--서버-수평-확장)
3. [DB 읽기 병목 + Read Replica](#3-db-읽기-병목--read-replica)
4. [Cache 적용](#4-cache-적용)
5. [Cache Redistribution](#5-cache-redistribution)
6. [비동기 아키텍처 + Queue](#6-비동기-아키텍처--queue)
7. [Ack + 중복 처리](#7-ack--중복-처리)
8. [DLQ / DLX](#8-dlq--dlx)
9. [큐의 팬아웃](#9-큐의-팬아웃)
10. [Kafka vs MQ 선택](#10-kafka-vs-mq-선택)
11. [Insert는 NoSQL](#11-insert는-nosql)
12. [OLTP / OLAP 분리](#12-oltp--olap-분리)
13. [파티셔닝](#13-파티셔닝)
14. [수직 파티셔닝](#14-수직-파티셔닝)
15. [샤딩](#15-샤딩)
16. [월 1억 건 데이터 처리](#16-월-1억-건-데이터-처리)
17. [Multi-read Replication](#17-multi-read-replication)
18. [Multi-Master Multi-Slave](#18-multi-master-multi-slave)
19. [인메모리 데이터 그리드](#19-인메모리-데이터-그리드)
20. [페더레이션](#20-페더레이션)
21. [Abstraction of Concern](#21-abstraction-of-concern)
22. [Separation of Concern](#22-separation-of-concern)
23. [외부 API 장애 격리](#23-외부-api-장애-격리)
24. [실전 면접 종합 질문](#24-실전-면접-종합-질문)
25. [최종 압축 정리](#25-최종-압축-정리)

---

# 1. 전체 접근 원칙

분산처리와 서버 확장은 기술을 먼저 고르는 문제가 아니다.

시니어 백엔드 개발자는 보통 다음 순서로 접근한다.

```text
1. 현재 병목을 측정한다.
2. 병목이 API 서버인지, DB인지, 외부 API인지, 네트워크인지 구분한다.
3. 가장 단순하고 운영 비용이 낮은 해결책부터 적용한다.
4. 개선 전후 지표를 비교한다.
5. 복잡한 분산 구조는 필요성이 명확할 때만 도입한다.
```

## 핵심 지표

| 영역 | 주요 지표 | 의미 |
|---|---|---|
| API | RPS, TPS, p95/p99 latency | 요청 처리량과 사용자 체감 속도 |
| 서버 | CPU, Memory, GC, Thread pool | 애플리케이션 병목 확인 |
| DB | Slow query, Lock wait, Connection count | DB 병목 확인 |
| Cache | Hit ratio, Eviction, Redis latency | 캐시 효과와 안정성 확인 |
| Queue | Lag, Retry count, DLQ count | 비동기 처리 적체 확인 |
| 장애 | Error rate, Timeout rate | 안정성 확인 |
| 배포 | Rollback 횟수, 장애 시간 | 운영 안정성 확인 |

## 우선순위

| 우선순위 | 전략 | 목적 | 복잡도 |
|---:|---|---|---|
| 1 | 관측 가능성 확보 | 병목 확인 | 낮음 |
| 2 | 코드/쿼리 최적화 | 불필요한 낭비 제거 | 낮음 |
| 3 | Load Balancer + 서버 수평 확장 | API 처리량 증가 | 낮음 |
| 4 | Cache | 반복 조회 부하 감소 | 중간 |
| 5 | DB 리플리케이션 | 읽기 부하 분산 | 중간 |
| 6 | 비동기 아키텍처 | 느린 후처리 분리 | 중간 |
| 7 | NoSQL / 로그 저장소 분리 | 대량 insert 처리 | 중간~높음 |
| 8 | OLTP / OLAP 분리 | 운영 DB 보호 | 높음 |
| 9 | 파티셔닝 | 대형 테이블 관리 | 높음 |
| 10 | 샤딩 | 단일 DB 한계 극복 | 매우 높음 |
| 11 | 멀티마스터 / 페더레이션 | 초대규모·글로벌 분산 | 매우 높음 |

---

# 2. Load Balancer + 서버 수평 확장

## 실제 사례

쇼핑몰 서비스에서 이벤트 오픈 시간인 오전 10시에 트래픽이 몰렸다.

기존 구조는 다음과 같았다.

```text
Client
  ↓
API Server 1대
  ↓
DB
```

평소에는 문제가 없었지만 이벤트 시간에 다음 문제가 발생했다.

```text
- API 응답속도 p95: 300ms → 4초
- 일부 요청 timeout 발생
- API 서버 CPU 95% 이상
- DB CPU는 40% 수준으로 여유 있음
```

즉, 병목은 DB가 아니라 API 서버였다.

## 해결

API 서버를 stateless하게 만들고 Load Balancer 뒤에 여러 대 배치했다.

```text
Client
  ↓
Load Balancer
  ↓
API Server 1
API Server 2
API Server 3
API Server 4
  ↓
DB
```

세션과 파일 저장은 서버 로컬에 두지 않았다.

```text
로그인 세션 → Redis 또는 Session Store
파일 업로드 → S3 같은 Object Storage
서버 로컬 상태 → 제거
```

## 왜 이 순서인가?

DB가 병목이 아닌데 DB 리플리케이션이나 샤딩을 먼저 할 필요가 없다.  
API 서버 CPU가 병목이면 가장 먼저 할 일은 서버 수평 확장이다.

## 면접 질문 1

### Q. 트래픽이 증가했을 때 가장 먼저 서버를 늘리면 되나요?

**답변 예시**

무조건 서버를 늘리기보다는 먼저 병목을 확인해야 합니다.

API 서버 CPU가 높은지, DB가 느린지, 외부 API가 느린지, 네트워크 문제인지 확인해야 합니다.

예를 들어 API 서버 CPU가 90% 이상이고 DB는 여유가 있다면 Load Balancer 뒤에 API 서버를 수평 확장하는 게 효과적입니다.  
반대로 DB 쿼리가 느린 상황에서 API 서버만 늘리면 DB connection만 더 많이 몰려서 오히려 장애가 커질 수 있습니다.

## 면접 질문 2

### Q. 서버 수평 확장을 하려면 어떤 전제가 필요한가요?

**답변 예시**

가장 중요한 전제는 API 서버가 stateless해야 한다는 점입니다.

서버 메모리에 세션을 저장하거나, 서버 로컬 디스크에 업로드 파일을 저장하면 특정 서버에 상태가 묶이기 때문에 수평 확장이 어렵습니다.

그래서 세션은 Redis나 외부 Session Store에 저장하고, 파일은 S3 같은 Object Storage에 저장하고, 서버는 요청을 받아 처리하는 역할만 하도록 만들어야 합니다.

---

# 3. DB 읽기 병목 + Read Replica

## 실제 사례

커뮤니티 서비스에서 메인 피드 조회가 느려졌다.

```text
- 전체 트래픽 중 조회 API가 85%
- 게시글 작성보다 목록/상세 조회가 압도적으로 많음
- DB CPU 80~90%
- SELECT 쿼리가 대부분 부하를 차지
- INSERT/UPDATE 부하는 크지 않음
```

처음에는 API 서버를 늘렸지만 효과가 없었다.  
오히려 DB connection이 늘어나면서 DB 부하가 더 커졌다.

## 해결

Primary DB는 쓰기 전용에 가깝게 두고, 조회는 Read Replica로 분산했다.

```text
쓰기 요청
API Server → Primary DB

읽기 요청
API Server → Read Replica 1
API Server → Read Replica 2
API Server → Read Replica 3
```

## 추가 대응

모든 조회를 Replica로 보내지는 않았다.

```text
일반 게시글 목록 조회 → Replica
게시글 상세 조회 → Replica
내가 방금 작성한 글 조회 → Primary
결제/주문 직후 상태 조회 → Primary
```

Replica에는 복제 지연, 즉 replication lag이 있을 수 있기 때문이다.

## 면접 질문 1

### Q. DB 리플리케이션을 하면 어떤 문제를 해결할 수 있나요?

**답변 예시**

DB 리플리케이션은 주로 읽기 부하를 분산하기 위해 사용합니다.

쓰기 요청은 Primary DB로 보내고, 읽기 요청은 여러 Read Replica로 분산해서 Primary DB의 부하를 줄일 수 있습니다.

다만 복제 지연이 있기 때문에 방금 쓴 데이터를 바로 읽어야 하는 경우에는 Primary에서 읽도록 처리해야 합니다.

## 면접 질문 2

### Q. Read Replica를 쓰면 항상 정합성 문제가 생기나요?

**답변 예시**

항상 문제라고 보기는 어렵고, 서비스 요구사항에 따라 다릅니다.

예를 들어 상품 목록, 게시글 목록, 통계성 조회는 수 초 정도 지연되어도 괜찮은 경우가 많습니다.  
하지만 결제 직후 주문 상태, 계좌 잔액, 재고 차감 결과처럼 강한 정합성이 필요한 데이터는 Replica가 아니라 Primary에서 읽는 것이 안전합니다.

---

# 4. Cache 적용

## 실제 사례

음식 배달 서비스에서 가게 상세 페이지 조회가 너무 많았다.

가게 상세 페이지는 다음 데이터를 조합해서 보여줬다.

```text
- 가게 기본 정보
- 메뉴 목록
- 리뷰 요약
- 영업 시간
- 배달 가능 지역
```

이 데이터는 자주 조회되지만 자주 바뀌지는 않았다.

```text
- 같은 가게 상세 페이지를 수천 명이 반복 조회
- DB SELECT 부하 증가
- API p95 latency 1.2초
- DB CPU 85%
```

## 해결

Redis Cache를 적용했다.

```text
Client
  ↓
API Server
  ↓
Redis Cache
  ↓ miss
DB
```

캐시 key는 다음처럼 설계했다.

```text
store:detail:{storeId}
```

TTL은 5분으로 설정했고, 가게 정보가 변경되면 해당 key를 삭제했다.

```text
가게 정보 수정
  ↓
DB 업데이트
  ↓
Redis key 삭제
```

## 결과

```text
Cache hit ratio: 92%
DB CPU: 85% → 35%
p95 latency: 1.2초 → 180ms
```

## 면접 질문 1

### Q. 어떤 데이터를 캐시하면 좋나요?

**답변 예시**

자주 읽히고, 자주 바뀌지 않으며, 조회 비용이 큰 데이터를 캐시하면 효과가 큽니다.

예를 들어 상품 상세, 카테고리 목록, 가게 상세, 권한 정보, 설정값, 인기 게시글 같은 데이터입니다.

반대로 잔액, 재고, 결제 상태처럼 강한 정합성이 필요한 데이터는 캐시를 신중하게 적용해야 합니다.

## 면접 질문 2

### Q. 캐시를 적용하면 어떤 문제가 생길 수 있나요?

**답변 예시**

대표적으로 stale data 문제가 생길 수 있습니다.

DB는 수정됐는데 캐시에는 이전 값이 남아 있어서 사용자에게 오래된 데이터가 보일 수 있습니다.

이를 해결하기 위해 TTL을 두거나, 데이터 변경 시 캐시를 무효화하는 전략을 사용합니다.

또한 캐시가 동시에 만료되면 DB로 트래픽이 몰리는 cache stampede가 발생할 수 있으므로 TTL에 random jitter를 주거나 lock을 사용해 한 요청만 DB를 조회하게 만들 수 있습니다.

---

# 5. Cache Redistribution

## 실제 사례

Redis Cluster를 사용하던 서비스에서 캐시 노드를 3대에서 6대로 늘렸다.

```text
기존:
Redis Node A
Redis Node B
Redis Node C

확장 후:
Redis Node A
Redis Node B
Redis Node C
Redis Node D
Redis Node E
Redis Node F
```

노드를 추가하면서 일부 key slot이 새 노드로 이동했다.

이때 순간적으로 다음 문제가 발생했다.

```text
- cache miss 증가
- Redis latency 증가
- 일부 API 응답속도 증가
- DB 트래픽 일시적 증가
```

## 해결

캐시 재분배 시점에 다음 조치를 했다.

```text
1. 트래픽이 적은 시간에 resharding 수행
2. cache miss 증가를 예상하고 DB connection pool 모니터링
3. hot key 별도 관리
4. TTL을 분산시켜 대량 만료 방지
5. Redis latency와 DB CPU를 함께 모니터링
```

## 면접 질문

### Q. Redis Cluster에서 노드를 추가하면 어떤 문제가 발생할 수 있나요?

**답변 예시**

Redis Cluster는 key slot을 기준으로 데이터를 분산합니다.  
노드를 추가하면 일부 slot이 새 노드로 이동하면서 cache redistribution이 발생합니다.

이 과정에서 일시적으로 cache miss가 증가하거나 Redis latency가 증가할 수 있고, miss가 늘어나면 DB 트래픽도 증가할 수 있습니다.

그래서 트래픽이 낮은 시간에 진행하고, DB 부하와 Redis latency를 함께 모니터링해야 합니다.

---

# 6. 비동기 아키텍처 + Queue

## 실제 사례

회원가입 API가 느렸다.

회원가입 요청 하나에서 다음 작업을 모두 동기로 처리하고 있었다.

```text
1. 회원 정보 저장
2. 가입 축하 이메일 발송
3. SMS 인증 기록 저장
4. 마케팅 CRM 전송
5. 쿠폰 발급
6. 가입 이벤트 로그 저장
```

문제는 이메일 발송 서버와 CRM API가 종종 느려진다는 점이었다.

```text
회원가입 p95 latency: 2.5초
외부 CRM API timeout 발생
외부 API 장애 시 회원가입도 실패
```

## 해결

핵심 트랜잭션과 부가 작업을 분리했다.

동기 처리:

```text
회원 정보 저장
필수 인증 상태 저장
```

비동기 처리:

```text
가입 축하 이메일
쿠폰 발급
CRM 전송
이벤트 로그 저장
```

구조:

```text
Client
  ↓
API Server
  ↓
User DB 저장
  ↓
Queue에 UserRegistered 이벤트 발행
  ↓
Worker들이 후속 처리
```

## 결과

```text
회원가입 p95 latency: 2.5초 → 250ms
외부 CRM 장애가 회원가입 API에 직접 영향 주지 않음
실패한 메시지는 DLQ로 이동
```

## 면접 질문 1

### Q. 언제 비동기 처리를 적용해야 하나요?

**답변 예시**

사용자 요청의 핵심 결과와 직접 관련 없는 작업이거나, 외부 시스템 때문에 지연될 수 있는 작업은 비동기로 분리하는 것이 좋습니다.

예를 들어 이메일 발송, 푸시 알림, CRM 전송, 분석 로그 저장, 이미지 리사이징 같은 작업입니다.

반대로 결제 승인, 주문 생성, 재고 차감처럼 사용자의 요청 결과와 직접 연결되고 정합성이 중요한 작업은 신중하게 동기 처리해야 합니다.

## 면접 질문 2

### Q. Queue를 쓰면 장애가 없어지나요?

**답변 예시**

장애가 없어지는 것은 아닙니다.  
Queue는 장애를 격리하고 완충하는 역할을 합니다.

예를 들어 이메일 서버가 장애가 나도 회원가입 API는 성공시킬 수 있고, 이메일 발송 메시지는 Queue에 남겨두었다가 나중에 재처리할 수 있습니다.

하지만 Queue를 쓰면 중복 처리, 메시지 순서, DLQ, 재시도 정책, consumer lag 같은 새로운 운영 문제가 생기기 때문에 이를 함께 설계해야 합니다.

---

# 7. Ack + 중복 처리

## 실제 사례

주문 완료 후 포인트를 지급하는 consumer가 있었다.

```text
OrderCompleted Event
  ↓
PointConsumer
  ↓
포인트 지급
```

어느 날 consumer가 포인트 지급은 성공했지만 Ack를 보내기 전에 서버가 죽었다.

```text
1. 메시지 수신
2. 포인트 지급 성공
3. Ack 보내기 전 consumer 장애
4. Broker는 처리 실패로 판단
5. 메시지 재전달
6. 포인트가 한 번 더 지급됨
```

## 문제

메시지 시스템은 보통 at-least-once 처리를 전제로 한다.  
즉, 메시지는 최소 한 번 전달되며, 상황에 따라 두 번 이상 처리될 수 있다.

## 해결

event_id 기반 idempotency 처리를 추가했다.

```text
OrderCompleted event_id = evt_123

PointConsumer 처리 전:
processed_event 테이블에서 evt_123 확인

없으면:
포인트 지급
processed_event에 evt_123 저장

있으면:
이미 처리한 이벤트이므로 skip
```

## 면접 질문 1

### Q. Ack는 무엇이고 왜 중요한가요?

**답변 예시**

Ack는 consumer가 메시지를 정상적으로 처리했다는 것을 broker에게 알려주는 신호입니다.

consumer가 메시지를 처리한 후 Ack를 보내면 broker는 해당 메시지를 완료 처리합니다.  
반대로 Ack를 보내지 못하면 broker는 메시지가 처리되지 않았다고 보고 재전달할 수 있습니다.

그래서 Ack는 메시지 유실 방지에 중요하지만, 같은 메시지가 중복 처리될 수 있기 때문에 consumer는 idempotent하게 설계해야 합니다.

## 면접 질문 2

### Q. 메시지 중복 처리는 어떻게 방지하나요?

**답변 예시**

메시지가 중복 전달될 수 있다는 전제로 설계합니다.

각 이벤트에 event_id를 부여하고, consumer가 처리 전에 해당 event_id를 이미 처리했는지 확인합니다.  
이미 처리한 event_id면 skip하고, 처음 보는 event_id면 비즈니스 로직을 실행한 뒤 처리 이력을 저장합니다.

특히 포인트 지급, 쿠폰 발급, 결제 후처리처럼 중복 처리되면 문제가 큰 작업에는 idempotency key가 필수입니다.

---

# 8. DLQ / DLX

## 실제 사례

알림 발송 consumer가 있었다.

```text
Notification Queue
  ↓
Notification Consumer
  ↓
Push 발송
```

그런데 특정 메시지 payload에 잘못된 userId가 들어왔다.

```json
{
  "userId": null,
  "message": "쿠폰이 발급되었습니다"
}
```

consumer는 이 메시지를 처리할 수 없어서 계속 실패했다.

문제는 실패 메시지가 계속 재시도되면서 정상 메시지 처리까지 지연시키는 것이었다.

## 해결

재시도 횟수를 3회로 제한하고, 계속 실패하면 DLQ로 보냈다.

```text
Notification Queue
  ↓ 실패 1회
Retry
  ↓ 실패 2회
Retry
  ↓ 실패 3회
DLX
  ↓
Notification DLQ
```

DLQ에는 다음 정보를 남겼다.

```text
- 원본 payload
- 실패 사유
- 실패 시간
- retry count
- stack trace
```

## 면접 질문 1

### Q. DLQ는 왜 필요한가요?

**답변 예시**

DLQ는 정상 처리할 수 없는 메시지를 별도로 격리하기 위해 필요합니다.

잘못된 payload나 존재하지 않는 사용자 ID처럼 재시도해도 성공할 가능성이 낮은 메시지를 계속 재시도하면 consumer 리소스를 낭비하고 정상 메시지 처리까지 지연시킬 수 있습니다.

그래서 일정 횟수 이상 실패한 메시지는 DLQ로 보내고, 원인을 분석한 뒤 수동 재처리하거나 폐기하는 방식으로 운영합니다.

## 면접 질문 2

### Q. DLX와 DLQ의 차이는 무엇인가요?

**답변 예시**

DLQ는 실패한 메시지가 최종적으로 쌓이는 Queue입니다.  
DLX는 RabbitMQ에서 실패 메시지를 DLQ로 라우팅하는 Exchange입니다.

즉, DLX는 라우팅 역할이고 DLQ는 저장되는 목적지라고 볼 수 있습니다.

---

# 9. 큐의 팬아웃

## 실제 사례

주문이 생성되면 여러 후속 작업이 필요했다.

```text
1. 결제 검증
2. 재고 차감
3. 쿠폰 사용 처리
4. 알림 발송
5. 추천 시스템 이벤트 전달
6. 데이터 분석 적재
```

처음에는 OrderService 안에서 모든 작업을 직접 호출했다.

```text
OrderService
  → PaymentService
  → InventoryService
  → CouponService
  → NotificationService
  → AnalyticsService
```

문제는 주문 생성 로직이 너무 무거워지고, 하나의 부가 기능 장애가 주문 전체에 영향을 준다는 점이었다.

## 해결

OrderCreated 이벤트를 발행하고 여러 consumer가 각자 처리하도록 했다.

```text
OrderCreated Event
  ├─ PaymentConsumer
  ├─ InventoryConsumer
  ├─ CouponConsumer
  ├─ NotificationConsumer
  └─ AnalyticsConsumer
```

## 결과

```text
- 주문 생성 API 응답속도 개선
- 알림 장애가 주문 생성에 직접 영향 주지 않음
- 분석 기능 추가 시 OrderService 수정 최소화
- 관심사 분리
```

## 주의점

팬아웃 구조에서는 추적이 어려워질 수 있다.

따라서 다음 값이 필요하다.

```text
- event_id
- order_id
- correlation_id
- trace_id
- consumer별 처리 상태
```

## 면접 질문 1

### Q. 큐의 팬아웃이란 무엇인가요?

**답변 예시**

큐의 팬아웃은 하나의 이벤트를 여러 consumer나 여러 queue로 분기시키는 구조입니다.

예를 들어 주문 생성 이벤트가 발생하면 결제 consumer, 재고 consumer, 알림 consumer, 분석 consumer가 각각 독립적으로 이벤트를 받아 처리할 수 있습니다.

이를 통해 서비스 간 결합도를 낮추고 기능 추가 시 기존 주문 로직을 덜 수정하게 만들 수 있습니다.

## 면접 질문 2

### Q. 팬아웃 구조의 단점은 무엇인가요?

**답변 예시**

처리 흐름이 분산되기 때문에 장애 추적이 어려워집니다.  
어떤 consumer가 실패했는지, 이벤트가 어디까지 처리됐는지 확인하기 어렵습니다.

또한 메시지 중복 처리, 순서 보장, 부분 실패 문제가 생길 수 있습니다.

그래서 event_id, correlation_id, trace_id를 넣고 consumer별 처리 상태와 DLQ를 모니터링해야 합니다.

---

# 10. Kafka vs MQ 선택

## 실제 사례 A: 이메일 발송

회원가입 후 이메일을 보내야 한다.

특징:

```text
- 작업 단위가 명확함
- 실패 시 재시도 필요
- 처리 완료 후 메시지는 없어져도 됨
- 순서가 크게 중요하지 않음
```

이 경우 RabbitMQ나 SQS 같은 Message Queue가 적합하다.

## 실제 사례 B: 사용자 행동 로그

사용자 클릭, 페이지뷰, 검색어 로그를 저장해야 한다.

특징:

```text
- 이벤트 양이 매우 많음
- 여러 consumer가 같은 이벤트를 읽어야 함
- 나중에 재처리할 수 있어야 함
- 분석 파이프라인으로 연결됨
```

이 경우 Kafka가 적합하다.

```text
User Event
  ↓
Kafka Topic
  ├─ Realtime Dashboard Consumer
  ├─ Recommendation Consumer
  ├─ Data Lake Consumer
  └─ Fraud Detection Consumer
```

## 면접 질문

### Q. RabbitMQ와 Kafka는 어떻게 다르게 선택하나요?

**답변 예시**

RabbitMQ나 SQS 같은 MQ는 작업 큐에 적합합니다.  
예를 들어 이메일 발송, 이미지 리사이징, 외부 API 호출처럼 하나의 작업을 consumer가 처리하고 완료하는 구조에 잘 맞습니다.

Kafka는 이벤트 스트리밍과 로그성 데이터 처리에 적합합니다.  
이벤트를 일정 기간 보관하고, 여러 consumer group이 독립적으로 읽을 수 있으며, offset 기반 재처리도 가능합니다.

따라서 단순 작업 분배는 MQ, 대량 이벤트 스트리밍과 재처리가 필요한 구조는 Kafka를 우선 고려합니다.

---

# 11. Insert는 NoSQL

## 실제 사례

서비스에서 사용자 행동 로그를 모두 RDB에 저장하고 있었다.

```text
user_events
- id
- user_id
- event_type
- page
- created_at
```

트래픽이 증가하면서 다음 문제가 발생했다.

```text
- 월 1억 건 이상 insert
- user_events 테이블 크기 급증
- 인덱스 크기 증가
- insert 성능 저하
- 운영 DB 백업 시간 증가
- 통계 쿼리 때문에 운영 DB 부하 증가
```

## 해결

운영 트랜잭션 데이터와 로그성 데이터를 분리했다.

```text
API Server
  ↓
Kafka
  ↓
Log Consumer
  ↓
NoSQL / Object Storage / OLAP
```

핵심 주문/결제 데이터는 RDB에 유지했다.

```text
주문, 결제, 재고, 정산 → PostgreSQL/MySQL
클릭 로그, 행동 이벤트, 검색 로그 → Kafka + NoSQL/OLAP
```

## 면접 질문 1

### Q. “insert는 NoSQL”이라는 말을 어떻게 이해해야 하나요?

**답변 예시**

모든 insert를 NoSQL에 넣어야 한다는 뜻은 아닙니다.

정합성이 중요한 주문, 결제, 재고 같은 OLTP 데이터는 RDB에 저장하는 것이 적합합니다.  
다만 클릭 로그, 행동 이벤트, 알림 이력처럼 대량으로 append되는 로그성 데이터는 RDB보다 NoSQL, Kafka, Object Storage, OLAP 저장소가 더 적합할 수 있습니다.

## 면접 질문 2

### Q. 왜 로그성 데이터를 운영 DB에 계속 넣으면 문제가 되나요?

**답변 예시**

로그성 데이터는 양이 빠르게 증가하고 대부분 append-only입니다.  
운영 DB에 계속 넣으면 테이블과 인덱스가 커지고, 백업 시간이 늘어나고, 통계 쿼리가 운영 트랜잭션에 영향을 줄 수 있습니다.

그래서 운영에 필요한 핵심 데이터와 분석용 이벤트 데이터는 저장소를 분리하는 것이 좋습니다.

---

# 12. OLTP / OLAP 분리

## 실제 사례

관리자 페이지에서 월별 매출 통계를 조회할 때마다 운영 DB가 느려졌다.

통계 쿼리는 다음과 같았다.

```sql
SELECT 
  date_trunc('day', created_at),
  sum(amount),
  count(*)
FROM orders
WHERE created_at BETWEEN ? AND ?
GROUP BY 1;
```

문제:

```text
- orders 테이블이 수억 건
- GROUP BY, SUM, COUNT가 무거움
- 관리자 통계 조회 시 실제 주문 API도 느려짐
```

## 해결

OLTP와 OLAP를 분리했다.

```text
주문 생성
  ↓
OLTP DB
  ↓
CDC / Kafka / Batch
  ↓
OLAP DB
  ↓
관리자 통계 조회
```

운영 DB는 주문/결제 같은 실시간 트랜잭션에 집중하게 하고, 통계는 OLAP 저장소에서 처리하게 했다.

## 면접 질문 1

### Q. OLTP와 OLAP의 차이는 무엇인가요?

**답변 예시**

OLTP는 실시간 트랜잭션 처리를 의미합니다.  
예를 들어 주문 생성, 결제 승인, 회원가입, 재고 차감처럼 짧고 정합성이 중요한 작업입니다.

OLAP는 분석 처리를 의미합니다.  
예를 들어 월별 매출, 사용자 리텐션, 상품별 전환율, 대시보드 통계처럼 대량 데이터를 집계하는 작업입니다.

운영 DB에서 OLAP성 쿼리를 많이 돌리면 실제 서비스 트랜잭션에 영향을 줄 수 있기 때문에 분리하는 것이 좋습니다.

## 면접 질문 2

### Q. 통계 쿼리가 느릴 때 인덱스만 추가하면 되지 않나요?

**답변 예시**

초기에는 인덱스로 개선할 수 있지만, 데이터가 매우 커지고 집계 범위가 넓어지면 인덱스만으로 한계가 있습니다.

특히 월간/연간 통계처럼 대량 데이터를 scan하고 group by하는 쿼리는 운영 DB에 큰 부하를 줍니다.

그래서 일정 규모 이상에서는 사전 집계 테이블, Read Replica, Batch ETL, OLAP 저장소 분리를 고려해야 합니다.

---

# 13. 파티셔닝

## 실제 사례

주문 테이블이 5억 건까지 증가했다.

문제:

```text
- 최근 3개월 주문만 자주 조회
- 오래된 주문은 거의 조회하지 않음
- 인덱스 크기 증가
- 월 단위 데이터 삭제가 느림
- 백업/보관 정책 관리 어려움
```

## 해결

created_at 기준 월별 파티셔닝을 적용했다.

```text
orders_2026_01
orders_2026_02
orders_2026_03
orders_2026_04
```

최근 데이터 조회는 최신 파티션만 접근하게 하고, 오래된 파티션은 아카이빙하거나 삭제했다.

## 결과

```text
- 최근 주문 조회 성능 개선
- 오래된 데이터 삭제가 쉬워짐
- 인덱스 관리 부담 감소
- 파티션 단위 백업/아카이빙 가능
```

## 면접 질문 1

### Q. 파티셔닝과 샤딩의 차이는 무엇인가요?

**답변 예시**

파티셔닝은 보통 하나의 DB 안에서 큰 테이블을 여러 파티션으로 나누는 방식입니다.  
예를 들어 주문 테이블을 월별로 나눌 수 있습니다.

샤딩은 데이터를 여러 DB 인스턴스에 나누어 저장하는 방식입니다.  
즉, DB 자체를 여러 개로 분산하는 것이기 때문에 운영 복잡도가 훨씬 높습니다.

그래서 보통 파티셔닝으로 해결 가능한 경우에는 샤딩까지 가지 않는 것이 좋습니다.

## 면접 질문 2

### Q. 시간 기준 파티셔닝은 언제 유리한가요?

**답변 예시**

데이터가 시간 순서로 계속 쌓이고, 조회도 주로 최근 데이터에 집중되는 경우 유리합니다.

예를 들어 주문, 로그, 이벤트, 알림 이력, 결제 이력 같은 데이터입니다.

월별이나 일별 파티션을 사용하면 최근 데이터 조회 성능을 개선하고, 오래된 데이터는 파티션 단위로 삭제하거나 아카이빙할 수 있습니다.

---

# 14. 수직 파티셔닝

## 실제 사례

회원 테이블에 모든 정보가 들어 있었다.

```text
users
- id
- email
- password
- name
- phone
- profile_image
- bio
- preferences_json
- marketing_settings
- created_at
```

대부분의 로그인/인증 API는 email, password, status만 필요했다.  
하지만 테이블에 큰 profile_image, bio, preferences_json 컬럼이 함께 있어 row가 무거웠다.

## 해결

자주 쓰는 핵심 정보와 덜 쓰는 프로필 정보를 분리했다.

```text
users
- id
- email
- password
- status
- created_at

user_profiles
- user_id
- profile_image
- bio
- preferences_json
- marketing_settings
```

## 면접 질문

### Q. 수직 파티셔닝은 어떤 경우에 적용하나요?

**답변 예시**

한 테이블 안에 자주 조회하는 컬럼과 거의 조회하지 않는 무거운 컬럼이 섞여 있을 때 적용할 수 있습니다.

예를 들어 로그인에는 email, password, status만 필요한데, 같은 테이블에 큰 JSON, 이미지 경로, 긴 소개글 같은 컬럼이 있으면 불필요한 I/O가 발생할 수 있습니다.

이 경우 핵심 users 테이블과 user_profiles 테이블로 나누어 조회 패턴에 맞게 최적화할 수 있습니다.

---

# 15. 샤딩

## 실제 사례

메시징 서비스에서 메시지 테이블이 너무 커졌다.

```text
messages
- id
- room_id
- sender_id
- content
- created_at
```

특징:

```text
- 월 수십억 건 메시지 저장
- 특정 대형 채팅방에 트래픽 집중
- 단일 DB의 저장 용량과 write throughput 한계 도달
- 파티셔닝과 리플리케이션만으로 부족
```

## 해결

room_id 기반 샤딩을 적용했다.

```text
shard = hash(room_id) % N
```

구조:

```text
Message DB Shard 0
Message DB Shard 1
Message DB Shard 2
Message DB Shard 3
```

메시지는 room_id 기준으로 특정 shard에 저장되도록 했다.

## 왜 room_id인가?

메시지 조회 패턴이 대부분 특정 채팅방 기준이었기 때문이다.

```text
채팅방 메시지 목록 조회
WHERE room_id = ?
ORDER BY created_at DESC
```

따라서 room_id를 shard key로 잡으면 한 채팅방의 메시지가 같은 shard에 있어 조회가 단순해진다.

## 면접 질문 1

### Q. 샤딩은 언제 적용해야 하나요?

**답변 예시**

샤딩은 최후의 수단에 가깝습니다.

먼저 쿼리 최적화, 인덱스 최적화, 캐시, Read Replica, 파티셔닝, 비동기 처리, OLTP/OLAP 분리를 검토해야 합니다.

그럼에도 단일 DB의 저장 용량, write throughput, connection, I/O 한계를 넘는다면 샤딩을 고려합니다.

샤딩은 cross-shard query, transaction, migration, 운영 복잡도가 매우 크기 때문에 필요성이 명확할 때만 적용해야 합니다.

## 면접 질문 2

### Q. shard key는 어떻게 정하나요?

**답변 예시**

가장 중요한 기준은 조회 패턴과 데이터 분포입니다.

자주 조회하는 기준으로 shard key를 잡아야 cross-shard query를 줄일 수 있습니다.  
동시에 특정 shard에 데이터나 트래픽이 몰리지 않도록 분포가 균등해야 합니다.

예를 들어 채팅 메시지는 room_id 기준 조회가 많다면 room_id를 shard key로 고려할 수 있습니다.  
하지만 일부 대형 room에 트래픽이 몰린다면 hot shard 문제가 생길 수 있어 추가 분산 전략이 필요합니다.

---

# 16. 월 1억 건 데이터 처리

## 실제 사례

알림 이력 테이블에 월 1억 건이 쌓이고 있었다.

```text
notification_history
- id
- user_id
- type
- status
- created_at
```

단순 계산하면:

```text
월 100,000,000건
하루 약 3,333,333건
초당 평균 약 38.5건
```

평균만 보면 높지 않지만 실제 문제는 피크였다.

```text
- 오전 9시 캠페인 발송 때 초당 3,000건 insert
- created_at index가 커짐
- 오래된 데이터 삭제가 느림
- 관리자 통계 조회가 운영 DB를 압박
```

## 해결 순서

샤딩을 바로 하지 않았다.

먼저 다음을 적용했다.

```text
1. 알림 발송 요청을 Queue로 완충
2. Worker에서 batch insert
3. notification_history 월별 파티셔닝
4. 오래된 파티션은 아카이빙
5. 통계 조회는 OLAP로 분리
6. 자주 조회하는 최근 데이터만 RDB 유지
```

## 최종 구조

```text
Notification API
  ↓
Queue
  ↓
Notification Worker
  ↓
Recent History RDB Partition
  ↓
Old Data Archive / OLAP
```

## 면접 질문

### Q. 월 1억 건이면 무조건 샤딩해야 하나요?

**답변 예시**

무조건 샤딩해야 하는 것은 아닙니다.

월 1억 건은 평균으로 보면 초당 약 40건 수준입니다.  
하지만 중요한 것은 평균이 아니라 피크 트래픽, row size, index size, 조회 패턴, 보관 기간입니다.

예를 들어 특정 시간에 초당 수천 건이 몰리고, 인덱스가 커지고, 통계 쿼리까지 운영 DB에서 돌고 있다면 문제가 될 수 있습니다.

이 경우에도 바로 샤딩하기보다는 Queue로 쓰기 부하를 완충하고, batch insert, 파티셔닝, 아카이빙, OLAP 분리를 먼저 고려합니다.  
그 이후에도 단일 DB 한계를 넘으면 샤딩을 검토합니다.

---

# 17. Multi-read Replication

## 실제 사례

콘텐츠 플랫폼에서 글 조회 트래픽이 폭증했다.

```text
- 글 작성보다 글 조회가 100배 많음
- 인기 글 하나에 조회 요청 집중
- Primary DB의 SELECT 부하 증가
```

## 해결

Read Replica를 여러 대 두고 조회 API를 분산했다.

```text
Primary DB
  ↓
Replica 1
Replica 2
Replica 3
Replica 4
```

API 서버는 읽기 요청을 Replica로 라우팅했다.

## 추가 전략

```text
- 인기 글은 Redis Cache 적용
- 일반 조회는 Replica
- 작성 직후 조회는 Primary
- 관리자 통계는 OLAP
```

## 면접 질문

### Q. 읽기 부하가 많을 때 Cache와 Read Replica 중 무엇을 먼저 고려하나요?

**답변 예시**

조회 패턴에 따라 다릅니다.

같은 데이터가 반복 조회된다면 Cache가 효과적입니다.  
예를 들어 인기 게시글, 상품 상세, 카테고리 목록처럼 동일 key가 반복되는 경우입니다.

반대로 조회 데이터가 다양하고 캐시 hit ratio가 높지 않을 것 같다면 Read Replica로 읽기 부하를 분산하는 것이 더 적합할 수 있습니다.

실무에서는 둘을 함께 쓰는 경우도 많습니다.  
인기 데이터는 Cache, 일반 조회는 Replica로 처리하는 방식입니다.

---

# 18. Multi-Master Multi-Slave

## 실제 사례

글로벌 협업 서비스를 운영하고 있다.

```text
- 한국 사용자
- 미국 사용자
- 유럽 사용자
```

모든 쓰기를 한국 DB로 보내면 미국/유럽 사용자의 write latency가 너무 컸다.

```text
미국 사용자 → 한국 DB write
네트워크 왕복 지연 증가
```

## 해결 후보

지역별로 쓰기 가능한 DB를 두는 multi-master 구조를 검토했다.

```text
Korea Master ↔ US Master ↔ EU Master
      ↓             ↓           ↓
   Replica       Replica     Replica
```

## 문제

동일 데이터를 여러 지역에서 동시에 수정하면 conflict가 발생한다.

예:

```text
한국에서 문서 제목 수정
미국에서 같은 문서 제목 수정
둘 중 어떤 값을 최종값으로 볼 것인가?
```

## 실제 선택

강한 정합성이 필요한 데이터는 single writer 구조를 유지하고, 지역별로 독립적인 데이터만 multi-region write를 허용했다.

```text
결제, 계정 권한 → single primary
지역별 로그, 활동 이벤트 → regional write 허용
```

## 면접 질문

### Q. Multi-master 구조는 왜 어렵나요?

**답변 예시**

여러 노드에서 동시에 쓰기를 받을 수 있기 때문에 conflict resolution 문제가 생깁니다.

같은 데이터를 서로 다른 지역에서 동시에 수정하면 어떤 값을 최종 값으로 선택할지 결정해야 합니다.

또한 복제 지연, 네트워크 파티션, 정합성 보장 문제가 복잡해집니다.

그래서 일반적인 서비스에서는 multi-master를 쉽게 도입하지 않고, single writer 구조나 도메인별 write ownership을 먼저 고려합니다.

---

# 19. 인메모리 데이터 그리드

## 실제 사례

실시간 게임 서버에서 사용자 매칭 상태와 룸 상태를 빠르게 조회해야 했다.

RDB에 매번 접근하면 latency가 너무 컸다.

```text
- 매칭 대기 사용자 목록
- 현재 게임 룸 상태
- 유저 접속 상태
- 실시간 점수
```

## 해결

Hazelcast나 Redis Cluster 같은 인메모리 데이터 그리드를 사용했다.

```text
Game Server 1
Game Server 2
Game Server 3
  ↓
In-memory Data Grid
```

## 사용 이유

```text
- 매우 낮은 latency 필요
- 데이터가 자주 변경됨
- 모든 데이터를 영구 저장할 필요는 없음
- 여러 서버가 같은 상태를 빠르게 공유해야 함
```

## 주의

인메모리 데이터 그리드는 DB 대체제가 아니다.

```text
영구 보존 필요 데이터 → RDB
빠른 임시 상태 → In-memory Grid
```

## 면접 질문

### Q. Redis 같은 인메모리 저장소를 DB처럼 써도 되나요?

**답변 예시**

영구 정합성이 중요한 데이터에는 신중해야 합니다.

Redis나 인메모리 데이터 그리드는 빠르지만 메모리 기반이기 때문에 장애, eviction, persistence 설정에 따라 데이터 유실 가능성이 있습니다.

세션, 캐시, 랭킹, 임시 상태, 분산 락 같은 용도에는 적합하지만 주문, 결제, 정산 같은 핵심 데이터의 source of truth로 쓰는 것은 위험할 수 있습니다.

---

# 20. 페더레이션

## 실제 사례

커머스 서비스가 커지면서 도메인별로 시스템이 나뉘었다.

```text
User Service
Order Service
Payment Service
Coupon Service
Point Service
```

마이페이지에서는 이 데이터를 한 번에 보여줘야 했다.

```text
- 회원 정보
- 최근 주문
- 포인트
- 쿠폰
- 결제 수단
```

## 나쁜 구조

프론트엔드가 각 서비스를 직접 호출한다.

```text
Frontend
  ├─ User API
  ├─ Order API
  ├─ Point API
  ├─ Coupon API
  └─ Payment API
```

문제:

```text
- 프론트엔드 복잡도 증가
- 인증/권한 처리 중복
- 장애 처리 어려움
- 화면별 조합 로직이 흩어짐
```

## 개선

BFF나 GraphQL Federation을 둔다.

```text
Frontend
  ↓
MyPage BFF / GraphQL Gateway
  ├─ User Service
  ├─ Order Service
  ├─ Point Service
  └─ Coupon Service
```

## 면접 질문

### Q. 페더레이션은 어떤 문제를 해결하나요?

**답변 예시**

페더레이션은 여러 독립 시스템이나 서비스를 하나의 논리적 API처럼 묶어주는 역할을 합니다.

도메인별 서비스는 독립적으로 유지하면서, 클라이언트 입장에서는 필요한 데이터를 한 번에 조회할 수 있게 해줍니다.

다만 내부적으로 여러 서비스를 호출하기 때문에 timeout, partial failure, observability, caching 전략이 중요합니다.

---

# 21. Abstraction of Concern

## 실제 사례

OrderService에서 RabbitMQ 라이브러리를 직접 호출하고 있었다.

```java
public void createOrder(Order order) {
    orderRepository.save(order);
    rabbitTemplate.convertAndSend("order.exchange", "order.created", order);
}
```

문제는 나중에 Kafka로 전환하려고 하자 주문 서비스 코드 곳곳을 수정해야 했다는 점이다.

## 개선

이벤트 발행을 추상화했다.

```java
public interface EventPublisher {
    void publish(String topic, Object event);
}
```

RabbitMQ 구현체:

```java
public class RabbitEventPublisher implements EventPublisher {
    public void publish(String topic, Object event) {
        rabbitTemplate.convertAndSend(topic, event);
    }
}
```

Kafka 구현체:

```java
public class KafkaEventPublisher implements EventPublisher {
    public void publish(String topic, Object event) {
        kafkaTemplate.send(topic, event);
    }
}
```

OrderService는 구체 기술을 모른다.

```java
public void createOrder(Order order) {
    orderRepository.save(order);
    eventPublisher.publish("order.created", new OrderCreatedEvent(order.getId()));
}
```

## 면접 질문

### Q. Abstraction of concern은 왜 중요한가요?

**답변 예시**

구체 기술에 직접 의존하면 변경에 취약해집니다.

예를 들어 비즈니스 로직이 RabbitMQ API를 직접 호출하면 Kafka로 바꾸거나 테스트할 때 많은 코드가 영향을 받습니다.

EventPublisher 같은 인터페이스로 추상화하면 비즈니스 로직은 이벤트 발행이라는 개념에만 의존하고, RabbitMQ나 Kafka 같은 구현체는 바깥으로 분리할 수 있습니다.

---

# 22. Separation of Concern

## 실제 사례

OrderService 하나가 너무 많은 일을 하고 있었다.

```text
OrderService.createOrder()
  - 주문 생성
  - 결제 요청
  - 쿠폰 차감
  - 재고 차감
  - 포인트 적립
  - 이메일 발송
  - 분석 로그 저장
```

문제:

```text
- 코드가 길고 복잡함
- 테스트 어려움
- 하나의 외부 API 장애가 주문 생성에 영향
- 변경 영향 범위가 큼
```

## 개선

책임을 분리했다.

```text
OrderService → 주문 생성
PaymentService → 결제
InventoryService → 재고
CouponService → 쿠폰
NotificationConsumer → 알림
AnalyticsConsumer → 분석 로그
```

## 면접 질문

### Q. Separation of concern이 분산처리와 무슨 관련이 있나요?

**답변 예시**

관심사가 분리되어 있어야 어떤 작업을 동기로 처리하고 어떤 작업을 비동기로 분리할지 결정할 수 있습니다.

예를 들어 주문 생성은 핵심 트랜잭션이지만 알림 발송이나 분석 로그 저장은 비동기로 처리해도 됩니다.

코드 안에서 모든 책임이 섞여 있으면 Queue나 Event 기반 구조를 도입해도 구조가 복잡해집니다.

---

# 23. 외부 API 장애 격리

## 실제 사례

결제 완료 후 문자 알림을 발송하는 API가 있었다.

초기 구조:

```text
결제 승인
  ↓
SMS 발송
  ↓
응답 반환
```

SMS 업체 장애가 발생하자 결제 API도 timeout이 발생했다.

## 해결

결제는 동기 처리하고 SMS는 비동기로 분리했다.

```text
결제 승인
  ↓
Payment DB 저장
  ↓
PaymentCompleted Event 발행
  ↓
응답 반환

SMS Consumer
  ↓
SMS 발송
```

SMS 발송 실패 시 DLQ로 보냈다.

## 면접 질문

### Q. 외부 API 장애가 내부 서비스에 영향을 주지 않게 하려면 어떻게 해야 하나요?

**답변 예시**

먼저 timeout과 retry 정책을 명확히 둬야 합니다.  
무한정 기다리거나 무한 재시도하면 내부 리소스가 고갈될 수 있습니다.

핵심 트랜잭션과 직접 관련 없는 외부 호출은 Queue 기반 비동기로 분리할 수 있습니다.

또한 circuit breaker를 적용해서 외부 API 장애가 지속될 때 빠르게 실패 처리하고, 실패 메시지는 DLQ에 저장해서 나중에 재처리할 수 있게 합니다.

---

# 24. 실전 면접 종합 질문

## Q1. 트래픽이 10배 증가하면 어떤 순서로 대응하시겠습니까?

**답변 예시**

먼저 관측 지표를 확인합니다.

```text
- API latency p95/p99
- CPU, memory
- DB slow query
- DB connection pool
- cache hit ratio
- queue lag
- error rate
```

그다음 병목에 따라 대응합니다.

API 서버 CPU가 병목이면 Load Balancer 뒤에 서버를 수평 확장합니다.  
DB 읽기가 병목이면 인덱스 최적화, Cache, Read Replica를 검토합니다.  
DB 쓰기가 병목이면 트랜잭션 범위 축소, batch insert, Queue, 파티셔닝을 검토합니다.  
외부 API가 병목이면 timeout, retry, circuit breaker, 비동기 처리를 적용합니다.

중요한 점은 트래픽 증가 = 무조건 샤딩이 아니라, 병목 기반으로 가장 단순한 해결책부터 적용하는 것입니다.

## Q2. Cache, Replica, Queue, Sharding 중 어떤 순서로 도입하나요?

**답변 예시**

일반적으로는 복잡도가 낮고 효과가 큰 것부터 도입합니다.

```text
1. 쿼리/인덱스 최적화
2. Cache
3. Read Replica
4. Queue 기반 비동기 처리
5. 파티셔닝
6. 샤딩
```

다만 병목 유형에 따라 순서는 달라집니다.

읽기 부하가 크고 동일 데이터 반복 조회가 많으면 Cache가 먼저입니다.  
조회 데이터가 다양하면 Read Replica가 효과적일 수 있습니다.  
느린 외부 API나 후처리 작업이 문제면 Queue가 먼저입니다.  
단일 DB의 저장 용량과 write throughput 한계가 명확하면 파티셔닝이나 샤딩을 검토합니다.

## Q3. 샤딩을 최대한 늦게 해야 하는 이유는 무엇인가요?

**답변 예시**

샤딩은 단일 DB의 한계를 넘을 수 있는 강력한 방법이지만 운영 복잡도가 매우 큽니다.

샤딩을 하면 cross-shard join이 어려워지고, cross-shard transaction도 복잡해집니다.  
또한 shard key를 잘못 잡으면 특정 shard에 트래픽이 몰리는 hot shard 문제가 생길 수 있습니다.

데이터 재분배, 백업, 복구, 모니터링, 장애 대응도 복잡해집니다.

그래서 먼저 인덱스 최적화, 캐시, 리플리케이션, 파티셔닝, 비동기 처리를 검토하고, 그래도 단일 DB 한계를 넘을 때 샤딩을 적용하는 것이 좋습니다.

## Q4. 비동기 메시지 처리에서 가장 중요한 설계 포인트는 무엇인가요?

**답변 예시**

가장 중요한 것은 중복 처리와 실패 처리입니다.

메시지 시스템은 보통 at-least-once 전달을 전제로 하기 때문에 같은 메시지가 두 번 처리될 수 있습니다.  
따라서 event_id나 idempotency key를 사용해서 consumer를 멱등하게 설계해야 합니다.

또한 처리 실패 시 무한 재시도를 막기 위해 retry count를 제한하고, 계속 실패하는 메시지는 DLQ로 보내야 합니다.

마지막으로 consumer lag, retry count, DLQ 적재량을 모니터링해야 운영이 가능합니다.

## Q5. OLTP DB에서 통계 쿼리를 돌리면 왜 위험한가요?

**답변 예시**

OLTP DB는 주문, 결제, 회원가입처럼 짧고 정합성이 중요한 트랜잭션을 처리하기 위한 저장소입니다.

그런데 월별 매출 통계나 사용자 행동 분석처럼 대량 데이터를 scan하고 group by하는 OLAP성 쿼리를 운영 DB에서 실행하면 CPU, I/O, lock, buffer cache에 부담을 줘서 실제 서비스 API가 느려질 수 있습니다.

그래서 일정 규모 이상에서는 통계 데이터를 별도의 OLAP 저장소나 집계 테이블로 분리하는 것이 좋습니다.

## Q6. Kafka를 쓰면 무조건 좋은가요?

**답변 예시**

아닙니다. Kafka는 대량 이벤트 스트리밍, 로그 보관, 재처리, 여러 consumer group이 필요한 상황에는 강력합니다.

하지만 단순 이메일 발송이나 작은 규모의 작업 큐라면 RabbitMQ, SQS 같은 MQ가 더 단순하고 적합할 수 있습니다.

Kafka는 운영 복잡도가 있습니다.  
broker 운영, partition 설계, consumer lag, offset 관리, rebalancing, 메시지 순서 보장 범위 등을 이해해야 합니다.

따라서 요구사항이 단순 작업 큐인지, 이벤트 스트리밍인지에 따라 선택해야 합니다.

## Q7. Read Replica에서 방금 쓴 데이터가 안 보이면 어떻게 하나요?

**답변 예시**

Replica에는 replication lag이 있을 수 있기 때문에 방금 쓴 데이터를 바로 읽어야 하는 경우에는 Primary에서 읽도록 라우팅합니다.

예를 들어 사용자가 게시글을 작성한 직후 본인의 글을 조회하는 경우에는 Primary를 조회하고, 일반 목록 조회는 Replica를 사용합니다.

또는 write 후 일정 시간 동안 해당 사용자의 읽기 요청을 Primary로 보내는 read-your-writes 전략을 사용할 수도 있습니다.

## Q8. 팬아웃 구조에서 일부 consumer만 실패하면 어떻게 하나요?

**답변 예시**

각 consumer는 독립적으로 실패 처리와 재시도를 가져야 합니다.

예를 들어 OrderCreated 이벤트를 결제 consumer, 알림 consumer, 분석 consumer가 각각 처리할 때 알림 consumer가 실패하더라도 주문 생성 전체가 실패하면 안 됩니다.

실패한 consumer는 retry 후 DLQ로 보내고, event_id와 correlation_id를 통해 어떤 이벤트의 어떤 consumer가 실패했는지 추적할 수 있어야 합니다.

## Q9. 대량 insert를 처리할 때 어떤 전략을 쓰나요?

**답변 예시**

먼저 동기 API 요청 안에서 매번 DB에 insert하지 않고 Queue나 Kafka로 완충합니다.

Consumer나 worker가 batch insert를 수행하면 DB round-trip을 줄일 수 있습니다.

로그성 데이터라면 RDB 대신 NoSQL, Object Storage, OLAP 저장소로 분리하는 것도 고려합니다.

또한 테이블이 매우 커진다면 시간 기준 파티셔닝, 오래된 데이터 아카이빙, 불필요한 인덱스 제거를 함께 적용합니다.

## Q10. 시니어 백엔드 개발자로서 아키텍처 개선을 어떻게 제안하겠습니까?

**답변 예시**

먼저 문제를 기술명으로 정의하지 않고 지표로 정의하겠습니다.

예를 들어 “Kafka를 도입하자”가 아니라 “회원가입 API의 p95 latency가 외부 CRM 호출 때문에 2.5초까지 증가하고 있으므로 CRM 전송을 비동기 이벤트로 분리하자”처럼 말해야 합니다.

그다음 개선안을 단계적으로 제안합니다.

```text
1. 현재 병목 지표 확인
2. 가장 단순한 개선부터 적용
3. 변경 전후 수치 비교
4. 운영 복잡도 평가
5. 장애 대응 전략 포함
6. 장기적으로 확장 가능한 구조 설계
```

아키텍처 개선은 기술 도입이 아니라 성능, 안정성, 정합성, 운영 비용 사이의 균형을 맞추는 일이라고 생각합니다.

---

# 25. 최종 압축 정리

| 문제 | 먼저 볼 지표 | 우선 해결책 | 이후 확장 |
|---|---|---|---|
| API 서버 과부하 | CPU, p95, thread | Load Balancer + 수평 확장 | Auto Scaling |
| DB 읽기 병목 | SELECT latency, DB CPU | 인덱스, Cache | Read Replica |
| DB 쓰기 병목 | INSERT latency, lock | 트랜잭션 축소, batch | Queue, 파티셔닝 |
| 반복 조회 많음 | Cache hit ratio | Redis Cache | Redis Cluster |
| 외부 API 지연 | timeout, error rate | timeout, retry | Queue, DLQ |
| 대량 이벤트 | TPS, 저장량 | Kafka/MQ | NoSQL, OLAP |
| 통계 쿼리 무거움 | scan row, query time | 집계 테이블 | OLAP 분리 |
| 테이블 거대화 | row count, index size | 파티셔닝 | 아카이빙 |
| 단일 DB 한계 | CPU, I/O, storage | 최적화 종합 | 샤딩 |
| 글로벌 쓰기 | region latency | single writer 검토 | multi-master 신중 적용 |

## 면접용 한 문장

> 트래픽 증가나 데이터 증가 문제를 해결할 때는 먼저 p95/p99 latency, DB 부하, cache hit ratio, queue lag 같은 지표로 병목을 확인하고, Load Balancer, Cache, Read Replica, Queue, OLAP 분리, 파티셔닝을 순서대로 검토한 뒤, 단일 DB 한계가 명확할 때만 샤딩이나 멀티마스터 같은 고복잡도 구조를 선택하겠습니다.
