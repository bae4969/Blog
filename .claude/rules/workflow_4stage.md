# 4단계 워크플로우 — 서칭 → 기획 → 구현 → 검증 (full 전용 필수, lite는 단순 2단계)

이 프로젝트의 **full 모드 비단순 요청**은 아래 4단계 사이클을 따른다. 메인 에이전트는 `/full` prefix가 붙은 요청을 받으면 [`main_full_procedure.md`](main_full_procedure.md)를 따라 4단계 진행을 직접 지휘한다. 단계별 상세 규약은 [`../agents/orchestrator.md`](../agents/orchestrator.md)에 보존된다. 단계 전이마다 `.claude/state/current.json`을 갱신해 세션이 끊겨도 재개 가능하게 한다.

**lite 모드**는 본 4단계를 적용하지 않는다 — 메인이 직접 Edit/Write로 외과적 수정 후 critic만 호출. 자세한 흐름은 본 문서 하단 "Lite 모드 (기본)" 절 참조.

## 모드 분기 (Lite vs Full)

| 모드 | 진입 조건 | 실행 |
|------|----------|------|
| **lite** (기본) | `/full` prefix 없음 | 메인이 직접 Edit/Write → critic 검증 (2단계: 수정→검증, 서브에이전트 1개) |
| **full** | `/full` prefix 있음 | 메인이 4단계 사이클 지휘 (search→plan→implement→verify) + report (서브에이전트 4개) |

**결정론적 분기**: lite vs full 모드는 `/full` slash prefix 매칭으로만 결정한다(다른 slash command — `/draft`, `/init` 등 — 은 자체 동작을 가지며 모드 자체를 바꾸지 않는다). LLM이 "간단해 보임"으로 모드를 바꾸는 것 금지.

**state.mode 필드**: full 모드에서만 state.json을 초기화하고 `"mode": "full"` 기록. lite는 state.json을 생성·갱신하지 않는다 (재개 불필요).

**lite에서 full로 승격**: critic이 `recommend_full: true`를 반환해도 자동 승격하지 않는다. lite Fail 재시도 후의 AskUser 카드에 "`/full`로 승격" 옵션을 포함시키고, 사용자가 선택한 경우에만 승격한다.

## 적용 대상

### 양성 예시 (워크플로우 발동 — 메인이 4단계 진입)
- "X 기능을 구현해줘"
- "이 모듈을 리팩토링해줘"
- "A하고 B하고 C 해줘" (복수 항목 나열)
- "버그 X를 고치고 회귀 테스트도 추가해줘"
- "환경을 검토하고 부족한 부분 채워줘"
- "Y 라이브러리 도입해서 Z 기능을 추가해줘"

### 음성 예시 (메인이 즉시 처리, 4단계 진입 안 함)
- "X 함수가 어디 있어?" (정보 조회)
- "이 에러 메시지 무슨 뜻이야?" (질의)
- "이 파일 한 줄만 고쳐줘 — typo" (단일·자명 편집)
- "지금 상태 요약해줘" (보고)
- "도구 목록 보여줘" (조회)
- "방금 변경 사항 설명해줘" (회상)

### 경계선 판단
- 변경 파일 1개·단계 1개·검증이 자명 → 메인 직접 처리.
- 두 가지 이상의 의문 ("어디를 고쳐야 할지 모름" + "여러 후보 있음") → 발동.
- 의심스러우면 발동 (안전한 쪽). 사용자가 "그냥 빨리 해"라고 반복하면 다음 회차부터 비슷한 요청은 메인 직접 처리.

## 4단계 — 상세

### Phase 1 — SEARCH (서칭)
**책임**: 메인 → researcher.

1. 메인이 사용자 요청을 한 줄로 정리하고 `state.json` 초기화 (status=`searching`, current_phase=`search`). 같은 시점에 `temp/progress.md`를 run 헤더로 덮어써 초기화한다.
2. researcher 호출 — 입력 계약(목표·컨텍스트·범위·출력 형식·완료 조건).
   - 범위: 코드베이스 + 웹 + 외부 MCP(context7/arxiv/github 등) 모두 활용 가능.
