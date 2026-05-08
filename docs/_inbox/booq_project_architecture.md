# booq 프로젝트 아키텍처 문서

> **booq**은 ISBN 바코드 스캔을 통해 책 정보를 가져오고, 로컬 DB에 독서 기록과 노트를 저장하며, 통계 그래프와 독서 알림을 제공하는 Flutter 기반 독서노트 앱이다.

---

## 1. 프로젝트 개요

### 1.1 앱 이름

```txt
booq
```

### 1.2 핵심 기능

```txt
1. ISBN 바코드 스캔
2. 책 정보 조회 및 저장
3. 로컬 DB 기반 내 서재 관리
4. 독서노트 작성 및 관리
5. 독서 통계 그래프
6. 독서 리마인더 알림
```

### 1.3 개발 방향

booq은 단순한 책 검색 앱이 아니라, 사용자의 독서 데이터를 장기적으로 저장하고 분석하는 앱이다. 따라서 초기부터 다음 원칙을 기준으로 설계한다.

```txt
Offline-first
Feature-first structure
Clean Architecture
MVVM-style presentation layer
Repository pattern
Type-safe local database
Immutable state
Testable business logic
```

---

## 2. Android 개발 기준과 Flutter 대응 개념

Android/Kotlin 개발 기준으로 비교하면 booq의 Flutter 구조는 다음과 같이 대응된다.

| Android / Kotlin | Flutter / Dart |
|---|---|
| Jetpack Compose | Flutter Widget / Material 3 |
| MVVM ViewModel | Riverpod Notifier / AsyncNotifier |
| StateFlow | Riverpod State / AsyncValue / Stream |
| Coroutine | Future / Stream / async-await |
| Hilt / Dagger | Riverpod Provider DI |
| Room | Drift(SQLite) |
| Retrofit / OkHttp | Dio + Retrofit.dart |
| Navigation Compose | go_router |
| MPAndroidChart | fl_chart |
| WorkManager / AlarmManager / Notification | flutter_local_notifications |

---

## 3. 최종 추천 기술 스택

### 3.1 Core Stack

| 영역 | 추천 기술 | 목적 |
|---|---|---|
| Framework | Flutter stable | 크로스플랫폼 앱 개발 |
| Language | Dart | Flutter 기본 언어 |
| Architecture | Clean Architecture + MVVM | 관심사 분리, 테스트 용이성 |
| State Management | Riverpod | 상태관리 및 DI |
| Routing | go_router | 선언형 라우팅, deep link 대응 |
| Local DB | Drift(SQLite) | 관계형 로컬 DB, 통계 쿼리 |
| Network | Dio | HTTP client |
| API Client | Retrofit.dart | REST API client code generation |
| Model | Freezed | immutable model, union state |
| JSON | json_serializable | JSON 직렬화/역직렬화 |
| Barcode Scanner | mobile_scanner | ISBN 바코드/QR 스캔 |
| Chart | fl_chart | 통계 그래프 |
| Notification | flutter_local_notifications | 로컬 알림 |
| Timezone | timezone | 예약 알림 시간대 처리 |
| Lint | flutter_lints / very_good_analysis | 코드 품질 관리 |
| Test | flutter_test, mocktail, integration_test | 단위/위젯/통합 테스트 |

---

## 4. 아키텍처 개요

booq은 **Feature-first + Layered Clean Architecture** 구조를 사용한다.

```txt
Presentation Layer
  - Screen
  - Widget
  - ViewModel
  - UI State

Domain Layer
  - Entity
  - Value Object
  - Repository Interface
  - UseCase

Data Layer
  - Repository Implementation
  - Local DAO
  - Remote API Service
  - DTO
  - Mapper
```

### 4.1 계층별 책임

| Layer | 책임 |
|---|---|
| Presentation | UI 표시, 사용자 이벤트 전달, 화면 상태 관리 |
| Domain | 핵심 비즈니스 규칙, Entity, UseCase, Repository Interface |
| Data | API 호출, DB 접근, DTO 변환, Repository 구현 |
| Core | 공통 유틸, 에러 처리, 네트워크 설정, 공통 위젯 |
| App | 앱 진입점, 라우터, 테마, 전역 설정 |

---

## 5. 데이터 흐름

booq의 기본 데이터 흐름은 단방향으로 설계한다.

