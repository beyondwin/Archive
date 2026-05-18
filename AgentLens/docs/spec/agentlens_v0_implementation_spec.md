# AgentLens v0 상세 구현 명세 (Implementation Spec)

> 본 문서는 `docs/adr/agentlens_architecture_proposal.md`(아키텍처)와 `docs/plan/agentlens_v0_detailed_plan.md`(플랜)의 동반 문서다. **엔지니어가 코드를 쓰기 직전에 펼쳐놓는 청사진**으로, 모듈 책임 / 함수 시그니처 / 핵심 알고리즘 의사 코드 / 데이터 모델 / 동시성 / 테스트 전략을 한 곳에 모은다.

---

## 0. 사용 규칙

- 이 문서의 시그니처와 실제 코드가 어긋나면 **이 문서가 우선**한다 (구현 PR이 따라잡거나, 시그니처 변경을 명시적으로 spec PR로 올린다).
- `# TODO(M?)` 주석은 마일스톤 표시. 본문은 모두 v0 범위 한정.
- Python 3.11+. 런타임 의존성: `typer`, `jsonschema`. `pydantic` 모델은 선택적 생성물이며 JSON Schema 계약을 대체하지 않는다. `click`은 Typer의 transitive dependency로만 사용하고 직접 의존하지 않는다. 외부 observability/네트워크 SDK 금지.

---

## 1. 시스템 개요

```
┌───────────────────────────────────────────────────────────┐
│                       AgentLens CLI                       │
│  (Typer entrypoint: cli.py — start/mark/final/seal/eval/  │
│   show/latest/status/failures/risks/install/doctor/gc/run)│
└───────────────────────────────────────────────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────┐         ┌─────────────────────────┐
│ store/              │         │ adapters/               │
│  paths, writer,     │         │  process (wrapper),     │
│  manifest, sqlite,  │         │  shims, claude,         │
│  query, retention   │         │  codex_cli, codex_app,  │
└─────────────────────┘         │  generic                │
            │                   └─────────────────────────┘
            ▼                              │
┌─────────────────────┐                    │
│ schema/             │                    │
│  jsonschema/*.json  │◄───────────────────┘
│  validate, models   │
└─────────────────────┘
            │
            ▼
┌─────────────────────┐
│ evaluator/          │
│  checks, engine,    │
│  failures           │
└─────────────────────┘
            │
            ▼
┌─────────────────────┐
│ redaction/          │
│  patterns, redact   │
└─────────────────────┘
```

**불변 규칙**
1. JSON artifact는 항상 **store/writer.py** 를 거쳐 atomic write.
2. SQLite write는 **best-effort**, 실패 시 swallow + log. JSON write 실패는 raise.
3. 모든 외부에서 들어오는 문자열(command argv, path, excerpt)은 **redaction/redact.py** 통과 후 저장.
4. evaluator는 read-only — durable store를 절대 mutate하지 않는다.
5. writer는 redaction 적용 후 최종 persisted document를 schema validate한다. redaction 때문에 schema-invalid artifact가 디스크에 남으면 안 된다.
6. `agentlens run`은 run 초기화 실패가 child command 실행을 막지 않는다. child spawn 전 AgentLens write가 실패하면 recording을 포기하고 passthrough로 실행한다.
7. query command는 `store/query.py` facade만 호출한다. `store/sqlite_index.py`를 직접 호출하지 않는다.

---

## 2. 모듈 책임 매트릭스