3. researcher가 발견을 구조화해 반환하고 `temp/progress.md`에 서칭 요약을 append한다.
4. 메인이 **AskUserQuestion** 카드로 결정 받기 — 옵션 예:
   - 기획 진입 (Recommended, 발견이 충분할 때)
   - 추가 서칭 (특정 영역 보강 필요)
   - 서칭 범위 변경
   - 취소
5. 응답 처리 후 Phase 2로 (또는 재서칭/취소).

### Phase 2 — PLAN (기획)
**책임**: 메인 → planner.

1. 메인이 `state.current_phase = "plan"`, `status = "planning"`.
2. planner 호출 — researcher 발견 중 필요한 최소한을 컨텍스트로 전달.
3. planner가 다음을 반환:
   - 추천 접근 + (필요 시) 대안 비교
   - 단계 분해 (3~7개, 각각 완료 조건·검증 방법 부착)
   - 영향 범위·예상 리스크
   - **coder 변경 명세** (대상·금지 사항·완료 조건·코드 컨벤션)
   - **사용자 결정 항목** (AskUserQuestion 카드용 옵션)
4. planner 결과 본문을 `temp/plan.md`에 덮어쓰고 `temp/progress.md`에 기획 산출 경로를 append한다. 채팅에는 기획서 링크와 핵심 한 줄만 남기고, 본문 전체를 붙이지 않는다.

출력 위치: planner 산출물 본문은 `temp/plan.md`에 덮어쓰기로 작성. 채팅에는 `temp/plan.md` 링크와 AskUserQuestion 승인 카드만 띄운다.

5. 메인이 **AskUserQuestion** 카드로 결정 + 승인 — 한 호출에 최대 4개 질문 묶음, 마지막은 항상 "승인 / 수정요청 / 취소".
6. 응답 처리:
   - **승인** → `state.status = "approved"`, Phase 3로.
   - **수정요청** → planner에 변경 사항 전달 → 재호출 → 다시 4번.
   - **취소** → `state.status = "aborted"`, 종료.
7. **승인 없이는 절대 Phase 3로 진입하지 않는다**.

### Phase 3 — IMPLEMENT (구현)
**책임**: 메인 → coder.

1. 메인이 `state.current_phase = "implement"`, `status = "implementing"`.
2. coder 호출 — 프롬프트에 세 섹션을 순서대로 인용한다 (자세한 형식: [main_full_procedure.md §3.1](main_full_procedure.md)):
   - `## 사용자 원 요청` — 첫 메시지 본문 그대로 (인텐트 lossy 방지)
   - `## planner 변경 명세` — planner 산출 블록 그대로
   - `## (재호출 시) 이전 시도 실패 사유` — critic 사유 목록 (Phase 4 Fail 후 재구현 때만)
3. coder가 변경 명세에 적힌 파일·심볼만 Edit/Write로 직접 변경한다. 변경 명세에 검증 명령(테스트·빌드)이 있으면 Bash로 실행해 자체 점검.
4. coder가 결과(변경된 파일 목록·신규/삭제 파일·자체 검증 결과·행동 4원칙 자기 점검)를 반환.
5. 메인이 결과 요지를 기록하고 `temp/progress.md`에 구현 시도 요약을 append한다.
6. coder가 실패(Edit 도구 오류, 가정 충돌, 자체 검증 실패 등)를 보고했으면 Phase 4의 실패 경로로 직행.

**핵심 강제 메커니즘**: Edit/Write는 **coder에만** 부여된다. researcher/planner/critic은 도구 목록 자체에 Edit/Write가 없어 구조적으로 코드를 편집할 수 없다. full 모드의 메인은 단계 전이 메타데이터(`.claude/state/**`, `temp/**` 등) 화이트리스트만 쓰고 코드 파일은 손대지 않는다. lite 모드의 메인은 본 메커니즘과 별개로, 자기 Edit/Write로 코드를 직접 외과적 수정한다 (CLAUDE.md "Lite 모드" 절 참조).

