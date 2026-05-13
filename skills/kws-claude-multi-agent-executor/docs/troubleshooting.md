# 트러블슈팅

이 스킬을 실행·개발·디버깅하면서 자주 마주치는 문제들. 각 항목 구성: 증상 · 가능 원인 · 진단 · 해결.

*리스크* 나 *인정된 한계* 를 찾고 있다면 [`./risks-and-limitations.md`](./risks-and-limitations.md) 참조. 이 파일은 *구체적 해결 방법이 있는 운영 문제* 용입니다.

---

## 스킬 실행 문제

### 증상: 오케스트레이터가 Phase 0 Step 7.5를 건너뜀 (run 디렉터리 안 생김)

**가능 원인**: v2.8.1 이전 SKILL.md, 또는 오케스트레이터가 무거운 컨텍스트 압박 아래 있음.

**진단**:
```bash
grep "LEARNING_LOG_INIT:" <run.jsonl-path>
# 비어있음 → Step 7.5 가 실행 안 됨.
# 비어있지 않음 → 스텝이 실행됨 (RUN_ID 발산 vs SKIPPED 확인).
```

파일시스템 교차 확인:
```bash
find ~/.claude/learning/kws-claude-multi-agent-executor/runs -newer <run.jsonl> -type d
# 비어있음 → run 디렉터리 생성 안 됨.
```

**해결**:
- SKILL.md 버전 < 2.8.1 이면: ≥2.8.1로 번프.
- 2.8.1 인데 여전히 준수 실패면: 회귀를 사용자에게 노출. [`./deferred-candidates.md`](./deferred-candidates.md) §Hook-based enforcement 가 다루는 시나리오.

**참조**: [`./risks-and-limitations.md`](./risks-and-limitations.md) §Orchestrator adherence.

### 증상: 서브에이전트가 `MAE_LEARNING_RUN_ID` 를 사용하려는데 비어있음

**가능 원인**: Step 7.5 헬퍼 스크립트가 조용히 실패 (파일 실행 불가, Python 누락, `~/.claude/learning/` 쓰기 실패).

**진단**:
```bash
python3 ~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py init-run \
  --repo-root $(pwd) --repo-name test --branch main \
  --plan-path /tmp/p.md --spec-path /tmp/s.md
# 기대: RUN_ID 출력 + run 디렉터리 생성.
# 에러 시: stderr 읽기 — 권한, Python 버전, learning-events 디렉터리 누락일 가능성.
```

**해결**:
- `~/.claude/learning/` 가 쓰기 가능한지 확인.
- `python3` 이 PATH에 있는지 확인 (`which python3`).
- 헬퍼 스크립트가 실행 가능한지 확인 (`chmod +x` 필요 없음; `python3 <path>` 로 호출됨).

### 증상: 실행이 끝났는데 meta.json 이 `outcome=unknown`

**가능 원인**: 오케스트레이터가 close-run 경로에 도달하지 못함 — 하드 크래시, SIGKILL, 또는 Phase 2 건너뛴 스텝 경로.

**진단**:
- worktree 의 `state.json` 확인 — 마지막 태스크가 `COMPLETE` 인가?
- run.jsonl tail 확인 — 미처리 예외가 있었나?

**해결**:
- 실행은 성공했는데 close-run 이 건너뛰어졌다면 → 수동 실행:
  ```bash
  python3 ~/.claude/skills/kws-claude-multi-agent-executor/scripts/append_learning_event.py close-run \
    --run-id <run_id> --outcome success
  ```
- 실행이 크래시했다면 → `outcome=unknown` 그대로 두는 게 정직. 크래시 근본 원인을 조사; outcome 을 수동으로 다시 쓰지 마세요.

### 증상: 오케스트레이터가 서브에이전트를 디스패치했는데 Reviewer 출력이 안 나타남

**가능 원인**: Agent 툴 디스패치가 조용히 실패했거나, 서브에이전트가 승인 안 된 툴을 만남.

**진단**:
- run.jsonl 에서 예상 디스패치 시점 근처의 `"name": "Agent"` tool_use 항목 검색.
- 대응되는 tool_result 가 있는지 확인 (있으면 서브에이전트가 완료하고 반환함을 의미).

**해결**:
- 디스패치 누락이면: `--debug` 플래그로 재실행 (Claude Code CLI 옵션).
- tool_result 누락이면: 서브에이전트가 실행됐지만 반환 안 함 — 승인 안 된 툴에 걸렸을 가능성. 적절하면 `--dangerously-skip-permissions` 로 재실행.

---

## Eval 시스템 문제