| 모듈 | 책임 | 책임 아님 |
|---|---|---|
| `cli.py` | Typer 엔트리포인트, sub-command dispatch | 비즈니스 로직 |
| `config.py` | priority chain 해석, `AGENTLENS_DISABLE` 처리 | 파일 IO |
| `constants.py` | 매직 상수 (`SCHEMA_*`, `MAX_EXCERPT_CHARS`, `DEFAULT_MODE`) | 함수 |
| `ids.py` | workspace_id, run_id, event_id 생성 | path 결정 |
| `time.py` | UTC ISO8601 직렬화/검증 | 외부 NTP |
| `store/paths.py` | `~/.agentlens` 와 workspace 경로 결정 | mkdir |
| `store/writer.py` | atomic write, jsonl append, flock | hashing |
| `store/manifest.py` | two-phase seal, hash collection | redaction |
| `store/sqlite_index.py` | SQLite schema, index_run, rebuild | source of truth, fallback 결정 |
| `store/query.py` | query facade, SQLite/full-scan fallback | SQLite schema mutation |
| `store/retention.py` | GC 정책, dry-run | 권한 검사 |
| `schema/validate.py` | jsonschema 로드 + draft 2020-12 validation | 자동 마이그레이션 |
| `schema/models.py` | 선택적 jsonschema → pydantic 생성물 | 계약 source of truth |
| `evaluator/checks.py` | 12개 check 함수 | failure 분류 |
| `evaluator/engine.py` | check 실행 순서, status 해소, eval.json 작성 | check 로직 |
| `evaluator/failures.py` | taxonomy (category enum, multi-axis) | check 실행 |
| `redaction/patterns.py` | 정규식 + allow-list extractor 정의 | apply |
| `redaction/redact.py` | apply, mask, hash-preserving 변환 | 패턴 정의 |
| `adapters/process.py` | child spawn, signal, exit code 보존 | shim install |
| `adapters/shims.py` | shim 템플릿, lockfile, permissions | PATH 수정 (commands/install.py가 함) |
| `adapters/claude.py` | Claude probe + install/uninstall | hooks 실행 |
| `adapters/codex_cli.py` | Codex CLI probe + shim install hook | session watcher |
| `adapters/codex_app.py` | watcher + app-server probe | shim |
| `commands/*.py` | 각 sub-command body | 모든 IO를 store/* 통해서만 |

---

## 3. 디렉터리 / 파일 트리

`docs/adr/agentlens_v0_task_breakdown.md` §1과 동일. 본 문서에서는 신규 추가 또는 책임 변경만 명시.

추가 파일:

```
src/agentlens/
  __main__.py              # python -m agentlens 진입점
  schema/check_drift.py    # CI에서 jsonschema vs examples 일치 검사
  store/lock.py            # fcntl/flock wrapper (writer가 사용)
  store/query.py           # SQLite/full-scan query facade
docs/
  spec/
    agentlens_v0_implementation_spec.md   # 본 문서
  plan/
    agentlens_v0_detailed_plan.md
  adr/
    agentlens_architecture_proposal.md
    agentlens_v0_task_breakdown.md
```

---

## 4. 핵심 데이터 모델 (JSON Schema 요지)

각 스키마의 **필수 필드 / 옵션 필드 / enum / 검증 규칙**을 한 곳에 모은다. 실제 schema 파일은 `src/agentlens/schema/jsonschema/*.json`.

공통 규칙:
- `additionalProperties: false`
- 모든 timestamp: regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$`
- 모든 해시: `^sha256:[a-f0-9]{64}$`
- JSON Schema 파일은 JSON 문법을 유지한다. 버전 정책은 `#` 주석이 아니라 top-level `$comment`에 기록한다.

### 4.1 `run.json` (`agentlens.run.v1`)

```text
required:
  schema           const "agentlens.run.v1"
  run_id           string, matches ^run_\d{8}_\d{6}_[a-z0-9]{6}$
  workspace_id     string, matches ^ws_[a-f0-9]{16}$
  started_at       timestamp
  agent:
    name           enum: claude_code | codex_cli | codex_app | generic
    mode           enum: cli | app | code | unknown
  workspace:
    root_label     string (basename or git repo name)
    root_hash      sha256
    id_basis       enum: git | path
  recording:
    mode           enum: minimal | full   ← run 도중 변경 불가
    adapter        string

optional:
  parent_run_id    string | null
  agent.version    string
  workspace.git_remote_hash    sha256
  workspace.git_branch         string
  workspace.commit_before      string (git sha)
  input.kind                   string
  input.summary                string (≤ 4096)
  input.hash                   sha256
```

### 4.2 `events.jsonl` (`agentlens.event.v1`, line-delimited)

```text
required (per line):
  schema           const "agentlens.event.v1"
  event_id         string, matches ^evt_[a-z0-9]{12}$
  run_id           string (run.json와 동일)
  ts               timestamp
  type             enum (아래)
  payload          object

type enum:
  run.started
  checkpoint.marked
  command.started
  command.finished
  artifact.attached
  task.started
  task.finished
  failure.observed
  run.finalized
  run.cancelled

payload (type별):
  run.started:        {}
  checkpoint.marked:  {"name": string}
  command.started:    {"command_hash": sha256, "argv_excerpt": string?}
  command.finished:   {"command_hash": sha256, "exit_code": int,
                       "duration_ms": int, "stdout_excerpt": string?,
                       "stderr_excerpt": string?}
  artifact.attached:  {"kind": string, "path_label": string,
                       "path_hash": sha256, "sha256": sha256}
  task.started:       {"task_id": string, "label": string?}
  task.finished:      {"task_id": string, "status": "ok"|"fail"|"skip"}
  failure.observed:   {"category": string, "severity": string,
                       "summary": string, "evidence": [string]}
  run.finalized:      {"agent_outcome": string}
  run.cancelled:      {"signal": string, "reason": string?}
```

### 4.3 `final.json` (`agentlens.final.v1`)

```text
required:
  schema           const "agentlens.final.v1"
  run_id           string
  ended_at         timestamp
  agent_outcome    enum: success | failed | partial | cancelled | unknown
  summary          string (≤ 4096)
  changed_files    array of { path_label: string, path_hash: sha256 }
  verification     array of {
                     kind: enum "command"|"test"|"manual",
                     command_hash: sha256,
                     status: enum "passed"|"failed"|"skipped",
                     excerpt: string (≤ 4096)
                   }
  residual_risks   array of {
                     severity: enum low|medium|high|critical,
                     summary: string (≤ 4096)
                   }

optional (when agent_outcome == "cancelled"):
  exit_signal      enum SIGINT | SIGTERM | SIGHUP | other
  exit_code        integer

optional:
  no_changes_reason string (≤ 4096)
                   required by evaluator when agent_outcome="success" and
                   changed_files is empty. This avoids false failures for
                   research/no-op runs while still forcing explicitness.
```

### 4.4 `eval.json` (`agentlens.eval.v1`)

```text
required:
  schema           const "agentlens.eval.v1"
  run_id           string
  evaluated_at     timestamp
  status           enum: passed | failed | incomplete | needs_eval | error
  agent_outcome    enum: success | failed | partial | cancelled | unknown
  checks           array of {
                     name: string,
                     status: enum passed|failed|skipped,
                     message: string?,
                     evidence: [string]?
                   }
  failures         array of {
                     category: enum (§4.5),
                     severity: enum low|medium|high|critical,
                     source: enum agent_reported|evaluator|user_reported|imported,
                     blame_scope: enum agent|project|environment|user|unknown,
                     recoverability: enum informational|retry|rerun_or_fix|needs_user|non_recoverable,
                     confidence: number in [0, 1] (round to 2 decimals),
                     summary: string (≤ 4096),
                     evidence: [string]
                   }
```

### 4.5 Failure Category 열거

```text
MISSING_FINAL
INVALID_RUN_SCHEMA
INVALID_EVENT_SCHEMA
INVALID_FINAL_SCHEMA
INVALID_MANIFEST_SCHEMA
MISSING_VERIFICATION_EVIDENCE
UNACKNOWLEDGED_FAILED_COMMAND
SUCCESS_WITH_RESIDUAL_RISK
ARTIFACT_HASH_MISMATCH
MANIFEST_NOT_SEALED
RECORDING_INCOMPLETE
EVALUATOR_ERROR
COMMAND_TIMEOUT
ENVIRONMENT_BLOCKER
DIFF_SCOPE_UNKNOWN
CHANGED_FILES_MISSING
AGENT_REPORTED_GAP
USER_CORRECTION
UNKNOWN
```

### 4.6 `manifest.json` (`agentlens.manifest.v1`)

```text
required:
  schema           const "agentlens.manifest.v1"
  run_id           string
  sealed_at        timestamp
  sealed           boolean
  sealed_phase     enum pre_eval | final | recording_incomplete
  files            array of { path: string, sha256: sha256 }
  redaction:
    absolute_paths           const "masked"
    secret_like_values       const "masked"
    full_prompts             enum "not_stored"|"hashed"
    full_command_output      enum "not_stored"|"excerpted"
```

---

## 5. 모듈별 함수 시그니처

타입 어노테이션은 Python 3.11+ 문법(`list[T]`, `T | None`).

### 5.1 `constants.py`

```python
SCHEMA_RUN_V1 = "agentlens.run.v1"
SCHEMA_EVENT_V1 = "agentlens.event.v1"
SCHEMA_FINAL_V1 = "agentlens.final.v1"
SCHEMA_EVAL_V1 = "agentlens.eval.v1"
SCHEMA_MANIFEST_V1 = "agentlens.manifest.v1"

MAX_EXCERPT_CHARS = 4096
MAX_SUMMARY_CHARS = 4096
DEFAULT_MODE = "minimal"

EVENT_TYPES = frozenset({
    "run.started", "checkpoint.marked", "command.started", "command.finished",
    "artifact.attached", "task.started", "task.finished", "failure.observed",
    "run.finalized", "run.cancelled",
})

AGENT_OUTCOMES = frozenset({"success", "failed", "partial", "cancelled", "unknown"})
SEAL_PHASES = frozenset({"pre_eval", "final", "recording_incomplete"})
```

### 5.2 `time.py`

```python
def utc_now_iso() -> str: ...
"""현재 시각을 'YYYY-MM-DDTHH:MM:SS.ffffffZ' 형식으로 반환."""

def validate_iso8601_utc(s: str) -> bool: ...
"""regex로 검증. naive 또는 non-UTC는 False."""

def normalize_for_diff(s: str) -> str: ...
"""determinism 회귀에서 timestamp 자리 0으로 치환."""
```

### 5.3 `ids.py`

```python
def make_run_id(now: datetime | None = None) -> str: ...
"""형식 run_YYYYMMDD_HHMMSS_xxxxxx (xxxxxx: 6글자 random a-z0-9)."""

def make_event_id() -> str: ...
"""형식 evt_xxxxxxxxxxxx (12글자 random)."""

def compute_workspace_id(root: Path) -> tuple[str, Literal["git","path"], dict]:
    """
    Returns (workspace_id, id_basis, metadata)
    metadata contains git_remote_hash, git_branch 등 옵션 필드 hint.

    알고리즘:
      1. <root>/.agentlens/config.yaml에 workspace_id가 있으면 그 값을 우선 사용.
         이 persisted id가 workspace move 시 안정성을 보장한다.
      2. root에서 위로 올라가며 git toplevel 찾기.
      3. git remote -v 호출 → "origin" 우선, 없으면 첫 remote.
      4. remote 존재 시:
         remote_normalized = normalize_git_remote(remote)
         rel_path = relpath(root, git_toplevel)
         worktree_identity = sha256(realpath(git_toplevel)).hex()[:16]
         basis = "git"
         basis_input = "git:" + remote_normalized + ":" + rel_path + ":" + worktree_identity
         최초 계산 결과를 workspace config에 persist.
      5. remote 없음 또는 git 외부:
         host_id = sha256(socket.gethostname()).hex()[:16]
         basis = "path"
         basis_input = "path:" + host_id + ":" + sha256(realpath(root)).hex()
         최초 계산 결과를 workspace config에 persist.
      6. workspace_id = "ws_" + sha256(basis_input).hex()[:16]

    normalize_git_remote(remote):
      - https://host/org/repo.git        -> host/org/repo
      - ssh://git@host/org/repo.git      -> host/org/repo
      - git@host:org/repo.git            -> host/org/repo
      - lowercase host only; preserve path case to avoid collisions on
        case-sensitive providers.
    """
```

### 5.4 `store/paths.py`

```python
def agentlens_home() -> Path:
    """$AGENTLENS_HOME or ~/.agentlens. 존재 보장 안 함."""

def run_dir(workspace_id: str, run_id: str) -> Path:
    """~/.agentlens/runs/<workspace_id>/<run_id>/"""

def workspace_local(root: Path) -> Path:
    """<root>/.agentlens"""

def current_run_marker(root: Path, run_id: str) -> Path:
    """<root>/.agentlens/current-runs/<run_id>  (디렉터리 마커, 동시 다중 run 허용)"""

def safe_label_path(absolute_path: Path, workspace_root: Path) -> str:
    """absolute path → workspace-relative label. workspace 외부면 'EXTERNAL:<hash>'."""
```

### 5.5 `store/lock.py`

```python
@contextmanager
def file_lock(path: Path, mode: Literal["exclusive","shared"] = "exclusive") -> Iterator[None]:
    """
    fcntl.flock 기반 advisory lock.
    timeout 5s, 초과 시 LockTimeoutError raise.
    한 run의 events.jsonl 쓰기마다 exclusive lock 획득.
    """
```

### 5.6 `store/writer.py`

```python
def atomic_write_json(path: Path, data: dict, *, redact: bool = True) -> None:
    """
    1. data의 최소 구조 확인 (dict, schema field 존재)
    2. redact 이면 redaction/redact.apply_to_doc()
    3. redaction 후 최종 persisted doc 검증 (schema 추론 by data["schema"])
    4. tempfile.NamedTemporaryFile(dir=path.parent) → fsync → os.rename
    5. 실패 시 RaiseWriteError (raise; 호출측이 처리)
    """

def append_event(run_dir: Path, event: dict) -> None:
    """
    1. event 최소 구조 확인
    2. redaction 적용
    3. redaction 후 event 검증
    4. file_lock(events.jsonl, exclusive)
    5. open(append, buffering=0)
    6. write json + '\n'
    7. fsync
    """

def write_final(run_dir: Path, final: dict) -> None: ...
def write_run_meta(run_dir: Path, run: dict) -> None: ...
def write_workspace_pointer(workspace_root: Path, run_id: str, run_dir: Path) -> None: ...
```

### 5.7 `store/manifest.py`

```python
@dataclass(frozen=True)
class ManifestEntry:
    path: str       # run_dir 기준 상대경로
    sha256: str

def collect_files(run_dir: Path, *, include_eval: bool) -> list[ManifestEntry]:
    """
    run.json, events.jsonl, final.json, manifest.json 제외(자기 자신), artifacts/** 포함.
    include_eval=True 이면 eval.json 추가.
    각 파일에 대해 sha256 hex digest 계산.
    파일이 없으면 skip (final.json은 없을 수도 있음 — recording_incomplete 케이스).
    결과는 path 알파벳 순 정렬.
    """

def seal(run_dir: Path, phase: Literal["pre_eval","final","recording_incomplete"]) -> None:
    """
    1. entries = collect_files(run_dir, include_eval=(phase == "final"))
    2. manifest = {
         schema, run_id, sealed_at=now(), sealed=True, sealed_phase=phase,
         files=entries, redaction=current_policy(),
       }
    3. atomic_write_json(run_dir/"manifest.json", manifest, redact=False)
       # manifest 자체는 redaction 대상 아님; 단 path는 이미 label.
    """

def verify(run_dir: Path) -> list[ManifestEntry]:
    """sha256 재계산 후 manifest와 비교. 불일치 항목 리스트 반환."""
```

### 5.8 `store/sqlite_index.py`

```python
def open_db(path: Path | None = None) -> sqlite3.Connection: ...

def init_schema(conn: sqlite3.Connection) -> None:
    """
    CREATE TABLE runs (
      run_id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      parent_run_id TEXT,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      agent_name TEXT NOT NULL,
      agent_mode TEXT NOT NULL,
      recording_mode TEXT NOT NULL,
      agent_outcome TEXT,
      eval_status TEXT,
      sealed_phase TEXT
    );
    CREATE INDEX idx_runs_workspace ON runs(workspace_id, started_at DESC);
    CREATE INDEX idx_runs_eval_status ON runs(eval_status);

    CREATE TABLE checks (
      run_id TEXT, name TEXT, status TEXT, message TEXT,
      PRIMARY KEY (run_id, name)
    );

    CREATE TABLE failures (
      run_id TEXT, category TEXT, severity TEXT, source TEXT,
      blame_scope TEXT, summary TEXT,
      FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );

    CREATE TABLE artifacts (
      run_id TEXT, path TEXT, sha256 TEXT,
      PRIMARY KEY (run_id, path)
    );
    """

def index_run(conn: sqlite3.Connection, run_dir: Path) -> None:
    """run.json/final.json/eval.json/manifest.json을 읽어 모든 테이블에 upsert."""

def rebuild_index(home: Path) -> int:
    """home/runs/**/run.json 전부 스캔해 index 재생성. return: indexed run count."""
```

**원칙**: 본 모듈은 SQLite schema/upsert/rebuild primitive만 제공한다. CLI query command가 이 모듈을 직접 호출하면 안 된다.

### 5.8a `store/query.py`

```python
def latest(home: Path, workspace_id: str | None = None) -> dict | None:
    """SQLite가 정상일 때는 index를 사용하고, 없거나 손상되면 full-scan."""

def failures(home: Path, *, since_days: int = 30) -> list[dict]:
    """eval.json failures를 durable store 기준으로 반환. SQLite는 cache."""

def risks(home: Path, *, since_days: int = 30) -> list[dict]:
    """
    final.residual_risks + eval.failures + manifest.sealed_phase=="recording_incomplete"
    indicators를 합쳐 반환한다. recording_incomplete는 category
    RECORDING_INCOMPLETE로 normalize한다.
    """

def full_scan_runs(home: Path) -> list[dict]:
    """home/runs/**/run.json을 스캔하고 schema-invalid run은 risk로 surfaced."""
```

Fallback 규칙:
- SQLite file 없음 → full-scan.
- SQLite open/query 실패 → 경고 로그 후 full-scan.
- SQLite rebuild 실패 → full-scan 결과를 반환하고 child/user command exit code에 영향 없음.

### 5.9 `store/retention.py`

```python
@dataclass
class RetentionPolicy:
    sealed_runs_days: int = 30
    large_artifacts_days: int = 7
    max_artifact_mb_per_run: int = 50
    max_total_store_gb: int = 5
    keep_eval_summaries: bool = True

def gc(home: Path, policy: RetentionPolicy, *, dry_run: bool) -> GcReport:
    """
    1. run 디렉터리 전부 스캔 (SQLite 사용하지 않음)
    2. 정렬: started_at ASC
    3. for each run:
       - sealed_phase != "final" 이고 sealed_runs_days 초과 → 후보
       - artifacts/ 중 large_artifacts_days 초과 → 후보
       - max_artifact_mb_per_run 초과 oversize artifact → 후보
    4. 누적 store 크기 > max_total_store_gb 시 oldest sealed run의 artifact부터 추가 후보 (eval/final/manifest 보존)
    5. dry_run=False 이면 실제 삭제 + reindex
    Returns GcReport with deleted_paths, freed_bytes, kept_summaries.
    """
```

### 5.10 `schema/validate.py`

```python
def load_schema(name: Literal["run","event","final","eval","manifest"]) -> dict: ...

def validate_doc(doc: dict, *, schema_name: str | None = None) -> None:
    """
    schema_name 미지정 시 doc["schema"] 로 추론.
    jsonschema.Draft202012Validator.iter_errors() 모두 모아 SchemaError raise.
    """

def validate_event_line(line: str) -> dict:
    """json.loads → validate_doc(schema='event'). bad line은 EventLineError raise."""
```

### 5.11 `redaction/patterns.py`

```python
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("stripe_key", re.compile(r"\b(?:pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("aws_key",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("auth_header", re.compile(r"(?im)^authorization:\s*\S+")),
    ("bearer",     re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----")),
]

HOME_PREFIXES: list[str] = [str(Path.home()), "/Users/", "/home/"]

EXCERPT_EXTRACTORS: dict[str, Callable[[str], str | None]] = {
    "pytest_summary": _extract_pytest_summary,   # "12 passed, 1 failed" 한 줄
    "exit_code_line": _extract_exit_code,        # "exited with code N"
    "error_type": _extract_error_type,           # "TypeError: ..."
    # 추가 시 allow-list 원칙 유지
}
```

### 5.12 `redaction/redact.py`

```python
def mask_secret(text: str) -> str:
    """SECRET_PATTERNS 적용. 매치는 '<REDACTED:{kind}>'로 치환."""

def mask_path(text: str, workspace_root: Path | None = None) -> str:
    """
    1. workspace_root 있으면 그 prefix는 './'로 치환
    2. HOME_PREFIXES 매치는 '<HOME>/<HASH8>'로 치환
    """

def make_excerpt(raw: str, *, extractor: str) -> str | None:
    """EXCERPT_EXTRACTORS[extractor]만 호출. 결과는 MAX_EXCERPT_CHARS 이하."""

def apply_to_doc(doc: dict, *, workspace_root: Path | None = None) -> dict:
    """
    재귀 순회. str 필드에 mask_secret + mask_path 적용.
    'path_label' 키는 mask_path 강제. excerpt 키는 길이 검사.
    protected key는 변형 금지:
      schema, run_id, workspace_id, event_id, parent_run_id,
      *_hash, sha256, status, type, category, severity, source,
      blame_scope, recoverability, sealed_phase, agent_outcome.
    """
```

### 5.13 `evaluator/failures.py`

```python
class FailureCategory(StrEnum):
    MISSING_FINAL = "MISSING_FINAL"
    INVALID_RUN_SCHEMA = "INVALID_RUN_SCHEMA"
    INVALID_EVENT_SCHEMA = "INVALID_EVENT_SCHEMA"
    INVALID_FINAL_SCHEMA = "INVALID_FINAL_SCHEMA"
    INVALID_MANIFEST_SCHEMA = "INVALID_MANIFEST_SCHEMA"
    MISSING_VERIFICATION_EVIDENCE = "MISSING_VERIFICATION_EVIDENCE"
    UNACKNOWLEDGED_FAILED_COMMAND = "UNACKNOWLEDGED_FAILED_COMMAND"
    SUCCESS_WITH_RESIDUAL_RISK = "SUCCESS_WITH_RESIDUAL_RISK"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    MANIFEST_NOT_SEALED = "MANIFEST_NOT_SEALED"
    RECORDING_INCOMPLETE = "RECORDING_INCOMPLETE"
    EVALUATOR_ERROR = "EVALUATOR_ERROR"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
    ENVIRONMENT_BLOCKER = "ENVIRONMENT_BLOCKER"
    DIFF_SCOPE_UNKNOWN = "DIFF_SCOPE_UNKNOWN"
    CHANGED_FILES_MISSING = "CHANGED_FILES_MISSING"
    AGENT_REPORTED_GAP = "AGENT_REPORTED_GAP"
    USER_CORRECTION = "USER_CORRECTION"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class Failure:
    category: FailureCategory
    severity: Literal["low","medium","high","critical"]
    source: Literal["agent_reported","evaluator","user_reported","imported"]
    blame_scope: Literal["agent","project","environment","user","unknown"]
    recoverability: Literal["informational","retry","rerun_or_fix","needs_user","non_recoverable"]
    confidence: float    # [0,1], rounded 2 dp
    summary: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict: ...
```

### 5.14 `evaluator/checks.py`

각 체크는 동일한 시그니처를 가진다. `Context`는 run 디렉터리에서 로드한 4종 JSON 묶음.

```python
@dataclass
class EvalContext:
    run: dict
    events: list[dict]
    final: dict | None       # 없을 수 있음
    manifest: dict | None    # 없을 수 있음
    run_dir: Path

@dataclass
class CheckResult:
    name: str
    status: Literal["passed","failed","skipped"]
    message: str | None = None
    evidence: tuple[str, ...] = ()
    failures: tuple[Failure, ...] = ()

CheckFn = Callable[[EvalContext], CheckResult]

# 12개 체크 (선언 순서는 evaluator/engine.py의 실행 순서와 무관)
def check_schema_valid(ctx) -> CheckResult: ...
def check_run_started(ctx) -> CheckResult: ...
def check_events_well_formed(ctx) -> CheckResult: ...
def check_final_present(ctx) -> CheckResult: ...
def check_agent_outcome_valid(ctx) -> CheckResult: ...
def check_verification_present(ctx) -> CheckResult: ...
def check_commands_resolved(ctx) -> CheckResult: ...
def check_failed_commands_acknowledged(ctx) -> CheckResult: ...
def check_changed_files_present_when_success(ctx) -> CheckResult: ...
def check_residual_risks_explicit(ctx) -> CheckResult: ...
def check_manifest_sealed(ctx) -> CheckResult: ...
def check_artifact_hashes_valid(ctx) -> CheckResult: ...

REQUIRED_CHECKS: tuple[CheckFn, ...] = (
    check_schema_valid,
    check_run_started,
    check_events_well_formed,
    check_final_present,
    check_agent_outcome_valid,
    check_verification_present,
    check_commands_resolved,
    check_failed_commands_acknowledged,
    check_changed_files_present_when_success,
    check_residual_risks_explicit,
    check_manifest_sealed,
    check_artifact_hashes_valid,
)
```

`check_changed_files_present_when_success` rule:
- If `agent_outcome != "success"`: `skipped`.
- If `changed_files` has entries: `passed`.
- If `changed_files=[]` and `final.no_changes_reason` is non-empty: `passed` with informational message.
- If `changed_files=[]` and no reason is present: `failed` with category `DIFF_SCOPE_UNKNOWN`.

### 5.15 `evaluator/engine.py`

```python
def load_context(run_dir: Path) -> EvalContext: ...

def evaluate(run_dir: Path) -> dict:
    """
    1. try ctx = load_context(run_dir)
       except Exception as e:
         eval_doc = _minimal_error_eval(run_dir, e)
         atomic_write_json(run_dir/"eval.json", eval_doc, redact=False)
         return eval_doc
    2. results: list[CheckResult] = []
       failures: list[Failure] = []
       internal_error = False
       for fn in REQUIRED_CHECKS:
         try:
           r = fn(ctx)
           results.append(r)
           failures.extend(r.failures)
         except Exception as e:
           internal_error = True
           results.append(CheckResult(fn.__name__, "failed",
                                      message=f"check raised: {e!r}"))
           failures.append(Failure(
             category=FailureCategory.EVALUATOR_ERROR,
             severity="high",
             source="evaluator",
             blame_scope="unknown",
             recoverability="rerun_or_fix",
             confidence=1.0,
             summary=f"Evaluator check {fn.__name__} raised",
             evidence=(repr(e),),
           ))

    3. status = "error" if internal_error else resolve_status(ctx, results)
    4. eval_doc = {
         schema, run_id, evaluated_at,
         status,
         agent_outcome=(ctx.final or {}).get("agent_outcome","unknown"),
         checks=sorted(results, key=lambda r: r.name),
         failures=[f.to_dict() for f in sorted(failures, key=lambda f: f.category.value)],
       }
    5. validate_doc(eval_doc)
    6. atomic_write_json(run_dir/"eval.json", eval_doc, redact=False)
    7. return eval_doc

