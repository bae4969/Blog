# 메인 진입점 절차서 — `/full` 모드 4단계 사이클

본 문서는 메인이 `/full` 모드에서 따르는 **진입 절차서**다. 절차 본문(Phase 1~5, 재시도 임계값, history write 스키마 등)은 [`../agents/orchestrator.md`](../agents/orchestrator.md)에 보존된다 — 본 문서는 메인 시점의 진입·차이점만 다룬다.

> orchestrator.md는 **참조 절차서**로 유지된다. Claude Code의 서브에이전트로는 호출되지 않으나, 절차 본문의 single source of truth 역할을 한다. "본 에이전트가 X 한다"는 표현은 메인이 X로 흡수해 읽는다 (§4 참조).

## §1 진입 트리거

- 사용자 요청이 `/full` prefix로 시작하면 메인이 본 절차를 시작한다.
- `/full` prefix가 없으면 lite 모드 — 본 절차는 무시한다 ([workflow_4stage.md](workflow_4stage.md) "Lite 모드" 절 참조).
- lite vs full 모드 결정은 **`/full` slash prefix 매칭으로만** 한다 (다른 slash command — `/draft`, `/init` 등 — 은 자체 동작을 가지며 lite/full 모드 자체를 바꾸지 않는다). "이 요청은 간단해 보임" 같은 휴리스틱으로 모드를 바꾸는 것 금지.

## §2 4단계 순서

메인이 다음 4개 서브에이전트를 차례로 호출한다 (researcher → planner → coder → critic). 서브에이전트끼리 직접 통신하지 않고, 모든 핸드오프는 메인을 거친다.

```
/full 유저 요청
  ↓ (메인이 main_full_procedure 진입)
[Phase 1 SEARCH]   메인 ─Agent→ researcher  → AskUser(기획 진입 / 추가 서칭 / 범위 변경 / 취소)
  ↓
[Phase 2 PLAN]     메인 ─Agent→ planner     → AskUser(승인 / 수정요청 / 취소)  ← 승인 없이는 구현 진입 금지
  ↓
[Phase 3 IMPLEMENT] 메인 ─Agent→ coder       → Edit/Write로 파일 변경, Bash로 자체 검증
  ↓
[Phase 4 VERIFY]   메인 ─Agent→ critic
   ├─ Pass → Phase 5(REPORT) → state.status=done, history write, 종료
   └─ Fail → state.retry_count += 1
        ├─ retry_count < 3 : AskUser(자동 재구현 / 방향 변경 / 중단) → Phase 3 또는 Phase 2로 복귀
        └─ retry_count == 3: state.status=blocked, AskUser(계획 수정 / 단계 건너뛰기 / 취소)
```

- 단계 전이마다 메인이 `.claude/state/current.json`을 갱신하고 `temp/progress.md`에 한 줄 append.
- AskUserQuestion 카드는 메인이 띄운다 (서칭 후·기획 후 승인 필수·검증 1·2회 실패 후·검증 3회 실패 후 등 orchestrator.md에 명시된 모든 지점).

## §3 단계별 책임 매핑

각 Phase의 상세 규약은 [`../agents/orchestrator.md`](../agents/orchestrator.md)의 해당 절을 그대로 따른다. **호출자만 메인으로 흡수**한다.

| Phase | 호출 서브에이전트 | 상세 규약 위치 |
|---|---|---|
| Phase 0 — 요청 접수 | (없음, 메인이 state 초기화 + TodoWrite) | [orchestrator.md §Phase 0](../agents/orchestrator.md) |
| Phase 1 — SEARCH | researcher | [orchestrator.md §Phase 1](../agents/orchestrator.md) |
| Phase 2 — PLAN | planner | [orchestrator.md §Phase 2](../agents/orchestrator.md) |
| Phase 3 — IMPLEMENT | coder | [orchestrator.md §Phase 3](../agents/orchestrator.md) |
| Phase 4 — VERIFY | critic | [orchestrator.md §Phase 4](../agents/orchestrator.md) |
| Phase 5 — REPORT | (없음, 메인이 temp/report.md 작성 + history write) | [orchestrator.md §Phase 5](../agents/orchestrator.md) |

각 Phase의 호출자는 메인이다. 서브에이전트 호출 계약(목표·컨텍스트·입력·출력 형식·완료 조건)도 메인이 작성해서 프롬프트에 박는다.

## §3.1 coder 호출 프롬프트 — 사용자 원문 같이 인용

Phase 3에서 메인이 coder를 호출할 때, planner의 "coder 변경 명세" 블록만 단독으로 인용하지 않는다. **사용자 원 요청(첫 메시지 본문)**을 별도 섹션으로 명세 블록 위에 같이 인용한다.