```txt
User Action
  ↓
Screen / Widget
  ↓
ViewModel / Riverpod Notifier
  ↓
UseCase
  ↓
Repository Interface
  ↓
Repository Implementation
  ↓
Local DAO / Remote API Service
  ↓
Domain Entity
  ↓
UI State
  ↓
Screen Rebuild
```

### 5.1 예시: ISBN 스캔 후 책 저장

```txt
1. 사용자가 책 뒷면 ISBN 바코드를 스캔한다.
2. ScannerScreen이 감지된 barcode 값을 ViewModel에 전달한다.
3. ScannerViewModel이 ISBN 값을 검증한다.
4. ImportBookByIsbnUseCase가 실행된다.
5. BookRepository가 로컬 DB에 해당 ISBN 책이 있는지 먼저 확인한다.
6. 로컬에 없으면 외부 도서 API를 호출한다.
7. API 결과를 Domain Entity로 변환한다.
8. 책 정보를 로컬 DB에 저장한다.
9. 저장된 책 정보를 UI State로 반환한다.
10. 화면은 책 상세 페이지로 이동한다.
```

---

## 6. 추천 폴더 구조

```txt
lib/
  main.dart
  main_dev.dart
  bootstrap.dart

  app/
    booq_app.dart
    router.dart
    theme/
      app_theme.dart
      app_colors.dart
      app_typography.dart

  core/
    config/
      app_config.dart
      env.dart
    error/
      app_exception.dart
      failure.dart
    network/
      dio_provider.dart
      interceptors.dart
    result/
      result.dart
    utils/
      isbn_validator.dart
      date_time_ext.dart
    widgets/
      booq_button.dart
      booq_text_field.dart
      async_value_view.dart
      empty_state_view.dart

  domain/
    books/
      entities/
        book.dart
        author.dart
        reading_note.dart
        reading_session.dart
        reminder.dart
      value_objects/
        isbn.dart
      repositories/
        book_repository.dart
        reading_repository.dart
        reminder_repository.dart
      use_cases/
        import_book_by_isbn.dart
        save_reading_note.dart
        get_library_books.dart
        calculate_reading_stats.dart
        schedule_reading_reminder.dart

  data/
    local/
      app_database.dart
      tables/
        books_table.dart
        reading_notes_table.dart
        reading_sessions_table.dart
        reminders_table.dart
        tags_table.dart
        book_tags_table.dart
      daos/
        book_dao.dart
        reading_dao.dart
        reminder_dao.dart
    remote/
      dto/
        kakao_book_dto.dart
        google_book_dto.dart
        naver_book_dto.dart
      services/
        kakao_books_api.dart
        google_books_api.dart
        naver_books_api.dart
        national_library_api.dart
    notification/
      local_notification_service.dart
    repositories/
      book_repository_impl.dart
      reading_repository_impl.dart
      reminder_repository_impl.dart
    mappers/
      book_mapper.dart
      reading_mapper.dart

  features/
    scanner/
      presentation/
        scanner_screen.dart
        scanner_view_model.dart
        scanner_state.dart

    library/
      presentation/
        library_screen.dart
        library_view_model.dart
        library_state.dart
        book_detail_screen.dart
        book_detail_view_model.dart
        book_detail_state.dart

    notes/
      presentation/
        note_editor_screen.dart
        note_editor_view_model.dart
        note_editor_state.dart

    stats/
      presentation/
        stats_screen.dart
        stats_view_model.dart
        stats_state.dart
        widgets/
          monthly_pages_chart.dart
          reading_time_chart.dart
          streak_card.dart

    reminders/
      presentation/
        reminder_screen.dart
        reminder_view_model.dart
        reminder_state.dart

    settings/
      presentation/
        settings_screen.dart
```

---

## 7. Presentation Layer 설계

### 7.1 역할

Presentation Layer는 UI와 화면 상태를 담당한다.

```txt
Screen
  - 화면 구성
  - 사용자 입력 감지
  - ViewModel에 이벤트 전달

ViewModel
  - UI State 관리
  - UseCase 호출
  - loading/error/success 상태 처리

State
  - 화면에 필요한 데이터만 포함
  - immutable 구조 사용
```

### 7.2 Riverpod ViewModel 예시

