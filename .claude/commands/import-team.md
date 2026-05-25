# /project:import-team

`temp/input/export-team-*` 패키지를 감지해 현 작업 디렉토리의 **베이스 코드만** 갱신하는 커맨드. `/export-team`의 역상이다. export-team이 "베이스를 빼서 깨끗한 패키지로" 만든다면, import-team은 "그 패키지를 다시 베이스로 흡수"한다.

누적 데이터(history·진행 중 워크플로우 상태·사용자 자료)는 **절대 건드리지 않는다**. 따라서 다른 곳에서 베이스 코드만 진화시킨 export-team 패키지를 받아 이 작업 디렉토리에 갱신할 때 안전하게 쓸 수 있다.

## 실행 절차

### 1단계 — 소스 폴더 탐색

`temp/input/export-team-*` 패턴으로 glob 한다.

- **0개**: 사용자에게 "감지된 export-team 패키지 없음. `temp/input/`에 `export-team-<timestamp>/` 폴더를 넣고 다시 실행하라"고 안내 후 종료.
- **1개**: 그 폴더를 소스로 확정.
- **2개 이상**: AskUserQuestion 카드로 선택받기 (옵션 라벨에 폴더명 그대로, 가장 최근 mtime이 Recommended).

확정된 소스 경로를 변수로 고정한다 (이후 단계에서 같은 경로 재사용).

### 2단계 — 패키지 검증

확정된 소스 폴더 안에 다음 베이스 자산이 모두 존재하는지 확인한다:

- `CLAUDE.md`
- `.claude/agents/` (5개 에이전트 .md)
- `.claude/rules/`
- `.claude/commands/`
- `.claude/scripts/`
- `.claude/settings.local.json`
- `.claude/state/README.md`

하나라도 없으면 "유효한 export-team 패키지가 아님 (누락: ...)"으로 안내 후 종료. 변경은 전혀 수행하지 않는다.

### 3단계 — 변경 사항 미리보기 + 승인

실제 덮어쓰기 전에 무엇이 바뀔지 채팅에 짧게 요약한다:

- **새로 추가될 파일**: 현재 디렉토리에 없는 N개 (파일 경로 목록)
- **덮어쓰여질 파일**: 내용이 다른 M개 (파일 경로 목록)
- **변경 없음**: 동일 K개 (개수만)

요약이 길어질 것 같으면 본문은 `temp/output/import-team-preview-<timestamp>.md`에 쓰고 채팅에는 링크와 핵심 한 줄만 둔다.

이어 **AskUserQuestion** 카드로 결정 받기:

- **적용** (Recommended) — 백업 후 덮어쓰기 수행
- **취소** — 종료, 어떤 변경도 하지 않음

### 4단계 — 백업 (적용 전)

적용 전, 영향받는 파일(3단계의 "덮어쓰여질 파일")만을 백업 폴더에 보존한다:

```
temp/output/import-team-backup-<YYYYMMDD_HHMMSS>/
```

- 백업 대상 파일은 **현재(import 직전) 버전**이다. 같은 상대경로를 유지한 채 복사한다.
- 새로 추가될 파일은 백업 대상 아님(원본 없으므로).
- 동일 파일도 백업 대상 아님.
- 백업이 비어 있을 수도 있다 (덮어쓰여질 파일이 0개인 경우). 그러면 폴더만 생성하고 진행.

### 5단계 — 적용 (덮어쓰기)

소스 → 현 디렉토리로 **같은 상대경로**로 복사한다:

- `CLAUDE.md`
- `.claude/agents/` 전체
- `.claude/rules/` 전체
- `.claude/commands/` 전체 (이 커맨드 자기 자신 `import-team.md`도 포함될 수 있음 — 자기 갱신 허용)
- `.claude/scripts/` 전체
- `.claude/settings.local.json`
- `.claude/state/README.md`

