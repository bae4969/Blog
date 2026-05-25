# /project:full

기본 lite 모드(메인이 직접 Edit/Write + critic 검증)를 4단계 full 모드(researcher→planner→coder→critic)로 전환하는 슬래시 커맨드.

이 prefix가 붙으면 메인이 [`.claude/rules/main_full_procedure.md`](.claude/rules/main_full_procedure.md)를 따라 4단계 사이클(researcher → planner → coder → critic)을 직접 지휘한다 (절차 본문은 [`orchestrator.md`](../agents/orchestrator.md) 참조).

## 언제 쓰나

- 변경 범위가 넓거나 여러 파일에 걸친 작업
- 아키텍처 결정이 필요한 작업
- critic이 lite Fail 후 "recommend_full: true"를 반환했을 때
- 사용자가 서칭·기획 단계의 검토를 원할 때

## 실행 절차

1. 사용자 메시지에서 `/full` prefix를 확인한다.
2. 나머지 요청 내용을 추출한다.
3. state.json을 `mode=full`로 초기화하고 main_full_procedure의 Phase 1부터 시작한다.
4. 메인은 Phase 1(서칭)부터 시작한다 — Phase 0 state 초기화에서 `mode: "full"` 기록.

## 예시

```
/full 인증 미들웨어를 JWT로 교체하고 회귀 테스트 추가해줘
```

→ 메인이 researcher → planner → 사용자 승인 → coder → critic 전체 사이클 실행.

## 주의

- `/full` 없이 시작하면 기본 lite 모드(coder→critic 직행)다.
- lite critic이 Fail + recommend_full: true를 반환해도 자동 승격하지 않는다. 사용자가 명시적으로 결정.