```dart
@riverpod
class ScannerViewModel extends _$ScannerViewModel {
  @override
  ScannerState build() => const ScannerState.idle();

  Future<void> onIsbnDetected(String rawCode) async {
    final isbn = Isbn.tryParse(rawCode);

    if (isbn == null) {
      state = const ScannerState.invalid();
      return;
    }

    state = const ScannerState.loading();

    final importBook = ref.read(importBookByIsbnProvider);
    final result = await importBook(isbn);

    state = result.when(
      success: (book) => ScannerState.success(book),
      failure: (failure) => ScannerState.error(failure.message),
    );
  }
}
```

### 7.3 UI State 예시

```dart
@freezed
sealed class ScannerState with _$ScannerState {
  const factory ScannerState.idle() = ScannerIdle;
  const factory ScannerState.loading() = ScannerLoading;
  const factory ScannerState.success(Book book) = ScannerSuccess;
  const factory ScannerState.invalid() = ScannerInvalid;
  const factory ScannerState.error(String message) = ScannerError;
}
```

---

## 8. Domain Layer 설계

### 8.1 역할

Domain Layer는 앱의 핵심 규칙을 담당한다. 외부 API, DB, Flutter UI에 의존하지 않는다.

```txt
Entity
  - 앱의 핵심 데이터 모델

Value Object
  - ISBN, 날짜 범위 등 검증이 필요한 값

Repository Interface
  - 데이터 접근 추상화

UseCase
  - 하나의 사용자 행동 또는 비즈니스 로직 단위
```

### 8.2 Book Entity 예시

```dart
@freezed
class Book with _$Book {
  const factory Book({
    required String id,
    required String isbn13,
    String? isbn10,
    required String title,
    String? subtitle,
    required List<String> authors,
    String? publisher,
    DateTime? publishedDate,
    String? description,
    String? thumbnailUrl,
    int? pageCount,
    required BookSource source,
    required DateTime createdAt,
    required DateTime updatedAt,
  }) = _Book;
}
```

### 8.3 Repository Interface 예시

```dart
abstract interface class BookRepository {
  Stream<List<Book>> watchLibraryBooks();
  Stream<Book?> watchBookById(String bookId);
  Future<Book?> findBookByIsbn(Isbn isbn);
  Future<Book> importBookByIsbn(Isbn isbn);
  Future<void> deleteBook(String bookId);
}
```

### 8.4 UseCase 예시

```dart
class ImportBookByIsbn {
  const ImportBookByIsbn(this._repository);

  final BookRepository _repository;

  Future<Result<Book>> call(Isbn isbn) async {
    try {
      final book = await _repository.importBookByIsbn(isbn);
      return Result.success(book);
    } on AppException catch (e) {
      return Result.failure(Failure.fromException(e));
    }
  }
}
```

---

## 9. Data Layer 설계

### 9.1 역할

Data Layer는 실제 데이터 입출력을 담당한다.

```txt
Repository Implementation
  - Local DAO와 Remote API Service 조합

DAO
  - Drift DB 접근

API Service
  - 외부 도서 API 호출

DTO
  - API 응답 모델

Mapper
  - DTO / DB Model / Domain Entity 변환
```

### 9.2 BookRepositoryImpl 흐름

```txt
importBookByIsbn(isbn)
  1. localDao.findByIsbn(isbn)
  2. 있으면 local book 반환
  3. 없으면 Kakao Book API 조회
  4. 실패 또는 결과 없음이면 Naver Book API 조회
  5. 실패 또는 결과 없음이면 Google Books API 조회
  6. 실패 또는 결과 없음이면 국립중앙도서관 API 조회
  7. API DTO를 Domain Book으로 변환
  8. Drift DB에 저장
  9. 저장된 Book 반환
```

---

## 10. 로컬 DB 설계

booq은 통계와 독서 기록이 중요하므로 key-value storage보다 관계형 DB가 적합하다. 따라서 Drift(SQLite)를 사용한다.

### 10.1 주요 테이블

```txt
books
reading_notes
reading_sessions
reminders
tags
book_tags
```

### 10.2 books

```txt
id TEXT PRIMARY KEY
isbn10 TEXT NULL
isbn13 TEXT UNIQUE NOT NULL
title TEXT NOT NULL
subtitle TEXT NULL
authors TEXT NOT NULL
publisher TEXT NULL
publishedDate TEXT NULL
description TEXT NULL
thumbnailUrl TEXT NULL
pageCount INTEGER NULL
source TEXT NOT NULL
status TEXT NOT NULL
rating REAL NULL
createdAt INTEGER NOT NULL
updatedAt INTEGER NOT NULL
```

