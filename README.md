# PHP 블로그 애플리케이션

MVC 구조 기반의 PHP 블로그 + 주식/암호화폐 대시보드 애플리케이션입니다.

## 주요 기능

- **블로그**: 게시글 CRUD, 카테고리 기반 분류, 권한별 접근 제어, Quill 리치 에디터
- **주식/시장**: KR·US·COIN 3개 시장 지원, 캔들 차트, 체결 내역, 종목 검색, 백테스트
- **인터랙트(`/func`)**: YouTube 알고리즘 분석, 분석 결과 공유 링크·반응, 분석 이력
- **관리자**: 사용자/카테고리/캐시/주식구독/주식분할/WOL/IP 차단/외부 API 키 관리, 감사 로그
- **보안**: Argon2ID 비밀번호 해싱, CSRF 토큰, CSP nonce, 세션 바인딩, IP 자동 차단, 봇 UA 차단
- **캐시**: 메모리 + 파일 + 주식 일봉 전용 gzip 3계층, 패턴 기반 무효화

## 아키텍처

```
MVC + PSR-4 오토로딩 (Blog\ → src/)
단일 진입점: public/index.php
```

### 디렉토리 구조

```text
├── config.example/        # 설정 템플릿 (config/는 .gitignore)
├── public/                # 웹 루트 (DocumentRoot)
│   ├── index.php          # 단일 진입점 — 라우트 등록 & 디스패치
│   ├── css/               # 스타일시트 (common, blog, stocks, admin, home)
│   ├── js/                # 클라이언트 스크립트
│   └── vendor/            # 프론트엔드 라이브러리 (Quill, Chart.js)
├── src/
│   ├── Controllers/       # BaseController 상속, 뷰 렌더링 & 비즈니스 로직
│   ├── Core/              # 인프라 (Router, Auth, Session, Cache, View, Logger, HtmlSanitizer, ClientIp)
│   ├── Database/          # PDO 싱글턴 래퍼, 쿼리 로깅
│   ├── Models/            # DB 접근 + 캐시 계층
│   └── Services/          # 외부 API 통합 (YouTube, Gemini, OpenAI, Backtest)
├── views/
│   ├── home/              # 공통 partials + 로그인
│   ├── blog/              # 블로그 목록/상세/에디터
│   ├── admin/             # 관리자 페이지
│   ├── func/              # 인터랙트 (YouTube 분석·이력)
│   └── stock/             # 주식 목록/상세
├── cache/                 # 파일 캐시 (data/) + 주식 일봉 gzip 캐시 (stock/) + HTMLPurifier 캐시
├── sql/                   # DB 스키마 정의 (마이그레이션 도구 없음 — 수동 적용)
├── .github/workflows/     # main 푸시 시 릴리스 + 배포 파이프라인
└── Dockerfile             # PHP 8.2-Apache 컨테이너
```

## 설치 및 실행

### 로컬 개발

```bash
composer install
cp config.example/* config/        # 설정 파일 복사 후 편집
mkdir -p cache/data && chmod 755 cache cache/data
php -S localhost:80 -t public    # 개발 서버 → http://localhost:80/blog
```

### Docker

```bash
docker build -t php-blog:latest .
```

- PHP 8.2-Apache, 확장: pdo_mysql, mysqli, mbstring, exif, bcmath, sockets, gd, opcache, xdebug
- DocumentRoot: `/var/www/html/public`
- 헬스체크: `curl http://localhost/` (30초 간격)

### 테스트

`composer test` / `composer test-coverage` 스크립트와 PHPUnit 11 의존성은 준비돼 있지만, **아직 `tests/` 디렉토리와 `phpunit.xml`이 없어 실제로 실행되는 테스트는 없습니다.** 현재 검증은 문법 검사(`php -l`)와 테스트 환경에서의 동작 확인으로 합니다.

### 배포

`main` 브랜치에 푸시(PR 머지)되면 [GitHub Actions](.github/workflows/release.yml)가 자동으로 실행됩니다.

1. **검증** — `src public config` 아래 모든 PHP 파일 `php -l` (테스트는 `tests/`가 있을 때만 실행)
2. **릴리스** — `package.json`의 `version`으로 태그를 만들고 소스 아카이브를 GitHub Release에 첨부. 같은 태그가 이미 있으면 지우고 다시 만듭니다
3. **배포** — self-hosted 러너가 서버의 배포 디렉토리에서 `git reset --hard origin/main`

배포는 **추적 파일만** 갱신합니다. `config/`는 `.gitignore` 대상이라 배포로 전달되지 않으므로, 새 설정 키가 생기면 서버의 `config/`를 직접 갱신해야 합니다. DB 스키마도 자동 반영되지 않습니다(`sql/` 수동 적용).

## 라우트 맵

### 블로그

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/`, `/index.php` | → `/blog` 리다이렉트 |
| GET | `/blog` | HomeController::index |
| GET | `/blog/search`, `/search` | HomeController::search (JSON) |

### 인터랙트

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/func` | FuncController::index |
| GET | `/func/youtube-feed` | FuncController::youtubeFeed |
| GET | `/func/analyze` | FuncController::analyze |
| POST | `/func/analyze/react` | FuncController::reactAnalysis |
| GET | `/func/history` | FuncController::history |
| GET | `/a/:id` | FuncController::analyzeShort (공유 단축 링크) |