### Phase 4 — VERIFY + 재시도 루프
**책임**: 메인 → critic (실패 시 → AskUser → 재구현 → 재검증).

진행 기록: 구현/검증 진행 상황은 `temp/progress.md`에 append. 채팅에는 요지만.

1. 메인이 `state.current_phase = "verify"`, `status = "verifying"`.
2. critic 호출 — 입력: 사용자 원 요청, planner 완료 조건·금지 사항, coder 변경 보고, 테스트 명령 (있으면).
3. critic이 verdict(Pass/Fail) + 사유 목록 반환.
4. 메인이 verdict를 받고 `temp/progress.md`에 검증 결과를 append한다.

#### Pass 경로
- `state.status = "done"`.
- Phase 5(REPORT)로.

#### Fail 경로 — 재시도 게이트 (3단계)
- `state.retry_count += 1`.
- **retry_count < 3** (1회·2회 실패):
  - 메인이 **AskUserQuestion** 카드 — 옵션:
    - **자동 재구현** (Recommended) — critic 사유를 coder 입력에 추가해 Phase 3 재실행
    - **방향 변경** — planner를 critic 사유와 함께 재호출 → Phase 2로 복귀 (mode=full로 전환됨)
    - **중단** — `state.status = "aborted"`, 종료
  - 응답 처리 후 해당 단계로 복귀.
- **retry_count == 3** (3번째 실패):
  - **루프 강제 중단**. `state.status = "blocked"`, `state.block_reason = "verify_failed_3_times"`.
  - 메인이 **AskUserQuestion** 카드 — 옵션:
    - **계획 수정** — planner 재호출(Phase 2로) — retry_count 초기화 여부는 사용자에게 같이 묻기 (대개 초기화)
    - **단계 건너뛰기** — 현 변경을 그대로 done 마킹 (위험 — 회귀 가능성 사용자 명시 동의)
    - **취소** — `state.status = "aborted"`, 종료
  - 사용자 응답 전에는 자동 재시도 금지.

#### 재시도 시 coder 프롬프트 보강
critic 사유를 coder 호출 프롬프트 말미에 추가:
```text
## 이전 시도 실패 사유 (critic 피드백)
- <사유 1>
- <사유 2>
이번 시도는 위 사유를 정확히 해소해야 한다.
```

#### 재검증 시 critic 입력 보강
이전 verdict를 critic 입력에 같이 전달하면 critic이 "이전 사유 해소 여부"를 한 줄씩 체크해 verdict에 명시.

### Phase 5 — REPORT (완료 보고)
모든 단계 done 시 메인이:
1. 완료 보고 본문을 `temp/report.md`에 덮어쓴다:
   ```markdown
   ## 완료 보고
   
   ### 한 일
   - [단계 1] 무엇을 변경 → 영향 파일 (`path:line` 링크)
   - [단계 2] ...
   
   ### 자동 검증 결과
   - critic verdict: <Phase 4에서 critic이 반환한 verdict 그대로>
   - critic 사유: <critic 사유 목록 그대로 인용 — 가공·요약 금지>
   - 실행 테스트: `<명령>` → 통과
   - (없으면) "자동 검증 수단 없음 — 수동 테스트 필요"
   
   ### 사용자가 확인할 것 (수동 테스트 체크리스트)
   - [ ] <시나리오 1>: 기대 결과 = ...
   - [ ] <시나리오 2>: ...
   - [ ] (있다면) 회귀 가능성이 있는 영역
   
   ### 알려진 한계 / 후속 작업 (선택)
   - ...
   ```
2. 사용자에게는 `temp/report.md` 링크와 한 줄 요약만 보고한다. 긴 완료 보고 본문을 채팅에 붙이지 않는다.
   - **critic 인용 강제**: "자동 검증 결과" 섹션은 메인이 재평가하지 않는다. critic verdict·사유를 가공·완화 없이 그대로 옮긴다. critic이 Fail이면 보고서도 Fail. 메인은 critic 판정의 **기록자**이지 재심자가 아니다 (검증자와 기록자 분리).