### 10.3 reading_notes

```txt
id TEXT PRIMARY KEY
bookId TEXT NOT NULL
page INTEGER NULL
quote TEXT NULL
memo TEXT NOT NULL
createdAt INTEGER NOT NULL
updatedAt INTEGER NOT NULL
```

### 10.4 reading_sessions

```txt
id TEXT PRIMARY KEY
bookId TEXT NOT NULL
startedAt INTEGER NOT NULL
endedAt INTEGER NULL
pagesRead INTEGER NULL
minutes INTEGER NULL
createdAt INTEGER NOT NULL
updatedAt INTEGER NOT NULL
```

### 10.5 reminders

```txt
id TEXT PRIMARY KEY
bookId TEXT NULL
hour INTEGER NOT NULL
minute INTEGER NOT NULL
repeatRule TEXT NOT NULL
enabled INTEGER NOT NULL
createdAt INTEGER NOT NULL
updatedAt INTEGER NOT NULL
```

### 10.6 tags

```txt
id TEXT PRIMARY KEY
name TEXT UNIQUE NOT NULL
createdAt INTEGER NOT NULL
```

### 10.7 book_tags

```txt
bookId TEXT NOT NULL
tagId TEXT NOT NULL
PRIMARY KEY(bookId, tagId)
```

---

## 11. ISBN 스캔 설계

### 11.1 주의점

책 뒷면의 ISBN은 일반적으로 QR 코드가 아니라 **EAN-13 바코드** 형태다. 따라서 기능명은 내부적으로 `ISBN Scanner` 또는 `Barcode Scanner`로 두는 것이 정확하다.

### 11.2 처리 흐름

```txt
ScannerScreen
  ↓
mobile_scanner
  ↓
raw barcode value
  ↓
ISBN format filtering
  ↓
ISBN-10 / ISBN-13 validation
  ↓
ImportBookByIsbnUseCase
  ↓
BookRepository
  ↓
Local DB check
  ↓
Remote API fallback
  ↓
Save book
  ↓
Navigate to BookDetailScreen
```

### 11.3 ISBN 처리 규칙

```txt
1. raw barcode 값을 그대로 저장하지 않는다.
2. ISBN-10과 ISBN-13을 모두 파싱 가능하게 한다.
3. 저장 기준은 ISBN-13으로 통일한다.
4. check digit 검증을 통과한 값만 사용한다.
5. 이미 저장된 ISBN이면 중복 저장하지 않는다.
6. API 결과가 부족하면 사용자가 직접 수정할 수 있게 한다.
```

---

## 12. 책 정보 API 전략

국내 도서와 외서를 모두 고려해 여러 API를 fallback 구조로 사용한다.

| 우선순위 | API | 목적 |
|---:|---|---|
| 1 | Kakao Book Search API | 국내 도서 검색 우선 |
| 2 | Naver Book API | 국내 도서 보완 |
| 3 | 국립중앙도서관 ISBN API | 공식 서지정보 보완 |
| 4 | Google Books API | 외서 및 글로벌 데이터 보완 |
| 5 | Open Library API | 오픈 데이터 fallback |

### 12.1 API 조회 우선순위

```txt
1. Local DB
2. Kakao Book Search API
3. Naver Book API
4. Google Books API
5. National Library API
6. Manual input
```

### 12.2 API Key 관리

```txt
API Key는 코드에 직접 작성하지 않는다.
.env 또는 build flavor 기반으로 분리한다.
운영용/개발용 key를 분리한다.
GitHub에 key가 올라가지 않도록 관리한다.
```

---

## 13. 독서노트 설계

### 13.1 기능

```txt
책별 메모 작성
페이지 번호 기록
인용문 저장
개인 감상 저장
작성일/수정일 관리
책 상세 화면에서 노트 목록 표시
```

### 13.2 Note Editor 흐름

```txt
BookDetailScreen
  ↓
Add Note Button
  ↓
NoteEditorScreen
  ↓
NoteEditorViewModel
  ↓
SaveReadingNoteUseCase
  ↓
ReadingRepository
  ↓
ReadingNoteDao
  ↓
Local DB
```

---

## 14. 독서 통계 설계

### 14.1 통계 기준 데이터

통계는 `reading_sessions` 테이블을 기준으로 계산한다.

### 14.2 제공할 통계

