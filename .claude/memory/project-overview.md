# PHP 블로그 프로젝트 개요

PHP 8.2 MVC 모놀리스. 단일 진입점 `public/index.php`가 라우트 등록·디스패치를 모두 담당. PSR-4 오토로더는 `Blog\` → `src/` 한 줄만 사용.

## 자주 쓰는 명령

```bash
composer install                # PHP 의존성 (vendor/는 gitignore)
npm install                     # 프론트 자산 (Quill 등)

cp -r config.example/* config/  # 최초 1회: config/는 gitignore
mkdir -p cache/data && chmod 755 cache cache/data

php -S localhost:80 -t public   # 로컬 서버 (DocumentRoot = public/)

composer test                   # PHPUnit 11
composer test-coverage          # tests/ → coverage/ (HTML)
./vendor/bin/phpunit --filter <TestName>

docker build -t php-blog:latest .
docker build --build-arg APP_ENV=development -t php-blog:dev .
```

`APP_ENV=development` 환경변수가 `public/index.php:19`와 `public/index.php:28`에서 에러 표시·HTTPS 강제 우회를 분기한다.

## 단일 진입점 + 사전 라우트 가드 체인

`public/index.php`는 라우트 dispatch 전에 다음을 순서대로 수행한다 (각 단계가 즉시 종료 가능):

1. **HTTPS 리다이렉트** — `APP_ENV != development` && (`HTTPS` off || `X-Forwarded-Proto != https`) → 301
2. **클라이언트 IP 추출** — `trusted_proxies`에 등록된 source만 `X-Forwarded-For` 신뢰
3. **IP 차단 체크** — `BlockedIp` 모델: whitelist 우선, 그다음 영구·임시 차단 조회
4. **자동 차단 트리거** — 의심 URL 패턴·봇 UA 패턴·분당 요청 수 초과 → 즉시 차단
5. **세션 시작 + 1회 접속 로깅** — `Logger` `access` 채널
6. **Router::dispatch** — 라우트 핸들러 실행

라우터(`src/Core/Router.php`)는 linear scan + `:id` 파라미터 매칭. 미스 시 `Router::track404`가 IP별 404 카운터를 증가시켜 4번 단계와 연동. **새 라우트는 항상 `public/index.php`에 등록** (자동 디스커버리 없음).

## MVC 계층 규약

| 계층 | 위치 | 역할 |
|---|---|---|
| Controllers | `src/Controllers/` | `BaseController` 상속 — 생성자에서 Auth/Session/View 주입. CSRF 검증, JSON/Redirect/Render 헬퍼 제공 |
| Core 인프라 | `src/Core/` | Router, Auth, Session, Cache(싱글턴), View, Logger, HtmlSanitizer(HTMLPurifier 래퍼), `*Config` (외부 AI/YouTube 키) |
| Models | `src/Models/` | DB 접근 + **모델 내부에서 Cache 직접 호출** (별도 Repository 계층 없음) |
| Database | `src/Database/Database.php` | PDO 싱글턴. 모든 쿼리는 prepared statement 강제 |
| Services | `src/Services/` | 외부 API 통합 (YouTube, Gemini, OpenAI, Backtest) — 컨트롤러가 직접 호출 |
| Views | `views/` | 도메인별 폴더(`blog/`, `admin/`, `stock/`, `func/`, `home/`). 공통 partial은 `home/` |

## 캐시 — 2계층 싱글턴

`src/Core/Cache.php`: 메모리(요청 단위) + 파일(영속) 2계층. `Cache::getInstance()` 싱글턴. TTL은 `config/cache.php`의 키별 설정. 키 생성은 `Cache::key($prefix, ...$parts)` 헬퍼 사용. 모델 변경 시 `Cache::deletePattern()`으로 관련 키 모두 무효화 — 단일 키 삭제만 하면 stale 위험.

## 권한 모델 (역방향 주의)

**`user_list.user_level` 값이 낮을수록 권한이 높다.** 0=슈퍼관리자, 4=기본 구독자. `Auth` 가드는 항상 `<=` 비교. 신규 가드 추가 시 부등호 방향 헷갈리지 말 것.

| 레벨 | 역할 |
|---|---|
| 0 | 슈퍼관리자 |
| 1 | 관리자 |
| 2 | 편집자 |
| 3 | 작성자 |
| 4 | 구독자 (미로그인 기본값) |

## 보안 — 어디서 처리되는지

| 보호 | 위치 |
|---|---|
| CSRF 토큰 | `BaseController::validateCsrfToken` — 모든 POST에서 자동 검증, 검증 후 재생성 |
| CSP nonce | `View` — 요청마다 새 nonce 생성, 인라인 `<script>`에 주입 |
| XSS | 리치 콘텐츠 = HTMLPurifier (`HtmlSanitizer`), 일반 출력 = `htmlspecialchars` |
| 비밀번호 | Argon2ID (`password_hash`/`verify`), 레거시 SHA256 로그인 성공 시 자동 마이그레이션 |
| 세션 | HttpOnly + SameSite=Lax + Secure, IP+UA 바인딩 (`Session`) |
| IP 자동 차단 | `public/index.php` (사전) + 컨트롤러 단위 트리거 (404·로그인 실패) |
| API 보호 | `X-Requested-With` 헤더 + Origin/Referer 이중 검증 (`/stocks/api/*` 등) |

새 폼/엔드포인트 추가 시: POST → CSRF 검증 통과 보장, 리치 텍스트 입력 → `HtmlSanitizer::purify`, 사용자 입력 SQL → PDO bind만 사용.

## DB 스키마

`sql/`의 `*.sql` 파일이 각 테이블 정의. 마이그레이션 도구 없음, 수동 적용. 컬럼 추가 시 해당 모델 SELECT 컬럼 목록도 함께 갱신.

## 설정 파일 누락 시

`config/`는 gitignore. `config.example/`에 없는 새 키를 `config/`에 추가했다면 반드시 `config.example/`에도 sentinel 값으로 추가 (다른 환경에서 silent 실패).
