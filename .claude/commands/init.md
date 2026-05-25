# /project:init

새 프로젝트(=사용자 코드베이스)에 들어왔을 때 Claude가 코드를 읽고 의도를 파악하되, 확신 못 하는 지점은 사용자에게 묻고 그 결과를 `.claude/memory/`(사실)와 `.claude/rules/`(행동 지시)로 분리해 기록하는 커맨드.

한 실행에서 critical 4문항만 묻고 종료. 나머지는 `project-intent.md`의 Unresolved 섹션에 적어두고 다음 `/project:init` 재실행 때 거기서부터 이어 처리한다.

## 실행 절차

### 0단계 — 재실행 감지

`.claude/memory/project-intent.md`가 존재하는지 확인한다.

- **있음** → AskUserQuestion 카드로 결정 받기:
  - Unresolved 이어서 (Recommended, Unresolved 섹션에 항목이 있을 때)
  - 처음부터 다시 (스캔·가설부터 새로 — 기존 파일 백업 후 덮어쓰기)
  - 취소
- **없음** → 1단계로.

처음부터 다시를 선택하면 적용 전 백업한다 (`.claude/memory/.backup-<YYYYMMDD_HHMMSS>/project-intent.md`).

### 1단계 — 스캔

다음 정보를 모은다 (Claude 단독 수행, 사용자 노출 X):

- 디렉토리 트리 (Glob, depth 2~3 권장)
- README 계열: `README.md`, `README.rst`, `README.txt`
- 메타 파일: `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `CMakeLists.txt` / `build.gradle` / `Gemfile` / `composer.json`
- 진입점 후보: `main.*` / `index.*` / `app.*` / `server.*` / `__main__.py`
- 기존 `.claude/memory/project-intent.md`가 있으면 Unresolved 섹션 추출 (재실행 경로용)

### 2단계 — 1차 가설 작성 (내부)

스캔 결과를 토대로 Claude가 독자적으로 정리한다. 이 단계 산출물은 사용자에게 노출하지 않는다 (3단계에서 모호함만 추출해 사용).

- 프로젝트 유형: 라이브러리 / CLI / 서비스(웹·서버) / 실험 코드 / 모노레포 / 데이터 분석
- 디렉토리별 용도 추측 (확신 정도와 함께)
- 핵심 외부 의존성 (DB, 메시지큐, 외부 API, 인증 시스템 등)
- 실행 방법 추측 (`npm start`, `python -m ...`, 진입점 파일 직접 실행 등)
- 테스트 방법 추측 (`pytest`, `npm test`, `cargo test` 등)

### 3단계 — 모호함 후보 추출 & 우선순위

다음 6종류에서 모호한 지점을 찾는다:

1. **용도 불명 폴더/파일** — 이름만으로 추측 안 되는 항목
2. **패턴 혼재** — 두 가지 명명 규칙·언어·프레임워크가 섞여 있음
3. **외부 의존 불명** — 어떤 외부 시스템(DB·API·인증)을 쓰는지 코드만으로는 안 보임
4. **타깃 모호** — 라이브러리/CLI/서비스/실험 중 무엇이 정답인지 불확실
5. **테스트·실행 방법 불명** — 어떻게 돌리는지·테스트하는지 적혀있지 않음
6. **deprecated/실험 영역** — 안 쓰는 것 같은데 남아있는 코드

**우선순위 기준**: 답을 모른 상태에서 코드 변경을 시도했을 때 잘못된 결과를 만들 위험도 순. critical 4개를 추출.

후보가 4개 미만이면 있는 만큼만, 0개면 4단계 건너뛰고 5단계 직행 (Unresolved 없음).

### 4단계 — AskUserQuestion (4문항 한 배치)

한 호출에 최대 4개 질문 카드를 묶어 띄운다. 각 질문에는 Claude의 1차 추측을 (Recommended) 선택지로 포함해 사용자가 빠르게 확정할 수 있게 한다.

각 카드의 옵션 구성:
- Claude의 1차 추측 (Recommended)
- 대안 추측 (있으면 1~2개)
- "잘 모르겠음 / Unresolved로 넘김" — 항상 마지막 옵션으로 포함

사용자가 "Unresolved로 넘김"을 선택한 항목은 5단계에서 Unresolved 섹션에 마지막 추측과 함께 기록한다.

**재실행(Unresolved 이어서) 경로**:
- `.claude/memory/project-intent.md`의 Unresolved 섹션에서 다음 4개 항목을 추출한다.
- 동일한 AskUserQuestion 패턴으로 묻는다.
- 응답을 받으면 해당 항목을 Unresolved에서 제거하고 본문에 반영한다.

### 5단계 — 기록 (memory/rules 분리)

#### `.claude/memory/project-intent.md` 작성/갱신

신규 작성 또는 기존 본문에 응답 반영. 템플릿:

```markdown
# project-intent