3. `state.status = "done"`, `completed_at` 기록.

출력 위치: 완료 보고 본문은 `temp/report.md`에 덮어쓰기로 작성. 채팅에는 `temp/report.md` 링크와 한 줄 요약만. 영속본은 별도 파일이 아니라 `.claude/state/history/<run_id>/run.json`의 `report_body` 필드에 흡수한다 (도구 가드가 `report.md` Write 차단 → run당 단일 파일).

## temp 입출력 규칙

- `temp/input/`은 사용자가 직접 넣는 참고 자료 위치다. 사용자가 `temp/input/...` 경로를 언급하면 해당 파일을 읽고 필요한 최소 내용만 컨텍스트로 사용한다.
- `temp/output/`은 사용자가 읽을 별도 산출 문서 위치다. 사용자가 별도 문서·정리본·긴 결과물을 요청하면 `temp/output/`에 작성하고 채팅에는 링크와 짧은 요약만 남긴다.
- 워크플로우 기본 산출물은 `temp/plan.md`, `temp/progress.md`, `temp/report.md`를 사용한다.
- 사용자 요청 없이는 `.gitignore`를 수정하지 않는다.

## 세션 재개 (중요)

**모든 세션 시작 시 가장 먼저 `.claude/state/current.json` Read**. (CLAUDE.md 진입점)

- 파일이 없거나 status가 `done`/`aborted` → 신규 요청.
- status가 `searching` / `planning` / `awaiting_approval` / `approved` / `implementing` / `verifying` → AskUserQuestion으로 "재개 / 처음부터 재계획 / 취소".
- status가 `blocked` → 차단 사유 표시 + "계획 수정 / 단계 건너뛰기 / 취소".

재개 시 **이미 done인 단계를 다시 실행하지 않는다**. state의 진행 상황을 신뢰하되, 의심스러우면 해당 단계 산출물이 실제 존재하는지 확인 후 진행.

## 무결성

### 진실의 원천 (Source of Truth)
- **state.json이 SoT**. 워크플로우의 모든 진행 상태·재시도 카운터는 state.json을 기준으로 판단.
- TodoWrite는 사용자 가시성을 위한 **보조 view**. state.json에서 derive돼 표시되는 것으로 취급.
- 갱신 순서: **state.json 먼저 → TodoWrite 동기화**. 역순 금지.
- 둘 사이 불일치가 발견되면 state.json을 신뢰, TodoWrite 재구성.

### 갱신 규칙
- state 갱신은 매 단계 전이마다 한다 (배치로 미루지 않음). 세션이 어디서 끊겨도 손실을 한 단계 이내로 제한.
- state.json 쓰기는 메인만 수행. researcher/planner/coder/critic은 결과만 반환.

### history 영속화

모든 워크플로우 실행의 종료(done/aborted/blocked) 기록을 `.claude/state/history/`에 영속화한다.

**디렉토리 구조**:
```
.claude/state/history/
├── index.jsonl                    # 전체 실행 목록 (한 줄 = 한 run, append-only)
└── <run_id>/
    └── run.json                   # 실행 메타데이터 + report_body (Phase 5 보고서 본문 흡수)
```

> 보고서 본문은 별도 `report.md`가 아니라 `run.json`의 `report_body` 필드에 흡수한다. 하니스 도구 가드가 `report.md` Write를 차단하므로 run당 단일 파일(run.json)로 영속화해 가드와 무관하게 스펙·실태를 일치시킨다.

**`run_id` 형식**: `<ISO-timestamp>__<slug>`
- ISO-timestamp: `YYYY-MM-DDTHH-MM-SS` (콜론 대신 하이픈, UTC+9)
- slug: 요청 첫 줄 kebab-case 30자 컷
- 예: `2026-05-14T10-30-00__add-history-store`