### 인증

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET/POST | `/login.php` | AuthController::loginForm / login |
| GET/POST | `/logout.php` | AuthController::logoutRedirect / logout |
| GET | `/get/login_verify` | AuthController::verify (JSON) |

### 게시글

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/reader.php?posting_index={id}` | PostController::show |
| GET | `/writer.php` | PostController::createForm |
| POST | `/writer.php` | PostController::create |
| GET | `/post/edit/:id` | PostController::editForm |
| POST | `/post/update/:id` | PostController::update |
| POST | `/post/enable/:id` | PostController::enable |
| POST | `/post/disable/:id` | PostController::disable |
| POST | `/post/hard-delete/:id` | PostController::hardDelete |

### 관리자 (`/admin/*` — level ≤ 1)

| 메서드 | 경로 | 기능 |
|--------|------|------|
| GET | `/admin` | 관리자 메인 |
| GET | `/admin/logs` | 감사 로그 |
| GET/POST | `/admin/users`, `users/create`, `users/update` | 사용자 관리 |
| GET/POST | `/admin/categories`, `categories/create\|update\|delete\|reorder` | 카테고리 관리 |
| GET/POST | `/admin/cache`, `cache/clear\|clear-expired\|clear-pattern\|warmup\|stock-day-cleanup\|stock-day-clear` | 캐시 관리 |
| GET/POST | `/admin/stocks`, `stocks/subscriptions` | 주식 구독 관리 |
| GET/POST | `/admin/stock-splits`, `stock-splits/create\|delete` | 주식 분할/병합 이벤트 |
| GET/POST | `/admin/wol`, `wol/execute\|create\|update\|delete` | WOL 장치 관리 |
| GET/POST | `/admin/ip-blocks`, `ip-blocks/add\|remove\|clean` | IP 차단 관리 |

### 주식

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/stocks` | StockController::index |
| GET | `/stocks/view?code={code}&market={market}` | StockController::show |
| GET | `/stocks/api/candle` | StockController::apiCandleData (JSON) |
| GET | `/stocks/api/executions` | StockController::apiRecentExecutions (JSON) |
| GET | `/stocks/api/search` | StockController::apiSearch (JSON) |

## 설정

설정 파일은 `config.example/`을 `config/`에 복사하여 사용합니다.

| 파일 | 주요 항목 |
|------|----------|
| `database.php` | DB 호스트, 인증 정보, charset (utf8mb4) |
| `config.php` | 앱 이름, 세션 만료, 업로드 제한, 로그인 레이트 리미팅, IP 자동 차단 (임계값·차단 기간·의심 URL 패턴·봇 UA 패턴) |
| `cache.php` | 캐시 키별 TTL 설정 |

## 권한 체계

**낮은 `user_level` = 높은 권한**

| 레벨 | 역할 | 주요 권한 |
|------|------|----------|
| 0 | 슈퍼관리자 | 전체 접근 |
| 1 | 관리자 | 관리자 패널 |
| 2 | 편집자 | 게시글 작성/편집 |
| 3 | 작성자 | 게시글 작성 |
| 4 | 구독자 | 읽기 전용 (미로그인 기본값) |

## 보안

- **비밀번호**: 서버 측 Argon2ID 해싱 (`password_hash`/`password_verify`), 레거시 SHA256 자동 마이그레이션
- **SQL 인젝션 방지**: PDO Prepared Statement 강제
- **CSRF**: 모든 POST 폼에 일회용 토큰, 검증 후 자동 재생성
- **XSS 방지**: HTMLPurifier (리치 콘텐츠) + `htmlspecialchars` (일반 출력)
- **CSP**: 동적 nonce 기반 `Content-Security-Policy` 헤더
- **세션**: HttpOnly + SameSite=Lax + Secure 쿠키, IP+UA 바인딩, 활동 기반 만료
- **HTTPS**: HTTP → HTTPS 301 리다이렉트, HSTS 헤더
- **IP 자동 차단**: 과다 요청(분당 200회), 404 반복(분당 30회), 로그인 실패(5회), 의심 URL 패턴(18개), 봇 UA(16패턴) → 위험도별 차단(1분/1시간/7일)
- **클라이언트 IP**: 리버스 프록시 뒤에서는 `REMOTE_ADDR`이 프록시 IP로 고정되므로, `trusted_proxies`에 등록된 소스에 한해 `X-Real-IP`(우선) 또는 `X-Forwarded-For` 최우측 값으로 실제 방문자 IP를 복원 (`Core\ClientIp`). 차단·레이트 리미팅이 모두 이 값을 사용
- **API 보호**: `X-Requested-With` + Origin/Referer 이중 검증
- **봇 방어**: 검색 Rate Limiting(분당 20회), Pagination 상한 제한, Honeypot 필드, `noindex/nofollow` 메타 태그, `robots.txt` Crawl-delay
- **로그인 보호**: IP/사용자별 레이트 리미팅, 타이밍 공격 완화 딜레이

## 라이선스

MIT