def resolve_status(ctx, results) -> Literal["passed","failed","incomplete","needs_eval","error"]:
    """
    final 없음                          -> "incomplete"
    필수 check 중 status="failed" 1개+ -> "failed"
    모두 passed/skipped(허용된 것만)  -> "passed"
    """
```

**status 해소 표:**

| 조건 | 결과 |
|---|---|
| evaluator 내부 raise | `error` |
| `final.json` 없음 | `incomplete` |
| `check_schema_valid` failed | `failed` |
| 필수 check 1개 이상 failed | `failed` |
| `agent_outcome=success` & medium+ residual risk | `failed` (`check_residual_risks_explicit`에서) |
| 모든 필수 check passed | `passed` |
| (외부에서 eval.json 없음 조회) | `needs_eval` ← query 레이어에서만 |

### 5.16 `adapters/process.py`

```python
@dataclass
class WrapperResult:
    run_id: str | None
    exit_code: int
    cancelled_by_signal: str | None  # "SIGINT" 등

def wrap_command(argv: list[str], *, agent_name: str, agent_mode: str,
                 mode: Literal["minimal","full"]) -> WrapperResult:
    """
    의사 코드:

    recording_enabled = True
    try:
      run_id = make_run_id()
      workspace_id, basis, meta = compute_workspace_id(cwd)
      write_run_meta(...)
      append_event(run.started)
      write_workspace_pointer(...)
    except Exception as e:
      # Non-blocking invariant applies before child spawn too.
      # If AgentLens cannot initialize, run the child passthrough and return
      # the child's real exit code. No eval/manifest is attempted.
      recording_enabled = False

    sig_received: dict[str, str | None] = {"name": None}
    def handler(sig, frame):
        sig_received["name"] = {SIGINT:"SIGINT", SIGTERM:"SIGTERM"}.get(sig,"other")
        os.kill(child.pid, sig)   # forward
    signal.signal(SIGINT, handler); signal.signal(SIGTERM, handler)

    env = env_with_RUN_ID if recording_enabled else os.environ.copy()
    child = subprocess.Popen(argv, stdout=PIPE, stderr=PIPE, env=env)
    if recording_enabled: append_event(command.started)
    stdout, stderr = drain_streams_concurrently(child)
    exit_code = child.wait()
    duration_ms = ...
    if not recording_enabled:
        return WrapperResult(run_id=None, exit_code=exit_code, cancelled_by_signal=sig_received["name"])
    append_event(command.finished)

    # final 작성: 3가지 경로
    explicit_final = (run_dir/"final.json").exists()
    if sig_received["name"]:
        write_cancelled_final(...)            # agent_outcome=cancelled
        rc = 128 + signum_of(sig_received["name"])
    elif explicit_final:
        pass                                  # agent가 직접 작성
        rc = exit_code
    elif exit_code == 0:
        write_unknown_final(...)              # outcome=unknown
        rc = 0
    else:
        write_failed_final(..., exit_code)    # outcome=failed
        rc = exit_code

    # seal/eval은 best-effort
    try: seal(run_dir, "pre_eval")
    except Exception:
        try: seal(run_dir, "recording_incomplete")
        except Exception: pass
        return WrapperResult(run_id=run_id, exit_code=rc, cancelled_by_signal=sig_received["name"])

    try: evaluate(run_dir)
    except Exception:
        try: seal(run_dir, "recording_incomplete")
        except Exception: pass
        return WrapperResult(run_id=run_id, exit_code=rc, cancelled_by_signal=sig_received["name"])

    try: seal(run_dir, "final")
    except Exception: pass    # pre_eval manifest는 이미 디스크에 있음

    try: index_run(...)
    except Exception: pass    # SQLite 실패는 swallow

    return WrapperResult(run_id, rc, sig_received["name"])
    """
