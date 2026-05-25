# /project:export-team

현 하네스의 초기상태(베이스 + state 리셋본)를 `temp/output/` 아래 타임스탬프 폴더로 복사 보존하는 커맨드. 실행하면 깨끗하게 초기화된 멀티에이전트 베이스 한 벌이 만들어지며, 그 폴더를 새 작업 디렉토리에 그대로 복사하면 즉시 동작한다.

> 짝 커맨드 `/project:import-team`은 그 반대 — 이미 베이스가 깔린 작업 디렉토리의 `temp/input/`에 본 export 폴더를 넣고 실행하면, 누적 데이터(history·진행 중 상태)는 보존한 채 베이스 코드만 갱신한다.

## 실행 절차

### 1단계 — 타임스탬프 생성

현재 시각을 `YYYYMMDD_HHMMSS` 형식으로 만든다. 대상 루트 경로를 다음으로 확정한다:

```
temp/output/export-team-<timestamp>/
```

이 경로 문자열을 먼저 변수로 고정해 둔다. 이후 복사·제외 판정에서 "이 경로 하위는 복사 소스에서 제외"를 보장하기 위함이다(자기 재귀 복사 방지의 핵심).

### 2단계 — 대상 디렉토리 생성

`temp/output/export-team-<timestamp>/` 및 필요한 하위 트리를 mkdir 한다.

### 3단계 — 복사 대상 (베이스 초기상태)

다음 항목을 대상 디렉토리에 **같은 상대경로로** 복사한다:

- `CLAUDE.md`
- `.claude/agents/` 전체 (`orchestrator.md`, `researcher.md`, `planner.md`, `coder.md`, `critic.md`)
- `.claude/rules/` 전체 (`coding_principles.md`, `workflow_4stage.md`, `main_full_procedure.md`)
- `.claude/commands/` 전체 (`full.md`, `draft.md`, `init.md`, `export-team.md`, `import-team.md` — 이 커맨드 자기 자신 포함)
- `.claude/scripts/` 전체 (`session_start_hook.py`, `README.md`)
- `.claude/settings.local.json`
- `.claude/state/README.md`
- `.claude/state/history/.gitkeep`
- `temp/input/.gitkeep`, `temp/output/.gitkeep` (빈 스캐폴딩만)

### 4단계 — state 리셋 (복사본에만 적용, 원본 절대 불변)

복사가 끝난 **대상 디렉토리 안에서만** 다음을 수행한다. 원본 `.claude/state/`는 절대 건드리지 않는다.

- `.claude/state/current.json`은 **복사하지 않는다** (대상 디렉토리에 아예 존재시키지 않음). 새 작업 디렉토리에서 첫 세션이 시작되면 메인이 (main_full_procedure를 따라) "파일 없음 = 신규 요청"으로 자연스럽게 진입한다.
- `.claude/state/history/index.jsonl` 및 `<run_id>/` 디렉토리는 **복사하지 않는다** (history는 `.gitkeep`만 존재).

### 5단계 — 제외 (절대 복사 금지)

다음은 어떤 경우에도 대상 디렉토리에 포함하지 않는다:

- `.claude/state/current.json` (현재 진행 중 상태가 그대로 따라가지 않도록)
- `.claude/state/history/<run_id>/`, `.claude/state/history/index.jsonl`
- `temp/plan.md`, `temp/progress.md`, `temp/report.md`
- `temp/input/`의 실제 사용자 자료, `temp/output/`의 실제 산출물
- **특히 `temp/output/export-team-*` 디렉토리는 절대 복사 소스에 포함하지 말 것.** 이전 회차에 생성된 export 결과물이거나 이번 회차의 대상 디렉토리 자신이므로, 복사 소스에 들어가면 무한 재귀 복사가 발생한다. 1단계에서 고정한 대상 경로와 기존 `temp/output/export-team-*`를 명시적으로 제외한 뒤 복사를 수행한다.
- `.git/` (존재할 경우)

### 6단계 — 완료 보고

채팅에 한 줄로 보고한다:

- 생성된 디렉토리 경로: `temp/output/export-team-<timestamp>/`
- 복사된 파일 수
- 안내: "이 디렉토리를 새 작업 폴더에 그대로 복사하면 즉시 동작하는 깨끗한 베이스입니다."

## 안전장치

- 기존 `temp/output/export-team-*` 디렉토리는 건드리지 않는다 — 타임스탬프로 폴더가 분리되므로 덮어쓰기가 아니라 새 폴더로 보존된다.
- `.claude/` 원본은 **읽기 전용**으로만 접근한다. state 리셋(4단계)은 복사본에만 적용한다.
- `.gitignore`는 수정하지 않는다.
- 이 커맨드는 오직 `temp/output/export-team-<timestamp>/` 하위만 생성한다. 그 밖의 어떤 경로도 생성·수정·삭제하지 않는다.

## 권장 구현 방식

호출 시점의 환경에 맞게 판단하되, 다음 순서를 권장한다:

1. 1단계에서 대상 경로 `temp/output/export-team-<timestamp>/`를 먼저 고정한다.
2. Bash `cp -r`로 `CLAUDE.md`와 `.claude/` 트리를 대상 디렉토리에 복사한다. Windows에서도 Git Bash로 Bash 사용이 가능하다.
3. 복사 직후 대상 디렉토리 안에서 5단계 제외 항목(history 누적, temp 워크플로우 산출물 등)을 `rm`으로 제거한다.
4. 대상 디렉토리에 `.claude/state/current.json`이 만들어졌다면 삭제한다 (빈 파일조차 남기지 않음).
5. 복사 소스 경로 산정 시 `temp/output/export-team-*`(특히 이번 대상 경로)를 먼저 명시적으로 제외해 자기 재귀 복사를 차단한다.

## 설계 원칙 (이 커맨드가 따르는 것)

- **원본 불변** — `.claude/state/` 원본은 읽기만. 리셋은 복사본 한정.
- **타임스탬프 격리** — 매 실행이 별도 폴더. 기존 export 결과를 덮어쓰지 않음.
- **자기 재귀 차단** — `temp/output/export-team-*`는 복사 소스에서 명시 제외.
- **깨끗한 베이스** — 누적 history는 제외하고 스캐폴딩(`.gitkeep`)만 보존해, 결과물이 곧바로 새 프로젝트의 초기 베이스가 되도록 한다.
