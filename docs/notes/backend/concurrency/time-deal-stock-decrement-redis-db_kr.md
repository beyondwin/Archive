# Redis, Optimistic Lock, UPSERT로 타임딜 재고 차감 설계하기

원문: [[Redis] Redis 1차 필터 + Optimistic Lock + UPSERT로 Oversell 0건 만든 타임딜 재고 차감 시스템](https://ditto-dev.tistory.com/110)

이 문서는 원문의 핵심 아이디어를 초보자도 이해할 수 있게 다시 정리한 것이다. 원문은 Kotlin, Spring, PostgreSQL, Redis로 타임딜 재고 차감 시스템을 구현한 경험을 다룬다. 핵심은 “Redis를 쓰면 동시성 문제가 해결된다”가 아니라, Redis는 DB를 보호하는 1차 필터로만 쓰고, 최종 정합성은 DB와 보상 로직으로 보장한다는 점이다.

## 한 줄 결론

한정 수량 판매에서 재고가 음수가 되면 안 된다. 그래서 Redis로 초과 요청을 빠르게 걸러내고, PostgreSQL의 조건부 UPDATE와 UPSERT로 최종 검증을 하며, Redis와 DB가 어긋나는 상황은 보상 로직과 주기적 복구 작업으로 맞춘다.

## 먼저 알아야 할 용어

### Oversell

재고보다 더 많이 팔리는 상황이다. 재고가 100개인데 주문이 101건 확정되면 oversell이다. 한정 판매, 쿠폰, 좌석 예매, 결제 같은 도메인에서는 단순 버그가 아니라 사용자 신뢰와 비용으로 이어진다.

### Redis

메모리 기반 저장소다. 매우 빠르기 때문에 재고처럼 자주 읽고 쓰는 값을 임시로 다루기에 좋다. 하지만 Redis에 있는 값이 항상 최종 진실이라는 뜻은 아니다. 결제, 주문, 구매 이력처럼 영속성과 감사가 필요한 데이터는 보통 DB가 기준이 된다.

### DB를 진실의 원천으로 둔다

최종적으로 무엇이 맞는지는 DB를 보고 판단한다는 뜻이다. Redis 값이 DB와 다르면 Redis를 고치는 방향으로 설계한다. 반대로 Redis 값을 믿고 DB를 맞추면 장애나 유실 상황에서 잘못된 판매 결과를 확정할 수 있다.

### Optimistic Lock

낙관적 락이라고 부른다. 실제로 먼저 잠그고 기다리게 만드는 방식이 아니라, “내가 읽은 버전이 아직 최신이면 업데이트한다”는 조건을 UPDATE에 넣는 방식이다.

예를 들어 재고 row에 `version` 컬럼이 있다고 하자.

```sql
UPDATE time_deals
SET remaining_stock = remaining_stock - 1,
    version = version + 1
WHERE id = :deal_id
  AND version = :expected_version
  AND remaining_stock >= 1;
```

동시에 여러 요청이 같은 `version`을 보고 들어와도, 먼저 성공한 요청만 `version`을 올린다. 나머지는 `WHERE version = :expected_version` 조건에 실패해서 업데이트되지 않는다.

### UPSERT

`INSERT`를 시도하되, 이미 같은 키가 있으면 `UPDATE`하는 방식이다. PostgreSQL에서는 `INSERT ... ON CONFLICT DO UPDATE` 문법을 쓴다. 1인 구매 한도처럼 “없으면 만들고, 있으면 수량을 늘리되 한도를 넘기면 실패” 같은 로직을 한 SQL 안에서 처리할 수 있다.

### 보상 트랜잭션

이미 한쪽 시스템에서 성공한 작업을 나중에 되돌리는 작업이다. Redis에서 재고를 1개 줄였는데 DB 업데이트가 실패했다면 Redis 재고를 다시 1개 늘려야 한다. 이 복구 작업이 보상이다.

## 해결하려는 문제

타임딜은 일반 쇼핑몰과 다르게 한 순간에 요청이 몰린다. 재고 100개짜리 상품에 2,000명이 거의 동시에 구매 요청을 보낼 수 있다. 이때 중요한 요구사항은 네 가지다.

1. 재고 100개면 성공 주문은 최대 100건이어야 한다.
2. 같은 사용자가 동시에 여러 번 눌러도 1인 구매 한도를 넘기면 안 된다.
3. 품절 이후의 1,900개 요청이 모두 DB까지 도달하면 안 된다.
4. Redis, DB, 애플리케이션 중 하나가 중간에 실패해도 최종 상태를 복구할 수 있어야 한다.

단순히 `SELECT remaining_stock`으로 재고를 읽고, 남아 있으면 `UPDATE`하는 코드는 위험하다.

```text
요청 A: 재고 1개 확인
요청 B: 재고 1개 확인
요청 A: 구매 성공, 재고 0개
요청 B: 구매 성공, 재고 -1개
```

두 요청 모두 “재고가 있다”고 판단했기 때문에 oversell이 발생한다.

## 원문 설계의 핵심 구조

원문은 세 겹의 방어선을 둔다.

```text
구매 요청
  |
  v
1차: Redis Lua 스크립트로 재고 확인 + 차감
  |
  v
2차: PostgreSQL 조건부 UPDATE로 재고 차감
  |
  v
3차: PostgreSQL UPSERT WHERE로 1인 구매 한도 검증
```

각 단계의 역할은 다르다.

| 단계 | 목적 | 실패하면 |
|---|---|---|
| Redis Lua | 품절 이후 요청을 빠르게 차단해서 DB를 보호한다. | 바로 409 응답을 준다. |
| DB 조건부 UPDATE | DB 재고가 음수가 되지 않게 최종 방어한다. | Redis 차감을 되돌리고 실패 처리한다. |
| UPSERT WHERE | 같은 사용자의 중복 구매와 한도 초과를 DB에서 막는다. | Redis 차감을 되돌리고 DB 트랜잭션은 롤백한다. |

이 구조에서 Redis는 최종 판정자가 아니다. Redis가 통과시킨 요청도 DB에서 다시 검증한다. Redis가 잘못 통과시켜도 DB가 막아야 하고, DB가 실패하면 Redis를 되돌려야 한다.

## 왜 Redis Lua를 쓰는가

Redis의 `DECRBY` 같은 단일 명령은 원자적이다. 하지만 “재고를 읽고, 충분한지 확인하고, 차감한다”는 작업을 여러 명령으로 나누면 중간에 다른 요청이 끼어들 수 있다.

위험한 흐름은 이렇다.

```text
요청 A: GET stock -> 1
요청 B: GET stock -> 1
요청 A: DECRBY stock 1 -> 0
요청 B: DECRBY stock 1 -> -1
```

그래서 확인과 차감을 하나의 Lua 스크립트로 묶는다.

```lua
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local quantity = tonumber(ARGV[1])

if current < quantity then
    return -1
end

return redis.call('DECRBY', KEYS[1], quantity)
```

Redis 공식 문서는 Lua 스크립트가 서버 안에서 실행되며 실행 중에는 다른 서버 활동이 막힌다고 설명한다. 즉 이 스크립트 안의 확인과 차감 사이에는 다른 요청이 끼어들 수 없다.

주의할 점도 있다. Lua 스크립트가 길거나 느리면 Redis 전체를 막을 수 있다. 그래서 이 스크립트는 짧고 단순해야 한다. 또한 Redis 스크립트 캐시는 재시작이나 failover 때 사라질 수 있으므로, `EVALSHA` 실패 시 스크립트를 다시 로드하는 처리가 필요하다.

## 왜 DB에서도 다시 막아야 하는가

Redis가 원자적으로 차감했다고 해서 주문이 확정된 것은 아니다. Redis 차감 이후에도 다음 문제가 생길 수 있다.

1. DB 업데이트가 실패한다.
2. 같은 사용자가 구매 한도를 넘겼다.
3. 애플리케이션이 Redis 차감 후 DB 커밋 전에 죽는다.
4. Redis 값이 DB와 잠깐 어긋난다.

따라서 DB에도 “재고가 충분할 때만 줄인다”는 조건이 있어야 한다.

```sql
UPDATE time_deals
SET remaining_stock = remaining_stock - :quantity,
    version = version + 1
WHERE id = :id
  AND version = :expected_version
  AND remaining_stock >= :quantity;
```

여기서 중요한 조건은 두 개다.

1. `version = :expected_version`: 내가 본 버전이 아직 최신일 때만 성공한다.
2. `remaining_stock >= :quantity`: 재고가 부족하면 절대 음수로 만들지 않는다.

업데이트된 row 수가 1이면 성공이고, 0이면 누군가 먼저 바꿨거나 재고가 부족한 것이다.

다만 원문의 “락 대기가 없다”는 표현은 보완해서 이해해야 한다. PostgreSQL의 `UPDATE`는 row를 수정하는 동안 row-level lock을 사용한다. `SELECT FOR UPDATE`처럼 긴 대기열을 의도적으로 만들지 않는다는 장점은 있지만, 같은 row를 동시에 수정하는 순간에는 짧은 경합이 생길 수 있다. 핵심은 “긴 트랜잭션으로 row를 오래 붙잡지 않고, 조건부 UPDATE를 짧게 실행한다”는 데 있다.

## 1인 구매 한도는 왜 UPSERT WHERE로 막는가

다음 방식은 초보자가 가장 쉽게 떠올리는 구현이다.

```text
1. 현재 구매 수량 SELECT
2. 한도보다 작으면 INSERT 또는 UPDATE
```

하지만 동시에 두 요청이 들어오면 둘 다 같은 값을 읽고 통과할 수 있다.

```text
요청 A: 현재 구매 수량 0 확인
요청 B: 현재 구매 수량 0 확인
요청 A: 구매 수량 1 저장
요청 B: 구매 수량 1 저장
```

그래서 확인과 증가를 SQL 한 문장 안으로 넣는다.

```sql
INSERT INTO time_deal_purchases (time_deal_id, user_id, quantity)
VALUES (:deal_id, :user_id, :quantity)
ON CONFLICT (time_deal_id, user_id)
DO UPDATE
SET quantity = time_deal_purchases.quantity + :quantity
WHERE time_deal_purchases.quantity + :quantity <= :max_per_user;
```

이 쿼리가 안전하려면 `time_deal_purchases` 테이블에 `(time_deal_id, user_id)` 유니크 제약이 있어야 한다. 그래야 PostgreSQL이 “같은 딜에서 같은 사용자의 row”를 충돌 대상으로 인식한다.

PostgreSQL 공식 문서도 `ON CONFLICT DO UPDATE`에 `WHERE` 조건을 붙일 수 있음을 명시한다. 이 조건이 거짓이면 업데이트가 일어나지 않으므로, 애플리케이션은 affected row 수를 보고 한도 초과로 해석할 수 있다.

## 중요한 보완점: 이것은 엄밀한 의미의 멱등성이 아니다

원문은 1인 구매 한도를 SQL로 막는 것을 멱등성과 함께 설명한다. 하지만 엄밀히 말하면 “중복 방어”와 “멱등성”은 다르다.

멱등성은 같은 요청을 여러 번 보내도 같은 결과를 돌려주는 성질이다. 예를 들어 결제 요청이 네트워크 오류로 재시도되면, 서버는 같은 idempotency key에 대해 두 번째 결제를 만들지 않고 첫 번째 결과를 다시 돌려줘야 한다. Stripe 문서도 POST 요청 재시도에서 중복 수행을 피하기 위해 idempotency key를 사용한다고 설명한다.

UPSERT WHERE는 “한도를 넘는 추가 구매를 막는 장치”에 가깝다. 다음 케이스에서는 별도의 멱등성 키가 없으면 문제가 남는다.

1. `maxPerUser`가 2 이상이다.
2. 사용자가 한 번 구매했지만 응답을 받기 전에 네트워크가 끊겼다.
3. 클라이언트가 같은 구매 요청을 재시도한다.
4. 서버는 두 번째 요청을 새로운 구매로 보고 수량을 한 번 더 늘릴 수 있다.

따라서 결제나 주문 확정 API라면 다음 중 하나를 추가하는 편이 좋다.

```text
Idempotency-Key: 클라이언트가 요청마다 생성하는 고유 키
purchase_requests 테이블: request_id, user_id, deal_id, payload_hash, response_snapshot 저장
unique constraint: (user_id, idempotency_key)
```

그러면 같은 요청이 재시도될 때 새 구매를 만들지 않고 이전 결과를 재사용할 수 있다.

## 전체 구매 흐름을 초보자 관점에서 다시 쓰기

정상 구매는 이렇게 흘러간다.

```text
1. 사용자가 구매 버튼을 누른다.
2. 서버가 타임딜이 열려 있는지 확인한다.
3. 빠른 선검사로 사용자의 기존 구매 수량을 확인한다.
4. Redis Lua 스크립트가 재고를 먼저 줄인다.
5. DB 조건부 UPDATE가 실제 재고를 줄인다.
6. UPSERT WHERE가 사용자 구매 수량을 저장한다.
7. DB 트랜잭션이 커밋된다.
8. 서버가 구매 성공 응답을 보낸다.
```

3번의 선검사는 최종 방어선이 아니다. 동시에 요청이 들어오면 오래된 값을 읽을 수 있다. 그래서 6번의 UPSERT WHERE가 최종 방어선이어야 한다.

DB 재고 차감이 실패하면 이렇게 처리한다.

```text
1. Redis 재고는 이미 줄어든 상태다.
2. DB 조건부 UPDATE가 실패한다.
3. 서버가 Redis 재고를 다시 늘린다.
4. 구매 실패 응답을 보낸다.
```

구매 한도 검증이 실패해도 비슷하다.

```text
1. Redis 재고 차감 성공
2. DB 재고 차감 성공
3. UPSERT WHERE 실패
4. Redis 재고 복구
5. 예외 발생
6. DB 트랜잭션 롤백
7. 구매 실패 응답
```

애플리케이션이 중간에 죽으면 보상 로직이 실행되지 못할 수 있다. 그래서 주기적 복구 작업이 필요하다.

```text
1. Redis 재고: 99
2. DB 재고: 100
3. 복구 스케줄러가 DB를 기준으로 Redis를 100으로 되돌린다.
```

## 팩트체크

| 주장 | 판단 | 설명 |
|---|---|---|
| Redis Lua로 확인과 차감을 원자적으로 묶을 수 있다. | 맞음 | Redis 공식 문서는 Lua 스크립트 실행 중 서버 활동이 막히며 원자 실행이 보장된다고 설명한다. |
| Redis 스크립트는 재시작 후에도 항상 캐시에 남아 있다. | 아님 | Redis 스크립트 캐시는 휘발성이므로 `NOSCRIPT` 대응이 필요하다. |
| PostgreSQL `ON CONFLICT DO UPDATE WHERE`로 조건부 UPSERT를 만들 수 있다. | 맞음 | PostgreSQL INSERT 문법에 `DO UPDATE ... WHERE condition`이 포함된다. |
| `SELECT FOR UPDATE`는 같은 row에 대한 다른 writer를 기다리게 할 수 있다. | 맞음 | PostgreSQL row-level lock은 같은 row의 update/delete/locking 시도를 트랜잭션 종료까지 막을 수 있다. |
| Optimistic Lock UPDATE는 어떤 락도 쓰지 않는다. | 부정확 | 명시적 대기 락을 먼저 잡는 방식은 아니지만, PostgreSQL UPDATE 자체는 row-level lock을 사용한다. |
| Serializable 격리 수준을 쓰면 애플리케이션 재시도가 필요 없다. | 아님 | PostgreSQL 문서는 Repeatable Read와 Serializable에서 serialization failure 재시도를 준비해야 한다고 설명한다. |
| UPSERT WHERE만 있으면 결제 API가 완전한 멱등성을 가진다. | 부족함 | 한도 초과 방어에는 좋지만, 같은 요청의 재시도에 같은 응답을 보장하려면 idempotency key 저장이 필요하다. |
| Redisson 또는 Redis lock만으로 DB 정합성이 자동 보장된다. | 아님 | Redis 기반 락은 외부 시스템인 DB 커밋 결과까지 자동으로 보장하지 않는다. DB 제약과 트랜잭션 설계가 별도로 필요하다. |

## 원문 설계의 좋은 점

### 1. Redis를 최종 진실로 보지 않았다

Redis를 빠른 필터로만 쓰고, DB를 기준으로 설계를 닫은 점이 좋다. 실무에서 Redis 값은 장애, failover, TTL, 수동 조작, 복구 지연 등으로 DB와 어긋날 수 있다.

### 2. 품절 이후 요청을 DB에 보내지 않는다

재고 100개에 요청 2,000개가 오면, 이상적으로 DB는 2,000개 요청을 모두 처리할 필요가 없다. Redis에서 품절 이후 요청을 빨리 끊어주면 DB 커넥션 풀과 단일 row 경합을 줄일 수 있다.

### 3. 구매 한도를 DB 쿼리로 닫았다

애플리케이션에서 `SELECT` 후 판단하는 방식은 레이스에 취약하다. `UPSERT WHERE`처럼 DB가 한 문장 안에서 확인과 변경을 처리하게 만드는 편이 더 안전하다.

### 4. 보상 로직을 별도 컴포넌트로 분리했다

Redis 차감 후 실패하는 경로가 여러 개라면, 롤백 호출을 여기저기에 흩어두면 누락되기 쉽다. 보상 핸들러를 한 곳으로 모으는 것은 좋은 구조다.

### 5. 부하 테스트로 설계를 검증했다

동시성 버그는 코드만 읽어서는 잘 드러나지 않는다. k6 같은 도구로 실제 동시 요청을 넣어봐야 “재고는 맞는데 성공 수가 너무 적다” 같은 설계상의 병목을 발견할 수 있다.

## 보완하면 더 좋아지는 점

### 1. 멱등성 키를 추가한다

구매 API에는 `Idempotency-Key`를 받는 것이 좋다. 특히 결제, 주문 생성, 쿠폰 발급처럼 재시도될 수 있는 POST API는 “한도 초과 방어”와 별개로 “같은 요청 재실행 방어”가 필요하다.

추천 테이블 예시는 다음과 같다.

```sql
CREATE TABLE purchase_requests (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    time_deal_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, idempotency_key)
);
```

같은 사용자가 같은 key로 다시 요청하면 새 구매를 만들지 않고 저장된 결과를 반환한다. 같은 key인데 요청 내용이 다르면 잘못된 재사용으로 보고 거부한다.

### 2. Redis 장애 시 정책을 명확히 한다

Redis를 1차 필터로 쓰면 Redis 장애 때 선택지가 필요하다.

| 정책 | 장점 | 단점 |
|---|---|---|
| Fail closed | oversell 위험이 낮다. | Redis 장애 동안 구매가 막힌다. |
| DB-only fallback | Redis 장애 중에도 판매가 가능하다. | DB에 순간 트래픽이 몰릴 수 있다. |
| Queue fallback | 순서를 제어하기 쉽다. | 응답이 비동기화되고 구현이 커진다. |

타임딜처럼 짧은 이벤트라면 fail closed가 더 단순할 수 있다. 결제가 이미 진행 중인 흐름이라면 DB-only fallback이나 큐 기반 처리를 별도로 검토해야 한다.

### 3. Redis 값이 DB보다 클 때도 자동 조치 기준이 필요하다

원문은 `Redis < DB`이면 Redis를 복구하고, `Redis > DB`이면 알람을 남기는 방식이다. `Redis > DB`는 더 위험하다. Redis가 실제 DB 재고보다 많이 남았다고 믿으면 더 많은 요청이 DB까지 도달한다. DB 조건부 UPDATE가 oversell을 막긴 하지만, DB 보호라는 Redis 필터의 목적은 약해진다.

운영에서는 다음을 정해야 한다.

1. `Redis > DB`를 즉시 DB 값으로 낮출지
2. 알람만 보내고 사람이 확인할지
3. 해당 딜을 일시 중지할지

재고 도메인에서는 보수적으로 DB 값으로 맞추거나 딜을 잠시 막는 정책이 더 안전할 수 있다.

### 4. 테스트 결과를 더 재현 가능하게 남긴다

원문 수치인 재고 100개, 동시 요청 2,000개, p95 271ms는 좋은 결과다. 다만 이 숫자를 설계 근거로 쓰려면 아래 정보가 함께 있어야 한다.

1. k6 시나리오: VU 수, ramp-up, duration, 요청 분포
2. 사용자 분포: 모두 다른 사용자였는지, 같은 사용자의 중복 요청이 섞였는지
3. DB 커넥션 풀 크기
4. Redis와 DB 인스턴스 사양
5. 애플리케이션 인스턴스 수
6. 테스트 반복 횟수와 실패율
7. p95 외 p99, 최대 응답 시간, 에러 타입별 비율

동시성 설계는 한 번의 성공 결과보다 반복 가능한 테스트 조건이 더 중요하다.

### 5. 재고 차감과 구매 기록의 순서를 재검토한다

원문은 Redis 차감, DB 재고 차감, 구매 기록 UPSERT 순서다. 이 흐름은 이해하기 쉽지만, 한도 초과 요청도 일단 재고 차감 단계까지 들어갈 수 있다. 선검사가 대부분 걸러주긴 하지만 최종 방어는 UPSERT이므로 실패 시 보상이 필요하다.

대안은 “구매 요청을 먼저 예약하고, 재고 차감은 확정 단계에서 처리”하는 구조다. 다만 이 방식은 예약 만료, 결제 대기, 취소 복구가 필요해서 설계가 커진다. 현재 원문 구조는 짧은 타임딜과 단순 구매 확정에는 적합하지만, 결제 승인까지 포함되는 실서비스라면 예약 모델을 검토할 만하다.

### 6. 큐 기반 설계는 별도 선택지로 남긴다

Kafka 단일 파티션, Redis Stream, SQS FIFO 같은 큐를 쓰면 특정 딜의 구매 요청을 순서대로 처리할 수 있다. 그러면 단일 row version 충돌은 크게 줄어든다.

하지만 큐 방식은 사용자가 즉시 성공/실패를 받기 어렵고, “접수됨”, “처리 중”, “성공”, “실패” 같은 상태 관리가 필요하다. 따라서 요구사항이 즉시 응답인지, 순서 보장이 더 중요한지에 따라 선택해야 한다.

## 초보자를 위한 최종 설계 예시

처음부터 완벽한 대규모 구조를 만들 필요는 없다. 다음 순서로 확장하면 이해하기 쉽다.

### 1단계: DB만으로 안전하게 만들기

먼저 Redis 없이 DB 조건부 UPDATE와 UPSERT WHERE만으로 oversell과 구매 한도를 막는다.

필수 조건은 다음과 같다.

1. `time_deals.remaining_stock >= quantity` 조건으로 음수 방지
2. `time_deals.version` 조건으로 동시 업데이트 충돌 감지
3. `(time_deal_id, user_id)` 유니크 제약
4. `ON CONFLICT DO UPDATE WHERE`로 구매 한도 검증
5. 동시성 통합 테스트

이 단계에서 DB만으로 정확성이 보장되어야 한다.

### 2단계: Redis를 앞에 붙여 DB 부하 줄이기

DB 정합성이 확보된 뒤 Redis Lua 필터를 추가한다. Redis는 품절 이후 요청을 빠르게 거절하는 역할만 맡는다.

이때 반드시 필요한 것은 실패 시 Redis를 되돌리는 보상 로직이다.

### 3단계: 복구 스케줄러 추가하기

애플리케이션이 중간에 죽으면 보상 로직이 실행되지 못할 수 있다. 그래서 DB 값을 기준으로 Redis를 주기적으로 맞추는 작업을 둔다.

### 4단계: 멱등성 키 추가하기

결제, 주문 생성, 쿠폰 발급처럼 재시도가 자연스러운 API라면 idempotency key를 반드시 추가한다. 구매 한도 방어와 멱등성은 별도 문제로 다룬다.

### 5단계: 운영 지표와 알람 추가하기

다음 지표는 최소한으로 보는 것이 좋다.

1. 구매 성공 수
2. 품절 거절 수
3. 구매 한도 거절 수
4. DB version conflict 수
5. Redis rollback 성공/실패 수
6. Redis와 DB 재고 불일치 수
7. p95, p99 응답 시간
8. DB 커넥션 풀 사용률

## 면접이나 회고에서 이렇게 설명하면 좋다

이 프로젝트를 설명할 때는 “Redis로 락을 잡았다”보다 다음처럼 말하는 편이 낫다.

```text
타임딜은 단일 재고 row에 쓰기 경합이 몰리는 문제였습니다.
그래서 DB를 최종 진실로 두고, PostgreSQL 조건부 UPDATE로 oversell을 막았습니다.
다만 모든 요청이 DB에 도달하면 커넥션 풀과 row 경합이 커지므로,
Redis Lua 스크립트를 1차 필터로 두어 품절 이후 요청을 빠르게 차단했습니다.
Redis와 DB는 하나의 트랜잭션으로 묶을 수 없기 때문에,
DB 실패 시 Redis를 되돌리는 보상 핸들러와 DB 기준 복구 스케줄러를 추가했습니다.
또한 1인 구매 한도는 SELECT 후 판단하지 않고,
PostgreSQL UPSERT WHERE로 DB 안에서 원자적으로 검증했습니다.
추가로 실서비스라면 재시도 안전성을 위해 idempotency key를 별도로 둬야 합니다.
```

## 요약

원문 설계의 핵심은 Redis, Optimistic Lock, UPSERT를 각각 적절한 위치에 배치했다는 점이다.

Redis는 빠르지만 최종 진실이 아니다. DB는 느릴 수 있지만 최종 정합성을 책임져야 한다. 그래서 Redis는 DB를 보호하는 앞단 필터로 쓰고, DB는 조건부 UPDATE와 UPSERT로 최종 판단을 한다. 둘 사이가 어긋날 수 있다는 사실을 인정하고 보상 로직과 복구 스케줄러를 둔 것이 이 설계의 가장 중요한 부분이다.

다만 “UPSERT WHERE = 멱등성”은 정확하지 않다. 구매 한도 방어와 멱등성은 비슷해 보이지만 다르다. 결제와 주문 API라면 idempotency key를 별도로 저장해야 재시도에도 안전하다.

## 참고 자료

- 원문: https://ditto-dev.tistory.com/110
- Redis Lua scripting: https://redis.io/docs/latest/develop/programmability/eval-intro/
- Redis distributed locks: https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/
- PostgreSQL INSERT / ON CONFLICT: https://www.postgresql.org/docs/current/sql-insert.html
- PostgreSQL explicit locking: https://www.postgresql.org/docs/current/explicit-locking.html
- PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- Stripe idempotent requests: https://docs.stripe.com/api/idempotent_requests