**run.json 스키마**:
```json
{
  "run_id": "2026-05-14T10-30-00__add-history-store",
  "started_at": "2026-05-14T10:30:00+09:00",
  "completed_at": "2026-05-14T10:45:23+09:00",
  "status": "done|aborted|blocked",
  "mode": "full|lite",
  "request": "사용자 원문 요청 (또는 한 줄 요약)",
  "plan_summary": "planner가 확정한 접근 한 단락",
  "retry_count": 0,
  "final_verdict": "Pass|Fail|N/A",
  "report_body": "Phase 5 보고서 본문 (temp/report.md 그대로). aborted/blocked 시 사유 단락."
}
```

별도 `<run_id>/report.md` 파일은 만들지 않는다 — 도구 가드가 `report.md` Write를 차단하므로 보고서 본문은 `run.json.report_body`에 흡수한다.

**index.jsonl 한 줄 스키마**:
```json
{"run_id":"2026-05-14T10-30-00__add-history-store","status":"done","mode":"full","request":"변경 이력 저장 구조 추가","files_changed":2,"retry_count":0,"final_verdict":"Pass"}
```

**쓰기 책임**:
- **메인만** history에 쓴다. researcher/planner/coder/critic은 직접 쓰지 않는다.
- 쓰는 시점: state.status가 done/aborted/blocked로 확정되는 전이에서 (orchestrator.md Phase 5 §4).
- **보존**: 무제한, 자동 청소 없음.

## 임계값 변경 시

**full 재시도 임계값(3회)**을 바꾸려면 다음 네 곳을 함께 갱신 (lite는 자동 1회 + 사용자 카드 1회로 고정, 카운터 없음):
1. 본 파일 — Phase 4 재시도 게이트 섹션
2. [CLAUDE.md](../../CLAUDE.md) — "변경 시 원칙" 섹션
3. [orchestrator.md](../agents/orchestrator.md) — "Phase 4" 섹션
4. [main_full_procedure.md](main_full_procedure.md) — §2 4단계 순서 흐름도

**lite 자동 재시도 횟수(1회)**를 바꾸려면 본 파일 "Lite 모드 실행 흐름" §5 + [CLAUDE.md](../../CLAUDE.md) "Lite 모드" 절을 함께 갱신.

## 출력 위치 규약

사용자가 `input/<파일명>` 식으로 언급하면 Claude는 `temp/input/<파일명>`을 참조 대상으로 해석한다. 사용자가 보고서/문서로 만들어줘 식으로 산출물을 요청하면 Claude는 `temp/output/`에 작성하고 경로 링크로 회신한다.

## AskUserQuestion 사용 지점 (요약)

메인은 다음 모든 분기에서 AskUserQuestion 카드를 띄운다:

| 시점 | 모드 | 옵션 |
|---|---|---|
| 세션 재개 (in-progress 상태) | full | 재개 / 처음부터 재계획 / 취소 |
| 세션 재개 (blocked 상태) | full | 계획 수정 / 단계 건너뛰기 / 취소 |
| 서칭 완료 후 | full | 기획 진입 / 추가 서칭 / 범위 변경 / 취소 |
| 기획 완료 후 | full | (결정 항목 카드 1~3개) + 승인 / 수정요청 / 취소 |
| 검증 1·2회 실패 | full | 자동 재구현 / 방향 변경 / 중단 |
| 검증 3회 실패 (blocked) | full | 계획 수정 / 단계 건너뛰기 / 취소 |
| 자동 재수정 후에도 critic Fail | lite | 자동 재구현 한번 더 / `/full`로 승격 / 중단 |
| 모호한 요구사항 발견 시 | lite·full | 옵션 카드로 결정 |

텍스트로 "Q1: ..., Q2: ..." 나열 금지. 한 호출에 최대 4개 질문 카드 묶음.

## Lite 모드 (기본)

Lite 모드는 4단계 사이클을 적용하지 않는다. 메인 에이전트가 직접 외과적으로 Edit/Write를 수행하고 critic 서브에이전트만 호출해 결과를 검증한다. researcher·planner·coder는 lite에서 호출되지 않는다 (orchestrator.md는 비활성 참조 절차서이므로 lite·full 모두에서 호출되지 않음).