```txt
월별 읽은 책 수
월별 읽은 페이지 수
주간 독서 시간
일별 독서 시간
연속 독서일 streak
책별 메모 수
태그별 책 분포
완독률
평균 완독 기간
```

### 14.3 월별 통계 SQL 예시

```sql
SELECT
  strftime('%Y-%m', datetime(started_at / 1000, 'unixepoch')) AS month,
  SUM(pages_read) AS total_pages,
  SUM(minutes) AS total_minutes
FROM reading_sessions
GROUP BY month
ORDER BY month;
```

### 14.4 통계 화면 흐름

```txt
StatsScreen
  ↓
StatsViewModel
  ↓
CalculateReadingStatsUseCase
  ↓
ReadingRepository.watchMonthlyStats()
  ↓
Drift query stream
  ↓
fl_chart
```

---

## 15. 알림 설계

### 15.1 알림 기능

```txt
매일 독서 리마인더
특정 책 읽기 알림
알림 on/off
알림 시간 변경
알림 반복 규칙 설정
```

### 15.2 알림 처리 흐름

```txt
ReminderScreen
  ↓
ReminderViewModel
  ↓
ScheduleReadingReminderUseCase
  ↓
ReminderRepository
  ↓
ReminderDao + LocalNotificationService
  ↓
flutter_local_notifications
```

### 15.3 NotificationService Interface

```dart
abstract interface class NotificationService {
  Future<void> initialize();
  Future<void> requestPermission();
  Future<void> scheduleReadingReminder(Reminder reminder);
  Future<void> cancelReminder(String reminderId);
  Future<void> cancelAll();
}
```

### 15.4 Android 권한 고려사항

```txt
Android 13 이상에서는 알림 권한 요청이 필요하다.
정확한 시간에 울리는 알림은 exact alarm 권한 처리가 필요할 수 있다.
기기 재부팅 후 알림 재등록 처리를 고려해야 한다.
```

---

## 16. 라우팅 설계

라우팅은 `go_router`를 사용한다.

```txt
/
/scan
/library
/library/:bookId
/library/:bookId/notes/new
/library/:bookId/notes/:noteId/edit
/stats
/reminders
/settings
```

### 16.1 Router 예시

```dart
final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/library',
    routes: [
      GoRoute(
        path: '/library',
        builder: (context, state) => const LibraryScreen(),
      ),
      GoRoute(
        path: '/scan',
        builder: (context, state) => const ScannerScreen(),
      ),
      GoRoute(
        path: '/library/:bookId',
        builder: (context, state) {
          final bookId = state.pathParameters['bookId']!;
          return BookDetailScreen(bookId: bookId);
        },
      ),
      GoRoute(
        path: '/stats',
        builder: (context, state) => const StatsScreen(),
      ),
      GoRoute(
        path: '/reminders',
        builder: (context, state) => const ReminderScreen(),
      ),
    ],
  );
});
```

---

## 17. 에러 처리 전략

### 17.1 에러 모델

```txt
AppException
  - NetworkException
  - DatabaseException
  - InvalidIsbnException
  - BookNotFoundException
  - PermissionException

Failure
  - UI에 표시 가능한 에러 메시지
  - 비즈니스 관점의 실패 상태
```

### 17.2 Result 타입

```dart
@freezed
sealed class Result<T> with _$Result<T> {
  const factory Result.success(T data) = Success<T>;
  const factory Result.failure(Failure failure) = FailureResult<T>;
}
```

### 17.3 원칙

```txt
1. Data Layer에서는 AppException을 던진다.
2. Domain Layer에서는 Result 또는 Failure로 변환한다.
3. Presentation Layer에서는 사용자에게 보여줄 메시지만 처리한다.
4. API 응답 DTO를 UI에 직접 넘기지 않는다.
5. stack trace와 사용자 메시지를 분리한다.
```

---

## 18. pubspec.yaml 초안

```yaml
dependencies:
  flutter:
    sdk: flutter

  # state / dependency injection
  flutter_riverpod:
  riverpod_annotation:

  # routing
  go_router:

  # network
  dio:
  retrofit:
  json_annotation:

  # model / immutable state
  freezed_annotation:

  # local database
  drift:
  drift_flutter:

  # scanner
  mobile_scanner:

  # chart
  fl_chart:

  # notification
  flutter_local_notifications:
  timezone:

  # utility
  permission_handler:
  cached_network_image:
  shared_preferences:
  path_provider:
  uuid:
  intl:

dev_dependencies:
  flutter_test:
    sdk: flutter

  # code generation
  build_runner:
  riverpod_generator:
  retrofit_generator:
  json_serializable:
  freezed:
  drift_dev:

  # lint
  flutter_lints:
  riverpod_lint:
  custom_lint:

  # test
  mocktail:
  integration_test:
    sdk: flutter
```