### 증상: 문서 신선도 체크가 드리프트 보고

**가능 원인**: 대응되는 문서 갱신 없이 변경을 출하했음.

**진단**:
```bash
python3 evals/check_doc_freshness.py
```

`failures[]` 검사 — 각 항목이 드리프트를 이름붙임.

**해결**: [`./doc-update-protocol.md`](./doc-update-protocol.md) 를 참고해서 출하한 변경 종류에 맞는 체크리스트 따르기. 흔한 케이스:
- 버전 불일치 → 같은 커밋에서 `SKILL.md`, 스킬 `README.md`, `HISTORY.md` 번프.
- 깨진 링크 → 경로 수정 또는 대상 갱신.
- HISTORY 항목 누락 → 현재 버전에 §1 항목 추가.
- 스냅샷 누락 → 마이너 번프에 `docs/snapshots/v<X>.md` 작성.
- ADR 인덱싱 안 됨 → `docs/decision-log.md` 에 행 추가.

드리프트가 의도적이면 (예: 템플릿의 placeholder 링크): `_template` 제외에 추가하거나 backtick 으로 감싸기 (code-span 텍스트는 건너뜀).

### 증상: `evals/run.sh` 가 preflight 실패

**가능 원인**: 계약 eval 회귀 (18개 계약 체크가 감시하는 프롬프트 또는 SKILL.md 편집을 깨뜨림).

**진단**:
```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_learning_log.py
```

출력이 어느 체크가 실패했는지 알려줌.

**해결**: 특정 체크 해결. 흔한 실패:
- `skill_call_in_references_reviewer-prompt.md` → Reviewer 프롬프트에서 `Skill("superpowers:requesting-code-review")` 호출 누락.
- `skill_md_v281_mandatory_framing` → SKILL.md Step 7.5 에서 MANDATORY / DO NOT SKIP THIS STEP / LEARNING_LOG_INIT: 중 하나 누락.
- `candidate_file_contract_in_references_*.md` → 서브에이전트 프롬프트에서 `.orchestrator/learning_events/` 또는 "Do not call the helper" 누락.

### 증상: `evals/run.sh` 가 `judge mean = 0` / `judge invocation failed` 생산

**가능 원인**: judge `claude -p` 호출이 실패 (네트워크, 인증, 또는 rate limit), 또는 judge 출력 파싱 불가.

**진단**:
- `<tmpdir>/.harness/run.jsonl` tail 읽기 — 에러 있나?
- 자명한 프롬프트로 `claude -p` 수동 호출해서 인증 확인.

**해결**:
- 인증: `claude login` 으로 자격 증명 갱신.
- Rate limit: 대기 후 재실행.
- 파싱 불가: `<tmpdir>/.harness/judge_input.txt` 읽기 — judge 프롬프트가 치환 안 된 placeholder 를 leak 했을 가능성. run.sh 의 `judge_prompt` 블록 치환 수정.

### 증상: rubric pass_rate = null (rubric 출력 없음)

**가능 원인**: 픽스처 YAML 에 `expected.rubric` 블록 누락, 또는 rubric 러너가 기대한 worktree 경로 존재 안 함.

**진단**:
```bash
jq '.expected.rubric' evals/fixtures/<fixture>.yaml
# 비어있음 → 픽스처에 rubric 없음 (run.sh 가 null 출력; 에러 아님).
ls /var/folders/.../<tmpdir>/worktrees/
# 비어있음 → 오케스트레이터가 worktree 생성 전 실패.
```

**해결**:
- 픽스처에 의도적으로 rubric 없으면: 무시.
- worktree 누락이면: 오케스트레이터가 Phase 0 에서 실패; Phase 0 디버그 (plan.md 또는 spec.md 파일 누락 가능성).

### 증상: 실행은 성공했는데 `learning_log_adherence: no`

**가능 원인**: Step 7.5 가 건너뛰어졌지만 오케스트레이터의 나머지는 작동.

**영향**: 실행별 관측성 손실 (meta.json 없음, events.jsonl 없음). 실행의 정확성에는 영향 없음.

**해결**: 이건 v2.8.0 시대의 회귀이고 v2.8.1 이 고침. v2.8.1+ 아래에서 이게 보이면 진짜 버그로 등록 — 준수가 회귀함.

---

## 브랜치 / 머지 문제

### 증상: `../v2.8-learning-log/` 로의 cross-reference 해결 실패

**가능 원인**: `main` (또는 v2.8 머지 전 main에서 분기한 브랜치) 에 있음. v2.8 커밋은 `codex/executor-learning-log` 에 거주.