```

**핵심 invariant**: 이 함수의 어떤 분기에서도 `WrapperResult.exit_code`는 child의 실제 종료 신호/코드를 반영한다. AgentLens 내부 실패는 manifest를 `recording_incomplete`로 표시할 뿐이다.

`drain_streams_concurrently(child)`는 stdout/stderr를 동시에 drain해야 한다. POSIX v0에서는 `selectors` 또는 두 reader thread를 사용한다. 한 stream만 순차로 읽는 구현은 stderr/stdout pipe buffer가 꽉 찰 때 deadlock을 만들 수 있으므로 금지한다.

### 5.17 `adapters/shims.py`

```python
SHIM_TEMPLATE = r"""#!/usr/bin/env bash
# AgentLens shim for {name} — managed file, do not edit.
set -euo pipefail
REAL_LOCKFILE="$HOME/.agentlens/shims/{name}.real"
if [ ! -f "$REAL_LOCKFILE" ]; then
  echo "agentlens: real binary lockfile missing — passthrough" >&2
  mapfile -t CANDIDATES < <(type -P -a {name} 2>/dev/null | grep -F -v "$HOME/.agentlens/shims/" || true)
  if [ "${{#CANDIDATES[@]}}" -eq 0 ]; then
    echo "agentlens: no real {name} binary found" >&2
    exit 127
  fi
  exec "${{CANDIDATES[0]}}" "$@"
fi
REAL_PATH="$(awk -F= '$1=="path"{{print $2}}' "$REAL_LOCKFILE")"
REAL_SHA="$(awk -F= '$1=="sha256"{{print $2}}' "$REAL_LOCKFILE")"
CUR_SHA="$(shasum -a 256 "$REAL_PATH" | awk '{{print $1}}')"
if [ "$REAL_SHA" != "$CUR_SHA" ]; then
  echo "agentlens: real binary sha256 drift — passthrough only" >&2
  exec "$REAL_PATH" "$@"
fi
# Nested invocation handling
if [ -n "${{AGENTLENS_RUN_ID:-}}" ]; then
  policy="${{AGENTLENS_NESTED_POLICY:-passthrough}}"
  if [ "$policy" = "passthrough" ]; then exec "$REAL_PATH" "$@"; fi
  # else fall through to recording with parent_run_id
fi
# Admin/auth subcommands pass-through (per integration adapter rules)
case "${{1:-}}" in
  auth|login|update|plugin|mcp) exec "$REAL_PATH" "$@" ;;
esac
exec agentlens run --agent {name} --mode auto -- "$REAL_PATH" "$@"
"""