### Lite 모드 실행 흐름

1. **상태 확인**: 메인이 `.claude/state/current.json`을 읽어 in-progress·blocked 상태가 있으면 재개 여부 질의 후 그쪽으로 처리(이 경우 full 워크플로우일 가능성 높음 — 메인이 main_full_procedure 4단계로 진입). 없으면 lite 신규 처리.
2. **외과적 수정**: 메인이 Edit/Write로 사용자 요청을 직접 처리. 변경 줄이 사용자 요청에 직접 트레이스되도록 ([coding_principles.md](coding_principles.md) §3).
3. **critic 호출**: 입력 — 사용자 원문 요청 + 변경 파일 목록 + `mode=lite`. critic이 Pass/Fail + (lite 한정) `recommend_full` 반환.
4. **판정 처리**:
   - **Pass**: 메인이 한 줄 보고. `recommend_full: true`면 "/full 재실행 권장" 안내 추가.
   - **Fail**: 메인이 critic 사유를 받아 **자동 재수정 1회** 후 critic 재호출.
     - **재호출 Pass**: 종료.
     - **재호출 Fail**: AskUser(자동 재구현 한번 더 / `/full`로 승격 / 중단). 응답 처리:
       - "자동 재구현 한번 더" → 메인이 critic 누적 사유로 한 번 더 시도 → critic 재호출 → Pass면 종료, 또 Fail이면 사용자에게 보고하고 종료(이상 자동 재시도 없음).
       - "/full로 승격" → state.json에 mode=full로 초기화하고 메인이 main_full_procedure 4단계 진입 (Phase 1부터 재시작).
       - "중단" → 메인이 history write 후 종료.
5. **history write**: 메인이 종료(Pass·아니면 중단) 시점에 `.claude/state/history/<run_id>/run.json`을 직접 작성. 스키마는 full과 동일. `final_verdict` = `Pass|Fail|N/A`. 작성 후 별도 current.json 초기화는 불필요(lite는 current.json을 안 만들었으므로).

### Lite vs Full 동작 차이

| 항목 | lite | full |
|------|------|------|
| 진입점 | 메인이 직접 Edit/Write | 메인이 main_full_procedure 4단계 진행 |
| 호출되는 서브에이전트 | critic만 | researcher → planner → coder → critic (메인이 지휘) |
| 단계 | 수정 → 검증 (단계 표현 없음) | Phase 1(search) → Phase 2(plan, 승인 필수) → Phase 3(implement) → Phase 4(verify) |
| 변경 주체 | 메인 자체 Edit/Write | coder 서브에이전트 Edit/Write |
| critic 입력 | 사용자 원문 + 변경 파일 + 행동4원칙 | planner 완료조건 + 금지사항 + coder 변경 보고 |
| critic 추가 출력 | `recommend_full` 필드 | 없음 (full이므로 불필요) |
| 자동 재시도 횟수 | 1회 (메인이 critic 사유로 재수정) | retry_count 0~2 자동, 3회면 blocked |
| Fail AskUser 옵션 | 자동 재구현 한번 더 / `/full`로 승격 / 중단 | 자동 재구현 / 방향 변경 / 중단 (3회면 계획 수정 / 단계 건너뛰기 / 취소) |
| state.json | **생성 안 함** | 매 단계 전이마다 갱신 |
| temp/plan.md | 생성 안 함 | 기획서 덮어쓰기 |
| temp/progress.md | 메인이 직접 append (선택) | 메인이 단계마다 append |
| temp/report.md | 메인이 직접 작성 (간략) | 메인이 Phase 5에서 작성 |
| history write 책임자 | 메인 | 메인 |
| history 스키마 | 동일 (run.json·index.jsonl) | 동일 |
| retry 임계값 | 자동 1회 + 사용자 카드 1회 (총 2회 시도 후 종료) | 3 |