updated: <YYYY-MM-DD>

## 프로젝트 한 줄 정의
<한 줄>

## 디렉토리 용도
| 경로 | 용도 |
|------|------|
| ... | ... |

## 외부 시스템·의존성
- ...

## 실행/테스트 방법
- 실행: `<명령>`
- 테스트: `<명령>`

## Unresolved
- [ ] <항목 1> — 마지막 추측: ...
- [ ] <항목 2>
```

재실행 시 해소된 항목은 Unresolved에서 제거하고 본문 표·리스트에 반영. 남은 Unresolved는 그대로 유지.

#### `.claude/rules/<주제>.md` 작성 (행동 지시가 도출됐을 때만)

사용자 답변이 "이 컨벤션을 지켜라" / "이 디렉토리는 손대지 마라" 같은 **행동 지시성** 내용일 때만 별도 파일로 분리한다.

- 주제별 파일명 예: `naming-convention.md`, `test-strategy.md`, `untouchable-areas.md`
- 형식은 글로벌 `~/.claude/rules/` 패턴을 따른다 (짧은 본문, **Why:** / **How to apply:** 라인 권장)

#### 인덱스 처리

- `.claude/memory/MEMORY.md` 존재 → `project-intent.md` 항목 한 줄 추가/갱신.
- `.claude/rules/RULES.md` 존재 → 새로 만든 rules 파일 항목 한 줄 추가.
- **인덱스 파일이 없으면** AskUserQuestion 카드로 결정 받기:
  - 인덱스 파일도 생성 (Recommended)
  - 생성하지 않음 — Unresolved에 "인덱스 미생성" 기록만

### 6단계 — 폴더 생성 보장

- `.claude/memory/` 없으면 생성.
- `.claude/rules/` 없으면 생성.
- 생성한 폴더가 있으면 채팅에 한 줄 알림 (예: "신규 폴더 생성: `.claude/memory/`, `.claude/rules/`").

### 7단계 — 완료 보고

채팅에 다음 형식으로 짧게 보고한다 (본문은 파일에 두고 링크만):

```
## /project:init 완료

산출물: .claude/memory/project-intent.md
프로젝트: <한 줄 정의>
이번 회차 해소: N개
Unresolved 남음: M개

다음 /project:init 재실행 시 Unresolved부터 이어 처리합니다.
```

- 새로 만든 rules 파일이 있으면 경로를 함께 표시.
- Unresolved가 0이면 "모든 모호함 해소됨" 한 줄 추가.

## 안전장치

- `temp/input/`은 사용자 자료라 절대 손대지 않는다.
- `.git/`, `.claude/state/`, lock 파일, CI 설정은 변경하지 않는다.
- 본 커맨드는 **오직** `.claude/memory/`, `.claude/rules/` 하위와 그 인덱스(`MEMORY.md`, `RULES.md`)만 생성/수정한다.
- 기존 `project-intent.md`를 덮어쓰는 경로(0단계의 "처음부터 다시")에서는 백업 디렉토리(`.claude/memory/.backup-<timestamp>/`)에 원본을 먼저 복사한다.

## 설계 원칙 (이 커맨드가 따르는 것)

- **묻기 전에 추측한다** — 무작정 질문 폭격이 아니라 1차 가설 작성 후 모호한 지점만 추림.
- **한 번에 critical 4개** — 사용자 피로 최소화. 나머지는 Unresolved로 이연.
- **사실은 memory, 행동은 rules** — 글로벌 분류 체계 (`~/.claude/`)와 동일.
- **재진입 가능** — Unresolved 섹션이 다음 회차의 입력이 됨.