def install_shim(name: Literal["claude","codex"], real_path: Path) -> None:
    """
    1. shim_dir = ~/.agentlens/shims; mkdir(mode=0o700, exist_ok)
    2. 소유자 검증: stat(shim_dir).st_uid == os.getuid()
    3. lockfile <name>.real 작성: path=..., sha256=...
    4. shim 스크립트 작성: SHIM_TEMPLATE.format(name=name), chmod 0o755
    5. PATH 수정은 commands/install.py가 사용자 동의 후 수행
    """

def verify_shim_integrity(name: str) -> Literal["ok","drift_warning","missing"]:
    """lockfile sha256 vs real binary sha256 비교."""
```

### 5.18 `adapters/claude.py`, `adapters/codex_cli.py`, `adapters/codex_app.py`

각 adapter는 같은 인터페이스를 따른다:

```python
class Adapter(Protocol):
    name: str
    def detect(self) -> "DetectResult": ...
    def install(self, *, consent: bool) -> "InstallResult": ...
    def uninstall(self) -> None: ...

@dataclass
class DetectResult:
    available: bool
    level: Literal["full","native-experimental","shim-only","watcher-only","unavailable"]
    notes: tuple[str, ...]

@dataclass
class InstallResult:
    level_installed: str
    files_modified: tuple[Path, ...]   # backup path 포함