소스 폴더 안에 있는 그 외 파일(예: `temp/input/.gitkeep`, `temp/output/.gitkeep`)은 현 디렉토리에 같은 경로의 동일 파일이 이미 있을 것이므로 굳이 적용할 필요 없다 — 적용해도 무해하지만 3단계의 변경 요약에서 "변경 없음"으로 분류된다.

### 6단계 — 절대 건드리지 않음 (보존 대상)

다음은 import 중 어떤 경로로도 덮어쓰거나 삭제하지 않는다:

- `.claude/state/current.json` — 진행 중인 워크플로우 상태 (있다면 그대로 유지, 없으면 새로 만들지 않음)
- `.claude/state/history/index.jsonl`, `.claude/state/history/<run_id>/` — 누적 실행 이력
- `temp/input/`의 사용자 자료 (소스 패키지 폴더 `temp/input/export-team-*` 자체도 그대로 둠)
- `temp/output/`의 기존 사용자 산출물·이전 백업
- `temp/plan.md`, `temp/progress.md`, `temp/report.md` (있다면 진행 중 워크플로우 산출물)
- `.git/` (존재할 경우)

소스 패키지에는 `.claude/state/current.json`이 **아예 존재하지 않는다** (`/export-team`이 복사 대상에서 제외). 따라서 자연스럽게 보존 대상에 포함되고, 현 디렉토리에 이미 있는 진행 상태가 그대로 유지된다.

### 7단계 — 완료 보고

채팅에 짧게 보고:

- 소스 패키지 경로: `temp/input/export-team-<timestamp>/`
- 새로 추가된 파일 수 / 덮어쓰여진 파일 수 / 변경 없음 수
- 백업 경로: `temp/output/import-team-backup-<timestamp>/` (덮어쓰여진 파일의 직전 버전 보존)
- 안내: "소스 패키지는 `temp/input/`에 그대로 두었습니다. 더 이상 필요 없으면 직접 삭제하세요."

## 안전장치

- **변경 전 승인 필수** — 3단계 AskUserQuestion 승인 없이는 5단계로 진입하지 않는다.
- **백업 우선** — 5단계 덮어쓰기 전에 4단계 백업이 완료되어 있어야 한다. 백업 실패 시 적용 중단.
- **누적 데이터 절대 불변** — 6단계 보존 대상은 어떤 흐름으로도 영향받지 않는다.
- **부분 실패 대응** — 5단계 중간에 실패하면 백업 폴더로 수동 복원 가능하도록 백업 구조를 같은 상대경로로 유지한다.
- **자기 갱신 허용** — 소스가 더 새로운 `import-team.md`/`export-team.md`를 포함할 수 있고, 이는 정상 덮어쓰기 대상이다.

## 권장 구현 방식

호출 시점의 환경에 맞게 판단하되, 다음 순서를 권장한다:

1. 1단계에서 소스 경로를 먼저 확정해 변수로 고정.
2. 2단계 검증 통과 후, 소스/현재 두 트리를 순회하며 파일 단위로 비교해 (1) 새로 추가 (2) 덮어쓰기 (3) 동일 세 그룹으로 분류. 비교는 내용 해시 또는 단순 `Compare-Object`/`diff`로 충분.
3. 3단계에서 미리보기를 사용자에게 보이고 AskUserQuestion 승인 받기. 취소면 즉시 종료.
4. 4단계 백업 → 5단계 적용 순서 엄수.
5. 6단계 보존 대상은 절대 복사 소스로 다루지 않는다.

## 설계 원칙 (이 커맨드가 따르는 것)

- **베이스 코드 vs 누적 데이터 분리** — import는 베이스 코드만 갱신, 누적 데이터는 불변.
- **승인 필수** — 덮어쓰기는 위험하므로 변경 미리보기 + 명시적 승인 없이는 적용하지 않음.
- **백업 우선** — 덮어쓰기 이전 버전을 항상 `temp/output/import-team-backup-*`에 보존.
- **export-team의 역상** — export가 빼서 패키지로 만들면, import가 패키지를 다시 흡수. 같은 자산 목록을 공유한다.