**진단**:
```bash
git log --oneline main..codex/executor-learning-log | grep "v2.8\|v2.9"
```

**해결**:
- v2.8/v2.9 문서를 읽어야 하면: `git checkout codex/executor-learning-log`.
- 머지 중이면: 먼저 Claude executor 커밋을 main 으로 cherry-pick 또는 머지, 그 다음 문서 경로 해결.

### 증상: `git status` 가 사용자의 Codex executor 변경을 unstaged 로 표시

**가능 원인**: 정상. 브랜치는 공유. 사용자의 병렬 작업과 Claude executor 작업이 경로 격리된 변경으로 공존.

**진단**:
```bash
git status --short | grep "skills/kws-codex"
# 사용자 소유 — 건드리지 말 것.
```

**해결**: Claude executor 파일 (`skills/kws-claude-multi-agent-executor/`) 과 *내* 스킬 버전용 Archive 수준 README 행만 스테이징. Codex 변경은 그대로 두기.

---

## 학습 로그 문제

### 증상: `find_open_run` 이 잘못된 run_id 반환

**가능 원인**: 이전 실행이 `outcome=unknown` (하드 크래시) 으로 남았고 헬퍼의 멱등성 probe 가 그걸 매칭.

**진단**:
```bash
ls ~/.claude/learning/kws-claude-multi-agent-executor/runs/<today>/
# 각 run 디렉터리에 대해 meta.outcome 확인.
```

**해결**:
- stale 실행을 수동으로 닫기: `append_learning_event.py close-run --run-id <id> --outcome unknown` (정직한 unknown 기록).
- 또는 실행이 정말 defunct 면 stale 디렉터리를 archive 위치로 이동.

### 증상: events.jsonl 에 중복 항목

**가능 원인**: 오케스트레이터가 후보 삭제 없이 `learning_events/` 두 번 스캔했거나, 여러 오케스트레이터 인스턴스가 같은 `MAE_LEARNING_RUN_ID` 공유.

**진단**:
- JSONL 의 `event_id` 값 비교 — 중복이 신호.
- 프로세스 트리 확인: `pgrep -f "claude -p"` 가 worktree 당 하나의 오케스트레이터만 보여야 함.

**해결**:
- 단일 작성자 계약: 오케스트레이터가 append 후 각 후보 파일 삭제 필수. 안 했으면 (예: append + delete 사이 크래시), 다음 스캔이 재 append.
- 헬퍼의 `event_id` = 콘텐츠의 sha256-16; 향후 dedup 로직이 이를 이용할 수 있지만 현재 미구현.

### 증상: meta.json 의 `worktree_path` 가 절대 경로로 보임

**가능 원인**: v2.8 이전 헬퍼 (relativization 없음), 또는 worktree 가 레포 루트 밖에서 생성됨.

**진단**:
- 헬퍼 버전 확인: `head -20 scripts/append_learning_event.py` 가 relativize 함수를 보여야 함.
- worktree 가 git 레포 안에 있는지 확인: `git -C <worktree_path> rev-parse --show-toplevel`.

**해결**:
- v2.8 이전 헬퍼면: 이 디렉터리에서 현재 버전 설치.
- worktree 가 정말 레포 밖이면: relativization 이 절대 경로로 fail-safe. 버그 아님; worktree 생성 로직 재검토 필요.

---

## 모두 잡기

### 의심스러우면 이 산출물들을 모아서 사용자에게 노출

낯선 실패에 대해 다음을 수집:

```bash
# 1. 실패 시점 상태
cat <worktree>/.orchestrator/state.json | jq '.tasks'

# 2. run.jsonl 마지막 100줄
tail -100 <tmpdir>/.harness/run.jsonl

# 3. 학습 로그 meta + events (디렉터리 존재 시)
cat ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/meta.json
cat ~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/events.jsonl

# 4. Git 상태
git -C <worktree> log --oneline -10
git -C <worktree> status

# 5. 최근 baseline
ls -la evals/baselines/
```

그리고 사용자에게 물어보세요. 이 스킬은 복잡한 실행 모델을 가지고 출하됐고, 많은 실패가 처음 봤을 때 비슷해 보입니다.

## 이 파일을 갱신하는 법

진단에 10분 이상 걸린 문제를 디버그했을 때 섹션 추가:
- 증상 (한 문장)
- 가능 원인 (한 문장)
- 진단 명령어 (구체적)
- 해결 (구체적)

"무엇이 이걸 어렵게 만들었나" 라는 지식이 가장 가치 있는 부분입니다. 세션과 함께 사라지게 두지 마세요.