```

**Claude adapter 추가 책임**
- `claude --version` parsing
- `claude --help` 에서 `--include-hook-events`, `--output-format`, `--bare` 존재 여부 확인
- settings 파일 (`~/.claude/settings.json`) 백업 후 `"agentlens"` 키 블록만 주입
- uninstall은 `"agentlens"` 키만 제거 (다른 키 보존)

**Codex CLI adapter**
- `codex --version`, `codex exec --help`, `codex plugin --help`, `codex mcp --help`, `codex app-server --help`
- primary integration: shim (M6에서 설치된 것을 활용)
- mcp/plugin은 보조 — 부재해도 `full` 가능

**Codex App adapter**
- `~/.codex/sessions`, `~/.codex/archived_sessions` 존재 → watcher mode 가능
- `codex app-server --help`에 `[experimental]` 표기 확인 → `native-experimental` 표시
- session JSONL fixture는 `tests/fixtures/codex_app/0.129.0/*.jsonl`로 pin

---

## 6. 핵심 알고리즘 의사 코드

### 6.1 `compute_workspace_id`

```python
def compute_workspace_id(root: Path):
    persisted = _read_workspace_config(root).get("workspace_id")
    if persisted:
        return persisted, _read_workspace_config(root).get("id_basis", "path"), {}

    git_top = _find_git_toplevel(root)        # subprocess 또는 walk
    if git_top is not None:
        remote = _git_remote_url(git_top)     # "origin" 우선, 없으면 첫 remote
        if remote:
            norm = normalize_git_remote(remote)
            rel = root.relative_to(git_top).as_posix()
            worktree_identity = sha256(str(git_top.resolve()).encode()).hexdigest()[:16]
            basis_input = f"git:{norm}:{rel}:{worktree_identity}"
            wid = "ws_" + sha256(basis_input.encode()).hexdigest()[:16]
            _persist_workspace_config(root, wid, id_basis="git")
            return wid, "git", {
                "git_remote_hash": "sha256:" + sha256(norm.encode()).hexdigest(),
                "git_branch": _git_branch(git_top),
            }
    host_id = sha256(socket.gethostname().encode()).hexdigest()[:16]
    canon = sha256(str(root.resolve()).encode()).hexdigest()
    basis_input = f"path:{host_id}:{canon}"
    wid = "ws_" + sha256(basis_input.encode()).hexdigest()[:16]
    _persist_workspace_config(root, wid, id_basis="path")
    return wid, "path", {}
```

This intentionally trades pure deterministic recomputation for workspace correctness:
main checkout and git worktree must not collide. Moving a workspace preserves id when
the workspace `.agentlens/config.yaml` moves with it. If that config is deleted,
future runs may receive a new workspace_id, but old durable artifacts remain intact.

### 6.2 Two-phase manifest seal

```
seal(run_dir, "pre_eval"):
  entries = collect(include_eval=False)
  write manifest with sealed_phase="pre_eval", sealed_at=now()

# evaluate() 호출 → eval.json 생성

seal(run_dir, "final"):
  entries = collect(include_eval=True)
  write manifest with sealed_phase="final", sealed_at=now()   ← overwrite

# 어떤 단계에서든 IO error 발생 시:
seal(run_dir, "recording_incomplete"):
  best-effort collect (없는 파일은 skip)
  write manifest with sealed_phase="recording_incomplete"
```

### 6.3 Evaluator status 결정

```python
def resolve_status(ctx, results):
    if ctx.final is None:
        return "incomplete"
    failed = [r for r in results if r.status == "failed"]
    if failed:
        return "failed"
    return "passed"
```

`error`는 engine 최상위 try/except에서 직접 반환.
`needs_eval`은 query 레이어에서 `eval.json` 부재 시 표시 (engine은 만들지 않음).

### 6.4 Shim 동작 흐름 (재진입 안전)

```
shim 시작
  ├─ lockfile 검증 (없거나 sha256 불일치 → passthrough)
  ├─ AGENTLENS_RUN_ID 있고 PID stamp가 자기 PID에서 만든 것 아님:
  │    AGENTLENS_NESTED_POLICY=passthrough(기본) → real exec
  │    AGENTLENS_NESTED_POLICY=nested → agentlens run --parent ... -- real ...
  ├─ admin 명령(auth/login/update/plugin/mcp) → real exec (recording 없음)
  └─ 그 외 → agentlens run -- real <argv>
```

PID stamp 처리:
```python
# wrapper가 환경에 넣는 값
env["AGENTLENS_RUN_ID"] = run_id
env["AGENTLENS_RUN_DIR"] = str(run_dir)
env["AGENTLENS_RUN_PID_STAMP"] = f"{os.getpid()}:{run_id}"

# shim에서 검사
if env.get("AGENTLENS_RUN_PID_STAMP","").startswith(f"{os.getppid()}:"):
    # 부모가 이 run을 만든 wrapper이므로 같은 run을 또 시작하지 않음
    exec real
```

### 6.5 Redaction 파이프라인

```
원본 dict
  ├─ apply_to_doc(doc, workspace_root):
  │     walk dict/list 재귀
  │     str 노드 만나면:
  │       1. protected key면 그대로 둠
  │       2. mask_secret(s)
  │       3. mask_path(s, workspace_root)
  │       4. key=="excerpt" 인 경우 len 검사 (4096 초과 시 truncate + 마커)
  │     bytes/numbers/bool 통과
  └─ schema validate redacted persisted doc
```

`mask_path`는 hash 보존을 위해 항상 `path_label` (사람용)과 `path_hash` (correlation용) 쌍을 유지.

---

## 7. 동시성 모델

### 7.1 다중 run 동시 진행

- 한 워크스페이스에서 두 개 이상의 agent run 동시 가능 (예: 두 Claude 세션).
- `<workspace>/.agentlens/current-runs/<run_id>` 디렉터리 마커를 각 run이 자신 PID 종료 시 정리.
- 같은 run_id를 두 프로세스가 동시에 만들 가능성은 `make_run_id`의 random suffix로 사실상 제거 (충돌 시 collision_handler가 한 번 재시도).

### 7.2 한 run의 events.jsonl

- 여러 sub-process가 같은 run에 이벤트를 append할 수 있음 (예: shim wrapper + 별도 hook adapter).
- `store/lock.py`의 exclusive flock으로 append 직렬화.
- lock timeout(5초) 발생 시 LockTimeoutError → 호출자가 `failure.observed` 이벤트로 변환해 추후 append (best-effort).

### 7.3 SQLite

- 단일 writer (`store/sqlite_index.py`만 write). best-effort, 실패 swallow.
- reader는 read-only connection 다중 허용.

### 7.4 Nested run

- 자식 agent가 또 다른 agent를 spawn (예: Claude 안에서 Codex 호출):
  - `AGENTLENS_NESTED_POLICY=passthrough` (기본): 자식은 기록 안 됨.
  - `AGENTLENS_NESTED_POLICY=nested`: 새 run 시작, `parent_run_id`=$AGENTLENS_RUN_ID.
- nested run의 events.jsonl은 부모와 분리된 디렉터리이므로 lock 경합 없음.

---

## 8. 보안 / 프라이버시 구현 디테일

### 8.1 기본 비저장 (default)

| 항목 | 처리 |
|---|---|
| absolute home path | mask: `<HOME>/<HASH8>` |
| API key / token | mask: `<REDACTED:openai_key>` 등 |
| Authorization header | mask |
| private key body | mask |
| full prompt transcript | 저장 안 함 (`manifest.redaction.full_prompts="not_stored"`) |
| full command output | excerpt만 (allow-list extractor) |
| 대용량 file body | artifact로만, retention 정책 적용 |

### 8.2 Excerpt 정책

- `MAX_EXCERPT_CHARS = 4096` (writer가 강제, 초과 시 잘라내고 `<TRUNCATED>` 마커).
- 추출은 `EXCERPT_EXTRACTORS` allow-list로만. 자유 텍스트 슬라이스 금지.
- `mode=full`이라도 동일 — full은 더 많은 evidence "필드"를 켜는 것이지 자유 텍스트 저장을 의미하지 않음.

### 8.3 Shim 보안

- `~/.agentlens/shims/` 권한 `0700`, 매 invocation 시 `os.stat`으로 owner 검증.
- lockfile에 real binary 경로 + sha256. sha256 drift 시 즉시 passthrough.
- `agentlens install`은 PATH 변경에 대한 명시 동의 prompt. `--yes`는 CI 또는 user 의도적 자동화 한정.

### 8.4 Retention

- `max_total_store_gb=5` 초과 시 oldest sealed run의 `artifacts/`부터 삭제.
- `eval.json`, `final.json`, `manifest.json`은 `keep_eval_summaries=true` 한 항상 보존.
- GC는 SQLite 부재 상태에서도 full-scan으로 동작.

---

## 9. 테스트 전략

### 9.1 fixture 구조

```
tests/fixtures/
  minimal_run/                 # success, verification 있음, residual 없음 → passed
    run.json, events.jsonl, final.json, manifest.json (pre_eval)
    expected_eval.json
  failed_command_run/          # 실패 command 있는데 final에서 인정 안 함 → failed
  missing_final_run/           # final 없음 → incomplete
  residual_risk_run/           # success인데 high residual risk → failed
  corrupt_manifest_run/        # manifest hash 불일치 → failed (ARTIFACT_HASH_MISMATCH)
  codex_app/0.129.0/           # Codex App session JSONL pin
```

### 9.2 단위 테스트 (예시 표)

| 파일 | 검증 항목 |
|---|---|
| `test_ids.py` | run_id 형식, workspace_id git/path basis 양쪽, worktree 분리 |
| `test_ids.py` | workspace config가 있으면 move 후에도 persisted workspace_id 유지 |
| `test_paths.py` | $AGENTLENS_HOME 우선, workspace 외부 경로 EXTERNAL 처리 |
| `test_schema_validation.py` | valid/invalid 짝, enum 경계, timestamp regex, additionalProperties, `$comment` 버전 정책 |
| `test_manifest.py` | pre_eval/final 두 단계, eval.json 포함 여부, hash 불일치 detect |
| `test_sqlite_index.py` | index/rebuild byte-equal, SQLite 부재 fallback |
| `test_query_fallback.py` | SQLite 없음/손상 시 `store/query.py` full-scan fallback |
| `test_evaluator_checks.py` | 12개 check 각각, residual severity policy |
| `test_evaluator_checks.py` | check exception → `EVALUATOR_ERROR`, success+empty changed_files+no_changes_reason policy |
| `test_redaction.py` | secret 패턴 7종, HOME prefix 3종, excerpt truncate |
| `test_redaction.py` | protected hash/id/status fields are never mutated by redaction |
| `test_retention.py` | 30일 초과, max_total_store_gb, dry_run vs 실제 |
| `test_config.py` | priority chain, AGENTLENS_DISABLE 우선 |
| `test_shim_security.py` | 권한 0700/0755, lockfile drift detect, nested policy |

### 9.3 통합 테스트

| 파일 | 검증 항목 |
|---|---|
| `test_cli_lifecycle.py` | start→mark→final→seal→eval→show 전체 흐름, JSON 포맷 |
| `test_process_wrapper.py` | exit 0/exit 42/SIGINT 세 경로, exit code 보존, large stdout/stderr no deadlock |
| `test_install_doctor.py` | fake binary 환경에서 detect, install/uninstall 백업/복원 |
| `test_nonblocking.py` | fault-injection 6종(init failure 포함), child exit code 보존 |
| `test_eval_determinism.py` | fixture 2회 실행 byte-equal (timestamp normalize 후) |

### 9.4 회귀 잠금

다음 5개 통과 없이는 어떤 PR도 머지 금지:
- `test_schema_validation.py`
- `test_eval_determinism.py`
- `test_nonblocking.py`
- `test_shim_security.py`
- `test_redaction.py`

### 9.5 Determinism 검증 방법

```python
def normalize(eval_doc: dict) -> dict:
    """evaluated_at, sealed_at 등 타임스탬프를 '0000-00-00T00:00:00Z'로 치환."""

def test_evaluator_byte_equal(fixture):
    e1 = json.dumps(evaluate(fixture), sort_keys=True)
    e2 = json.dumps(evaluate(fixture), sort_keys=True)
    assert normalize_str(e1) == normalize_str(e2)
```

---

## 10. CLI UX

### 10.1 명령 목록 (v0)

```
agentlens install [--yes]
agentlens doctor [integrations] [--format json]
agentlens on | off | mode <minimal|full>

agentlens run -- <command> [args...]
agentlens start --agent <name> --mode <cli|app|code|unknown> [--parent <run_id>]
agentlens mark <event_type> [--task-id ...] [--name ...]
agentlens attach --kind <kind> --path <path>
agentlens final --outcome <success|failed|partial|cancelled|unknown>
agentlens seal [--final]
agentlens eval [--latest | --run-id <id>]
agentlens cancel --run-id <id> [--reason ...] [--signal SIGINT]

agentlens latest [--format json]
agentlens status [--format json]
agentlens show <--latest | run_id> [--format json]
agentlens failures [--since-days 30] [--format json]
agentlens risks [--since-days 30] [--format json]
agentlens gc [--dry-run]
```

### 10.2 출력 규약

- 기본 출력: 사람용 텍스트. 가로 80자 이내, 색은 TTY일 때만.
- `--format json`: 단일 객체 또는 배열, schema stable (snapshot test).
- stderr: 진단/경고만. stdout은 query 결과 전용.
- 모든 command가 `--help`를 가짐 (Typer 기본).

### 10.3 Help 출력 제외 명령

다음은 v0에서 help/discoverable 명령 목록에 포함하지 않는다 (scope creep 방지):
- `import`, `dashboard`, `studio`, `mcp`, `patch`, `compile`

`cli.py`에 hidden command나 별도 entrypoint도 두지 않는다.

---

## 11. 최종 검증 시나리오 (v0 GA smoke)

`docs/adr/agentlens_v0_task_breakdown.md` §14와 동일. 본 문서에서는 통과 기준을 추가 명시:

```bash
ruff check .                                    # 0 error
pyright                                         # 0 error in strict
pytest -v                                       # all green, 회귀 잠금 테스트 포함
python -m agentlens.cli --help                  # deferred 명령 미노출
python -m agentlens.cli doctor integrations --format json | jq .   # parsable
python -m agentlens.cli run -- sh -c 'echo hello'                   # exit 0
python -m agentlens.cli latest                                       # 해당 run 표시
python -m agentlens.cli show --latest --format json | jq .          # parsable
python -m agentlens.cli show --latest                                # 절대 경로 없음
python -m agentlens.cli eval --latest                                # exit 0
python -m agentlens.cli failures                                     # 0건 (smoke run)
python -m agentlens.cli risks                                        # 0건
python -m agentlens.cli gc --dry-run                                 # 삭제 후보 0건
```

수동 SIGINT 시나리오:
```bash
python -m agentlens.cli run -- sh -c 'sleep 30' &
PID=$!; sleep 1; kill -INT $PID; wait $PID; echo "exit=$?"
# exit=130 (= 128 + SIGINT) 확인
python -m agentlens.cli show --latest --format json | jq .agent_outcome
# "cancelled" 확인
```

---

## 12. 참조 관계 요약

| 본 문서 절 | 아키텍처 문서 절 | 플랜 문서 절 |
|---|---|---|
| 4 데이터 모델 | §6 Minimal Run Contract | §3.1 M0 |
| 5 모듈 시그니처 | §3 전체 아키텍처, §4 저장 구조 | §3.2 M1, §3.3 M2 |
| 5.16 process wrapper | §12.3 CLI shim | §3.6 M5 |
| 5.17 shims | §12.3, §10.4 | §3.7 M6 |
| 6.1 workspace_id | §4.4 | §3.2 M1 (T1.1) |
| 6.2 manifest seal | §5 lifecycle | §3.2 M1 (T1.3) |
| 7 동시성 | §4.5 | §3.2 M1 |
| 8 보안 | §10 | §3.9 M8 |
| 9 테스트 | §8 evaluator | §5 품질 게이트, §7 검증 전략 |
| 10 CLI | §13 CLI 설계 | §3.4 M4 |

이 명세와 플랜 두 문서를 같이 보면 M0부터 v0 GA까지 모든 결정과 산출물이 추적 가능하다. 코드 작성 중 모호한 결정이 생기면 (1) 본 spec 확인, (2) 부족하면 ADR 확인, (3) 그래도 부족하면 spec PR을 먼저 올린다. 코드가 spec을 앞서 가지 않는다.