---

## 19. 코드 생성 명령어

```bash
flutter pub get
```

```bash
dart run build_runner build --delete-conflicting-outputs
```

watch mode:

```bash
dart run build_runner watch --delete-conflicting-outputs
```

---

## 20. 테스트 전략

### 20.1 테스트 종류

| 테스트 | 대상 |
|---|---|
| Unit Test | ISBN 검증, UseCase, 통계 계산 |
| Repository Test | API mock + Drift in-memory DB |
| ViewModel Test | Riverpod provider override |
| Widget Test | 주요 화면 UI 상태 검증 |
| Integration Test | 스캔 → 저장 → 상세 이동 플로우 |

### 20.2 우선 작성할 테스트

```txt
1. ISBN-10 / ISBN-13 validator test
2. ImportBookByIsbnUseCase test
3. BookRepositoryImpl local-first test
4. ReadingStats calculation test
5. ScannerViewModel state transition test
6. Reminder scheduling test
```

---

## 21. 개발 순서

### 21.1 MVP 1차 범위

```txt
1. 프로젝트 생성
2. 앱 테마 구성
3. go_router 구성
4. Riverpod bootstrap 구성
5. Drift DB schema 작성
6. ISBN value object 작성
7. Kakao 또는 Google Books API 1개 연동
8. BookRepository.importBookByIsbn 구현
9. mobile_scanner로 ISBN 스캔 구현
10. 내 서재 화면 구현
11. 책 상세 화면 구현
12. 독서노트 CRUD 구현
13. 독서 세션 기록 구현
14. 기본 통계 화면 구현
15. 로컬 알림 구현
```

### 21.2 MVP 이후 확장

```txt
태그 기능
검색/필터 기능
완독 목표 설정
책 표지 캐싱
백업/복원
Cloud sync
OAuth 로그인
커뮤니티 기능
추천 기능
AI 요약/메모 보조 기능
```

---

## 22. 설계 원칙

### 22.1 반드시 지킬 것

```txt
UI에서 API를 직접 호출하지 않는다.
UI에서 DB를 직접 접근하지 않는다.
DTO를 UI로 넘기지 않는다.
Entity는 Domain Layer에 둔다.
비즈니스 로직은 ViewModel 또는 UseCase에 둔다.
복잡한 로직은 UseCase로 분리한다.
Local DB를 source of truth로 본다.
ISBN은 저장 전 반드시 검증한다.
pubspec.lock은 커밋한다.
API Key는 Git에 올리지 않는다.
```

### 22.2 피해야 할 것

```txt
모든 파일을 lib/screens 안에 몰아넣기
Widget 안에서 Dio 호출하기
Widget 안에서 Drift DAO 호출하기
API 응답 모델을 화면에서 직접 사용하기
상태를 mutable class로 관리하기
통계 데이터를 매번 Dart에서만 계산하기
ISBN 중복 저장 허용하기
알림 권한 예외 처리를 누락하기
```

---

## 23. 최종 아키텍처 요약

booq의 최종 추천 구성은 다음과 같다.

```txt
Architecture:
  Feature-first Clean Architecture + MVVM

State / DI:
  Riverpod + code generation

Routing:
  go_router

Local DB:
  Drift(SQLite)

Network:
  Dio + Retrofit.dart

Model:
  Freezed + json_serializable

Scanner:
  mobile_scanner

Book Metadata API:
  Kakao Book Search API
  Naver Book API
  Google Books API
  National Library API

Chart:
  fl_chart

Notification:
  flutter_local_notifications + timezone

Lint / Test:
  flutter_lints or very_good_analysis
  riverpod_lint
  mocktail
  flutter_test
  integration_test
```

---

## 24. 한 줄 정리

```txt
booq은 Flutter 공식 MVVM 흐름을 기반으로 Riverpod ViewModel, Drift offline-first DB, Repository API fallback, mobile_scanner ISBN import를 사용하는 2026년형 독서노트 앱 구조로 설계한다.
```
