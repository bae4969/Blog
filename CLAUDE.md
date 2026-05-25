# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 코드베이스 개요 — PHP 블로그 + 시장/금융 대시보드

PHP 8.2 MVC 모놀리스. 단일 진입점 [public/index.php](public/index.php) 가 라우트 등록·디스패치를 모두 담당. PSR-4 오토로더는 `Blog\` → `src/` 한 줄만 사용.

## 자주 쓰는 명령

```bash
# 의존성
composer install                # PHP 의존성 (vendor/는 gitignore)
npm install                     # 프론트 자산 (Quill 등)

# 설정 — 최초 1회
cp -r config.example/* config/  # config/는 gitignore. 복사 후 DB/API 키 편집

# 캐시 디렉토리
mkdir -p cache/data && chmod 755 cache cache/data

# 로컬 서버
php -S localhost:80 -t public   # DocumentRoot = public/

# 테스트
composer test                   # PHPUnit 11
composer test-coverage          # tests/ → coverage/ (HTML)
./vendor/bin/phpunit --filter <TestName>   # 단일 테스트

# Docker
docker build -t php-blog:latest .          # PHP 8.2-Apache, prod 기본
docker build --build-arg APP_ENV=development -t php-blog:dev .   # dev (display_errors=1)
```

`APP_ENV=development` 환경변수가 [public/index.php:19](public/index.php#L19)와 [public/index.php:28](public/index.php#L28)에서 에러 표시·HTTPS 강제 우회를 분기한다.

## 단일 진입점 + 사전 라우트 가드 체인

[public/index.php](public/index.php) 는 라우트 정의 파일이 아니라 **실행 파이프라인** 그 자체다. 라우트 dispatch에 도달하기 전에 다음이 순서대로 수행된다 (각 단계가 즉시 종료 가능):

1. **HTTPS 리다이렉트** — `APP_ENV != development` && (`HTTPS` off || `X-Forwarded-Proto != https`) → 301
2. **클라이언트 IP 추출** — `trusted_proxies`에 등록된 source만 `X-Forwarded-For` 신뢰. 그 외는 `REMOTE_ADDR` 그대로
3. **IP 차단 체크** ([BlockedIp 모델](src/Models/BlockedIp.php) — `whitelist` 우선, 그다음 영구·임시 차단 조회
4. **자동 차단 트리거** — 의심 URL 패턴(`config/config.php` `ip_block.suspicious_url_patterns`), 봇 UA 패턴, 분당 요청 수 초과 → `block_duration[low|medium|high]` 적용 후 즉시 차단
5. **세션 시작 + 1회 접속 로깅** ([Logger](src/Core/Logger.php) `access` 채널)
6. **Router::dispatch** — 라우트 핸들러 실행

라우터([src/Core/Router.php](src/Core/Router.php))는 의도적으로 단순하다: linear scan + `:id` 파라미터 매칭, 미스 시 [Router::track404](src/Core/Router.php) 가 IP별 404 카운터를 증가시켜 4번 단계와 연동된다. 새 라우트는 항상 [public/index.php](public/index.php)에 등록한다 (자동 디스커버리 없음).

## MVC 계층 규약

| 계층 | 위치 | 역할 |
|---|---|---|
| Controllers | [src/Controllers/](src/Controllers/) | [BaseController](src/Controllers/BaseController.php) 상속 — 생성자에서 `Auth`/`Session`/`View` 주입. CSRF 검증, JSON/Redirect/Render 헬퍼 제공 |
| Core 인프라 | [src/Core/](src/Core/) | Router, Auth, Session, Cache(싱글턴), View, Logger, HtmlSanitizer(HTMLPurifier 래퍼), `*Config` (외부 AI/YouTube 키) |
| Models | [src/Models/](src/Models/) | DB 접근 + **모델 내부에서 Cache 직접 호출** (별도 Repository 계층 없음) |
| Database | [src/Database/Database.php](src/Database/Database.php) | PDO 싱글턴. 모든 쿼리는 prepared statement 강제 |
| Services | [src/Services/](src/Services/) | 외부 API 통합 (YouTube, Gemini, OpenAI, Backtest) — 컨트롤러가 직접 호출 |
| Views | [views/](views/) | 도메인별 폴더(`blog/`, `admin/`, `stock/`, `func/`, `home/`). 공통 partial은 `home/` |

## 캐시 — 2계층 싱글턴

[src/Core/Cache.php](src/Core/Cache.php) 는 메모리(요청 단위) + 파일(영속) 2계층이다. `Cache::getInstance()` 싱글턴. TTL은 [config/cache.php](config/cache.php) 의 키별 설정을 따른다. 키 생성은 `Cache::key($prefix, ...$parts)` 헬퍼 사용 (네임스페이스 통일). 모델 변경 시 `Cache::deletePattern()` 으로 관련 키 모두 무효화 — 단일 키 삭제만 하면 stale 위험.

## 권한 모델 (역방향 주의)

**`user_list.user_level` 값이 낮을수록 권한이 높다.** 0=슈퍼관리자, 4=기본 구독자. [Auth](src/Core/Auth.php) 가드는 항상 `<=` 비교. 신규 가드 추가 시 부등호 방향 헷갈리지 말 것 (README "권한 체계" 표 참조).

## 보안 — 어디서 처리되는지

| 보호 | 위치 |
|---|---|
| CSRF 토큰 | [BaseController::validateCsrfToken](src/Controllers/BaseController.php) — 모든 POST에서 자동 검증, 검증 후 재생성 |
| CSP nonce | [View](src/Core/View.php) — 요청마다 새 nonce 생성, 인라인 `<script>`에 주입 |
| XSS | 리치 콘텐츠 = HTMLPurifier ([HtmlSanitizer](src/Core/HtmlSanitizer.php)), 일반 출력 = `htmlspecialchars` |
| 비밀번호 | Argon2ID (`password_hash`/`verify`), 레거시 SHA256 로그인 성공 시 자동 마이그레이션 |
| 세션 | HttpOnly + SameSite=Lax + Secure, IP+UA 바인딩 ([Session](src/Core/Session.php)) |
| IP 자동 차단 | [public/index.php](public/index.php) (사전) + 컨트롤러 단위 트리거 (404·로그인 실패) |
| API 보호 | `X-Requested-With` 헤더 + Origin/Referer 이중 검증 (`/stocks/api/*` 등) |

새 폼/엔드포인트 추가 시: POST → CSRF 검증 통과 보장, 리치 텍스트 입력 → `HtmlSanitizer::purify`, 사용자 입력 SQL → PDO bind만 사용.

## DB 스키마

[sql/](sql/) 의 `*.sql` 파일이 각 테이블 정의. 마이그레이션 도구는 없고 수동 적용. 컬럼 추가 시 해당 모델 SELECT 컬럼 목록도 함께 갱신.

## 설정 파일 누락 시

`config/` 는 gitignore. `config.example/` 에 없는 새 키를 `config/`에 추가했다면 반드시 `config.example/` 에도 sentinel 값으로 추가해야 한다 (다른 환경에서 silent 실패).

---

# 멀티에이전트 베이스 — lite/full 듀얼 모드 (Claude only)

이 작업 디렉토리는 **기본 lite 모드(메인이 직접 Edit/Write → critic 검증)**로 동작하며, `/full` 슬래시 커맨드 사용 시에만 **4단계(서칭→기획→구현→검증)**로 진입하는 멀티에이전트 베이스다. lite에서는 메인이 외과적으로 직접 수정한 뒤 `critic`만 호출해 결과를 검증한다. `/full` 시에는 메인이 [`.claude/rules/main_full_procedure.md`](.claude/rules/main_full_procedure.md)를 따라 researcher/planner/coder/critic을 차례로 호출하며, 절차 본문은 [`.claude/agents/orchestrator.md`](.claude/agents/orchestrator.md)에 보존된다 (서브에이전트가 아닌 참조 절차서). 외부 CLI·다른 모델에 의존하지 않는 Claude only 구성이다.

## 모든 세션 시작 시 — 절대 진입 절차

1. **`.claude/state/current.json` 먼저 확인** (워크플로우 재개 여부 판단).
   - `status`가 `searching` / `planning` / `awaiting_approval` / `approved` / `implementing` / `verifying` → 사용자에게 재개·재계획·취소 옵션 질의(AskUserQuestion) 후 지시 대기.
   - `status`가 `blocked` → 차단 사유 표시 후 AskUserQuestion으로 "계획 수정 / 단계 건너뛰기 / 취소" 옵션 질의.
   - `status`가 `done` / `aborted` / 비어 있음 → 신규 요청으로 처리.
2. 신규 요청 처리 시 **모드 결정**:
   - 요청이 `/full`로 시작하면 → `mode=full`, 메인이 [`main_full_procedure`](.claude/rules/main_full_procedure.md)를 따라 4단계(researcher→planner→coder→critic) 실행.
   - `/full` prefix 없으면 → `mode=lite`, 메인이 직접 Edit/Write로 외과적 수정 후 `critic` 서브에이전트만 호출.
   - lite vs full 모드 결정은 `/full` slash prefix 매칭으로만 한다(다른 slash command — `/draft`, `/init` 등 — 은 자체 동작을 가지며 lite/full 모드 자체를 바꾸지 않는다). LLM이 "이 요청은 간단해 보인다" 같은 휴리스틱으로 모드를 바꾸는 것 금지.
3. lite 작업도 비단순 요청이면 본 사이클을 따른다. 단순 조회·typo는 메인이 즉시 처리(workflow_4stage.md "음성 예시" 참조).

## 모드별 사이클

### Lite 모드 (기본, `/full` prefix 없을 때)

```
유저 요청
  ↓
[수정]    메인이 직접 Edit/Write로 외과적 수정
  ↓
[검증]    critic 서브에이전트
   ├─ Pass + recommend_full:false → 메인이 한 줄 보고 → 종료
   ├─ Pass + recommend_full:true  → 메인이 보고 + 사용자에게 /full 재실행 안내
   └─ Fail → 메인이 critic 사유 받아 **자동 재수정 1회** → critic 재호출
        ├─ 재호출도 Fail → AskUser(자동 재구현 한번 더 / /full로 승격 / 중단)
        └─ 재호출 Pass → 종료
```

- 재시도 카운터·`blocked` 상태는 lite에서 쓰지 않는다 (full만 사용).
- `state.json`은 lite에서 생성·갱신하지 않는다. lite 종료 시에만 메인이 `history/<run_id>/run.json`을 작성한다 (스키마 동일).
- `temp/plan.md`는 lite에서 만들지 않는다. `temp/progress.md`·`temp/report.md`는 메인이 직접 작성.

### Full 모드 (`/full` prefix 사용 시)

```
# 절차서: main_full_procedure.md, 본문: orchestrator.md (비활성 참조)
/full 유저 요청
  ↓ (메인이 main_full_procedure 진입, mode=full)
[1 서칭]   메인 ─Agent→ researcher    → AskUser(범위 확정/추가 서칭)
  ↓
[2 기획]   메인 ─Agent→ planner       → AskUser(승인 / 수정 / 취소)  ← 승인 없이는 구현 진입 금지
  ↓
[3 구현]   메인 ─Agent→ coder         → Edit/Write로 파일 직접 변경, Bash로 자체 검증
  ↓
[4 검증]   메인 ─Agent→ critic
   ├─ Pass → REPORT → state.status=done, 종료
   └─ Fail → state.retry_count += 1
        ├─ retry_count < 3 : AskUser(자동 재구현 / 방향 변경 / 중단) → [3]로 복귀
        └─ retry_count == 3: 루프 중단, state.status=blocked
                              AskUser(계획 수정 / 단계 건너뛰기 / 취소)
```

매 단계 전이마다 `.claude/state/current.json`을 갱신해 세션이 끊겨도 재개 가능.

## 구성 — 5개 서브에이전트 (full 전용 4개 + lite/full 공용 1개)

| 에이전트 | 도구 | 역할 | 사용 모드 | 권한 |
|---|---|---|---|---|
| [orchestrator](.claude/agents/orchestrator.md) | Read/Grep/Glob/Agent/TodoWrite/Edit/Write/AskUserQuestion | 4단계 순서·분배·상태 관리 | **참조 절차서**(비활성 — 메인이 호출하지 않음, 절차 본문 SoT 보존용) | 읽기 + Agent 호출 + state·메모리 **메타데이터만 Edit/Write** |
| [researcher](.claude/agents/researcher.md) | Read/Grep/Glob/WebSearch/WebFetch | 코드·웹·MCP 조사 | **full 전용** | 읽기 전용 + WebSearch/WebFetch/MCP |
| [planner](.claude/agents/planner.md) | Read/Grep/Glob | 설계·작업 분해·승인 카드 작성 | **full 전용** | 읽기 전용 |
| [coder](.claude/agents/coder.md) | Read/Bash/Glob/Grep/**Edit/Write/NotebookEdit** | 코드·파일 변경(처리), 자체 검증 | **full 전용** | full 모드에서 Edit/Write를 가진 유일한 서브에이전트 |
| [critic](.claude/agents/critic.md) | Read/Grep/Glob/Bash | 산출물 검증·테스트·요구사항 일치 판정 | **lite·full 공용** | 읽기 + Bash(테스트 실행) |

격리 메커니즘:
- **full 모드**: Edit/Write는 `coder` 서브에이전트에만 부여. researcher/planner/critic은 도구 자체가 없어 구조적으로 코드 편집 불가. 메인은 단계 전이용 메타데이터(`.claude/state/**`, `temp/**` 등) 화이트리스트만 쓰고, 코드 파일은 손대지 않는다.
- **lite 모드**: 메인 에이전트가 자기 Edit/Write로 직접 외과적 수정. 자연어 규약상 lite 외 상황에서는 메인이 Edit/Write를 코드에 직접 쓰지 않는다(검증·재현 등으로 필요할 때 예외). critic이 사후에 "범위 외 변경" 사유로 잡아내는 게 안전망.

자세한 규약은 [.claude/rules/coding_principles.md](.claude/rules/coding_principles.md)와 각 에이전트 정의 파일 참조.

## temp/ 폴더 규약

`temp/` 디렉토리는 워크플로우 산출물과 사용자 자료의 임시 작업 공간이다.

- `temp/plan.md`는 Phase 2 기획서 본문이다. 매 run 덮어쓴다.
- `temp/progress.md`는 Phase 3/4 진행 상황이다. run 시작 시 초기화 후 append한다.
- `temp/report.md`는 Phase 5 완료 보고 본문이다. 매 run 덮어쓰며, 영속본은 `.claude/state/history/<run_id>/run.json`의 `report_body` 필드에 흡수한다 (도구 가드가 `report.md` Write를 차단하므로 별도 파일을 만들지 않음).
- `temp/input/`은 사용자 자료실이다. 사용자가 `input/foo.md`처럼 언급하면 Claude는 `temp/input/foo.md`를 참조한다.
- `temp/output/`은 산출물 위치다. 사용자가 보고서/문서를 요청하면 Claude가 이곳에 작성한다.
- 채팅에는 마크다운 링크와 AskUserQuestion 카드만 띄운다. 본문은 항상 파일에 작성한다.
- `.gitignore`는 수정하지 않는다.

## 코딩 행동 규칙 (모든 단계 공통)

모든 코드 변경 — 특히 coder가 Edit/Write로 만드는 모든 변경 — 에는 [.claude/rules/coding_principles.md](.claude/rules/coding_principles.md)의 4원칙이 적용된다:

1. **생각하고 코딩하기** — 가정 명시, 해석 갈리면 옵션 제시, 모호하면 멈추고 질문.
2. **단순함 우선** — 요청되지 않은 기능·추상화·유연성 금지. 200줄→50줄 가능하면 다시 쓰기.
3. **외과적 변경** — 인접 코드 손대지 않기, 무관한 dead code는 언급만 (삭제 X), 변경된 모든 줄이 요청에 직접 트레이스되어야.
4. **목표 주도 실행** — 검증 가능한 성공 기준 정의, 다단계는 "단계 → 검증" 형태로 분해.

coder는 매 변경 보고 말미에 "행동 4원칙 자기 점검" 한두 줄을 적는다. critic은 위반을 결함(Defect) 사유로 명시한다.

## 호출 흐름 (DAG, 순환 금지)

### Lite 모드 (기본)

```
메인 ─Edit/Write→ (워크스페이스 변경)
  │
  └→ critic  (검증)
       ├─ Pass → 메인이 한 줄 보고 (+ recommend_full true면 /full 재실행 안내)
       └─ Fail → 메인이 critic 사유로 자동 재수정 1회 → critic 재호출
                  ├─ Pass → 종료
                  └─ Fail → AskUser(자동 재구현 한번 더 / /full로 승격 / 중단)
```

### Full 모드 (`/full` prefix)

```
# 절차서: main_full_procedure.md, 본문: orchestrator.md (비활성 참조)
메인 ─Agent→ researcher / planner / coder / critic  (차례로 호출, 단계 사이마다 AskUser·state 갱신)
              │           │         │       │
              │           │         │       └─ Pass/Fail verdict 반환
              │           │         └─ Edit/Write로 워크스페이스 변경 + Bash 자체 검증
              │           └─ 변경 명세 + 단계 분해 반환
              └─ 발견 사항 구조화 반환

검증 Fail 시: 메인 → AskUser → (재구현이면) coder → critic ...
```

- 서브에이전트끼리 직접 통신 금지. full에서는 모든 핸드오프가 메인을 거치고, lite에서는 메인이 critic만 직접 호출한다.
- full에서 메인은 main_full_procedure 절차에 따라 researcher/planner/coder/critic 4개를 차례로 호출한다. lite에서는 메인이 critic만 호출한다.

## AskUserQuestion 사용 원칙

사용자 응답이 필요한 **모든 분기**에서 AskUserQuestion으로 카드를 띄운다. 텍스트로 "Q1: ..., Q2: ..." 나열 금지. 한 호출에 최대 4개 질문. 카드를 띄우는 대표 시점:

- (full) 서칭 종료 후: 발견 사항 요약 + "기획 진입 / 추가 서칭 / 범위 변경"
- (full) 기획 종료 후: 계획 브리핑 + "승인 / 수정 / 취소" — **승인 없이는 구현 진입 금지**
- (full) 검증 1·2차 실패 후: 실패 사유 + "자동 재구현 / 방향 변경 / 중단"
- (full) 검증 3회째 실패 후: blocked 상태 + "계획 수정 / 단계 건너뛰기 / 취소"
- (lite) 자동 재수정 후에도 critic Fail: "자동 재구현 한번 더 / /full로 승격 / 중단"
- 모호한 요구사항 발견 시: 옵션 카드로 결정 받기

## 사용법

1. 작업할 디렉토리에서 세션 시작 (subagent 디스커버리는 cwd의 `.claude/agents/`만 본다).
2. 베이스를 다른 작업 디렉토리에 가져갈 때:
   - `.claude/` 전체 + `CLAUDE.md` 복사
   - Claude Code만 있으면 동작 (외부 CLI·인증 불필요)
3. **기본 = lite 모드**: 요청을 그냥 입력하면 메인이 직접 외과적으로 수정한 뒤 critic 1회 검증.
4. **full 모드**: 요청 앞에 `/full`을 붙이면 researcher→planner→coder→critic 4단계로 처리. (자세한 내용: [.claude/commands/full.md](.claude/commands/full.md))
5. 단순 조회·typo 수정 같은 1줄 작업은 메인이 critic 호출 없이 직접 처리 (workflow_4stage.md "음성 예시" 참조).
6. **슬래시 커맨드 인덱스**:
   - [`/full`](.claude/commands/full.md) — lite → full 4단계 사이클 전환
   - [`/draft`](.claude/commands/draft.md) — 모호한 요청을 라운드 대화로 다듬어 한 줄 요청으로 조립
   - [`/init`](.claude/commands/init.md) — 새 프로젝트 진입 시 의도 파악 + memory/rules 기록
   - [`/export-team`](.claude/commands/export-team.md) — 베이스 초기상태를 타임스탬프 폴더로 export
   - [`/import-team`](.claude/commands/import-team.md) — export-team 패키지를 현 베이스에 흡수

## 변경 시 원칙

- 서브에이전트는 4개(researcher/planner/coder/critic)로 고정. orchestrator.md는 참조 절차서로 보존(서브에이전트로 호출하지 않음). 새 역할이 필요해도 같은 권한의 에이전트를 이름만 바꿔 늘리지 않는다.
- 읽기 전용과 쓰기 가능 권한을 항상 분리한다. **full 모드에서 Edit/Write는 `coder`에만 부여**한다 (메인의 full 모드 메타데이터 화이트리스트 예외 + lite 모드의 메인 직접 코드 편집 예외). 다른 서브에이전트(researcher/planner/critic)에 Edit/Write를 추가하지 않는다 — IMPLEMENT 격리의 핵심.
- 재시도 카운터 임계값은 **full만 사용**(3회). lite는 자동 재수정 1회 + 사용자 카드 1회로 고정. full 임계값을 바꾸려면 `workflow_4stage.md`, 본 파일, `.claude/agents/orchestrator.md`, `.claude/rules/main_full_procedure.md` 네 곳을 함께 갱신.
- 모드 분기 로직(슬래시 prefix 매칭)은 main_full_procedure.md와 CLAUDE.md 두 곳에 명시. 둘 다 함께 갱신.
- lite·full 모두 history write 책임자는 **메인** (full에서는 main_full_procedure 절차에 따라, 동일 스키마). 변경 시 `state/README.md` "쓰기 책임" 절도 함께 갱신.