```text
## 사용자 원 요청
<원문 그대로>

## planner 변경 명세
<planner 산출 명세 블록 그대로>

## (재호출 시) 이전 시도 실패 사유
- <critic 사유 1>
- <critic 사유 2>
```

이유: planner 명세는 "무엇을 바꾸나"를 압축한 결과라 사용자 원문의 톤·인텐트가 lossy해진다. coder가 가정 충돌·범위 모호함을 만났을 때 사용자 원문을 직접 보면 더 합당한 판단을 내릴 수 있다. 명세는 "어디·무엇·완료 조건", 원문은 "왜·강도·뉘앙스"를 담당.

본 §3.1은 [workflow_4stage.md](workflow_4stage.md) Phase 3·[`../agents/orchestrator.md`](../agents/orchestrator.md) Phase 3 입력 계약과 같이 동기화돼 있다 (2026-05-22 sweep 완료). 형식 변경 시 세 문서를 함께 갱신한다.

## §4 차이점 메모 — "본 에이전트" 표현 흡수

[`../agents/orchestrator.md`](../agents/orchestrator.md) 본문은 1인칭("당신은 Orchestrator다") 또는 "orchestrator가 X" / "본 에이전트가 X" 형식으로 쓰여 있다 (절차 본문 SoT 역할로 보존). 메인은 이 표현을 다음 규약으로 **읽는다** — 다른 문서(planner·coder·critic·researcher·workflow_4stage)의 본문은 이미 메인 시점으로 일관됐으므로 본 §4 흡수규약은 orchestrator.md에만 적용된다:

- "당신은 Orchestrator다" → "메인이 본 절차를 수행한다".
- "본 에이전트가 X를 한다" → "메인이 X를 한다".
- "orchestrator가 state.json을 갱신한다" → "메인이 state.json을 갱신한다".
- "orchestrator가 critic을 호출한다" → "메인이 critic을 호출한다".

orchestrator.md는 비활성 절차서로 보존된다 (서브에이전트로 호출되지 않음). 절차 본문 SoT 역할을 유지함으로써 본 문서를 짧게 유지하고 동기화 부담을 줄인다.

## §5 history write

종료(`state.status` = `done` / `aborted` / `blocked`) 전이에서 메인이 직접 `.claude/state/history/<run_id>/run.json`과 `.claude/state/history/index.jsonl`에 한 줄을 작성한다. `run_id` 형식·스키마·`final_verdict` 값(Pass/Fail/N/A)은 [`../state/README.md`](../state/README.md) "history/ 영속화" 절과 [`../agents/orchestrator.md`](../agents/orchestrator.md) §Phase 5 §4를 따른다.

- 별도 `<run_id>/report.md` 파일은 만들지 않는다 — 도구 가드가 `report.md` Write를 차단하므로 보고서 본문은 `run.json.report_body` 필드에 흡수한다.
- aborted·blocked 종료 시에도 동일하게 적용 (status·final_verdict만 달라짐, final_verdict=N/A).
- history write 후 `.claude/state/current.json`을 `{}`로 초기화한다.
- **lite·full 모두 메인이 history write 책임자**다 (full에서는 본 절차에 따라).

## §6 AskUserQuestion 사용 지점 (메인이 카드를 띄우는 곳)

메인은 다음 분기에서 텍스트 나열 대신 AskUserQuestion 카드를 띄운다 (한 호출 최대 4개 질문). 자세한 옵션은 [`../agents/orchestrator.md`](../agents/orchestrator.md) 본문의 해당 절을 그대로 따른다.

- 세션 재개 (in-progress 상태): "재개 / 처음부터 재계획 / 취소"
- 세션 재개 (blocked 상태): "계획 수정 / 단계 건너뛰기 / 취소"
- Phase 1 SEARCH 종료 후: "기획 진입 / 추가 서칭 / 범위 변경 / 취소"
- Phase 2 PLAN 종료 후: (결정 항목 1~3개) + "승인 / 수정요청 / 취소" — **승인 없이는 Phase 3 진입 금지**
- Phase 4 VERIFY 1·2회 실패: "자동 재구현 / 방향 변경 / 중단"
- Phase 4 VERIFY 3회 실패 (blocked): "계획 수정 / 단계 건너뛰기 / 취소"

## §7 세션 재개

세션 시작 시 메인이 `.claude/state/current.json`을 먼저 Read해 분기:

- `done` / `aborted` / 비어 있음 → 신규 요청 처리.
- in-progress 상태(`searching` / `planning` / `awaiting_approval` / `approved` / `implementing` / `verifying`) → "재개 / 처음부터 재계획 / 취소" 카드.
- `blocked` → 차단 사유 표시 + "계획 수정 / 단계 건너뛰기 / 취소" 카드.

재개 시 이미 done인 Phase는 다시 실행하지 않는다. 자세한 절차는 [`workflow_4stage.md`](workflow_4stage.md) "세션 재개" 절 참조.
