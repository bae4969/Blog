## PHP 블로그 — AI 코딩 가이드

AI 에이전트가 이 프로젝트에서 즉시 생산적으로 작업하기 위한 핵심 컨텍스트와 규칙입니다.

> **메모리 관리 규칙**: 프로젝트 관련 지식(보안 원칙, 코딩 규칙, 검증 결과 등)은 `/memories/`가 아닌 이 파일(`.github/copilot-instructions.md`)에 기록하여 Git으로 영구 관리한다. 컨테이너 내부 메모리 파일은 재빌드 시 소실되므로 사용하지 않는다.

### 아키텍처

- **MVC + PSR-4** 오토로딩 (`Blog\` → `src/`)
- **단일 진입점**: `public/index.php` — 모든 라우트 등록 및 디스패치
- **계층**: `src/Core/` (인프라), `src/Controllers/`, `src/Models/`, `src/Database/`, `views/`
- **캐시**: 메모리 + 파일(`cache/data`), 패턴 기반 무효화
- **보안**: PDO Prepared Statement, CSRF 토큰, 입력 정리, HTMLPurifier, IP 자동 차단

### 빌드 & 실행

```bash
composer install                           # 백엔드 의존성
npm install                                # 프론트엔드 (선택, Quill은 public/vendor/quill/ 로컬 사용)
cp config.example/* config/                # 설정 파일 복사 후 편집
php -S localhost:8080 -t public            # 개발 서버
composer test                              # PHPUnit 실행
composer test-coverage                     # 커버리지 HTML 리포트
```

- Docker: `docker build --build-arg APP_ENV=dev -t blog .` (PHP 8.2-Apache, Xdebug 포함)
- DB 설정: `config/database.php` (PDO MySQL, utf8mb4)
- 캐시 디렉토리: `cache/data` (쓰기 권한 필요)

### 라우팅 규칙

- `public/index.php`에서 `$router->get()` / `$router->post()`로 등록
- 경로 파라미터: `:id` 스타일, 핸들러 배열 3번째 요소에 라우트 템플릿 전달
  ```php
  $router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);
  ```
- 레거시 엔드포인트 유지: `/login.php`, `/reader.php`, `/writer.php`
- 새 라우트 추가 시 반드시 `public/index.php`에 등록

### 컨트롤러 규칙

- 반드시 `BaseController` 상속
- 뷰 출력: `renderLayout('blog', 'home/index', $data)` — 레이아웃은 `blog` 또는 `auth`
- POST 요청: `validateCsrfToken()` 필수, 뷰에 `csrfToken` 전달
- 입력 정리: `sanitizeInput()` (strip_tags + trim), 필수 필드 검증은 `validateRequired($data, $fields)`
- JSON 응답: `json($data)` 또는 `jsonResponse($data, $statusCode)`
- 리다이렉트: `redirect($url)` — 오픈 리다이렉트 방지 내장
- 인증 메서드:
  - `$this->auth->requireLogin()` — 미로그인 시 `/login.php`로 리다이렉트
  - `$this->auth->requireWritePermission()` — 글쓰기 권한 확인
  - `$this->auth->requireStockAdminAccess()` — 관리자(level ≤ 1) 전용
- 감사 로깅: `auditPostAction()`, `auditAdminAction()` 사용

### 인증 & 권한 (중요)

- **낮은 `user_level` = 높은 권한** (0: 슈퍼관리자, 1: 관리자, 2: 편집자, 3: 작성자, 4: 구독자)
- 미로그인 사용자 기본 레벨: 4
- 카테고리 읽기/쓰기 권한: `category_read_level >= ?` → "이 레벨 이상이면 접근 가능"
- 세션 기반 인증, HttpOnly 쿠키, SameSite=Lax
- 로그인 레이트 리미팅: `config/config.php`의 `login_rate_limit` 섹션 참고

### IP 자동 차단 시스템

- 위치: `public/index.php` (라우팅 전 즉시 차단), `Router::track404()`, `AuthController::checkLoginFailAutoBlock()`
- 모델: `src/Models/BlockedIp.php` — DB 테이블 `blocked_ip_list`, 캐시 `blocked_ip:{ip}`
- 위험도별 차단 기간: `config ip_block.block_duration` (low / medium / high)
- 의심 URL 패턴: `config ip_block.suspicious_url_patterns` 정규식 배열 — 1회 매칭으로 즉시 차단
- 캐시 TTL: 남은 차단 시간과 config `cache_ttl` 중 작은 값 사용
- 관리자 UI: `/admin/ip-blocks` — 수동 차단/해제, 만료 정리, 설정 현황 테이블
- 캐시 무효화: `deletePattern('blocked_ip')`
- **상세 설정값은 `config/config.php`의 `ip_block` 섹션 참고 (임계값, 차단 시간, 패턴 목록)**

### 모델 + 캐시 패턴

- DB: `Database::getInstance()` 싱글턴
- 캐시 키: `Cache::key('prefix', $arg1, $arg2, ...)`
- 읽기 위주 → 캐시, 동적 검색 → 캐시 제외
- **데이터 변경 시 반드시 관련 캐시 패턴 무효화:**
  - 게시글: `deletePattern('posts_meta')`, `deletePattern('post_detail')`, `deletePattern('post_count')`
  - 카테고리: `deletePattern('categories_')`
  - 사용자: `deletePattern('user')`
- TTL 설정: `config/cache.php`의 `cache_ttl` 섹션 참고

### HTML 보안

- 리치 콘텐츠 (게시글 본문): `HtmlSanitizer` (HTMLPurifier) — `Post::create()` 참고
- 일반 텍스트 출력: `$view->escape()` (htmlspecialchars)
- CSRF 토큰: `$view->csrfToken()` — 검증 성공 시 자동 재생성 (재현 공격 방지)

### DB 접근

- 모든 쿼리는 `Database` 클래스 경유 (Prepared Statement 강제)
- 느린 쿼리 임계값 100ms, 자동 로그 기록
- 주식 테이블명 동적 해석: `information_schema.TABLES` 조회 후 정규식 검증 (`/^[A-Za-z0-9_]+$/`)

### 주식/시장 기능

- 3개 시장: KR (한국), US (미국), COIN (암호화폐)
- 기본 시장 자동 선택: 평일 08–18시 KST → KR, 그 외 → US
- 캔들/체결 데이터: `candle`/`tick` 스키마 테이블, 접두사 `s` (주식) / `c` (코인)
- 코인 판별: `Bithumb.coin_info` 테이블 캐시 (30분)
- API: `/stocks/api/candle`, `/stocks/api/executions`, `/stocks/api/search`

### 뷰 레이어

#### `views/` 디렉토리 구조

```
views/
  home/              # 공통 요소 + 로그인
    layout.php         # 로그인 전용 레이아웃
    header.php         # 공통 헤더 (nav, 로그인/로그아웃, 글쓰기)
    footer.php         # 공통 푸터
    partials-head.php            # 공통 <head> (CSS 로드, cache bust)
    partials-flash-messages.php  # 공통 flash 알림 (success/error)
    partials-footer-scripts.php  # 공통 JS (blog.js, nav dropdown, additionalJs)
    login.php          # 로그인 폼 뷰
    index.php          # 홈 페이지 뷰
  blog/              # 블로그 섹션
    layout.php         # 블로그 레이아웃 (사이드바: 카테고리, 검색, 방문자)
    index.php          # 글 목록
    show.php           # 글 상세
    editor.php         # 글 작성/수정 에디터
  admin/             # 관리자 섹션
    layout.php         # 관리자 레이아웃 (사이드바: 관리 메뉴)
    users.php          # 사용자 관리
    categories.php     # 카테고리 관리
    cache.php          # 캐시 관리
    stocks.php         # 주식 구독 관리
    wol.php            # WOL 관리
    ip-blocks.php      # IP 차단 관리
  stock/             # 주식 섹션
    layout.php         # 주식 레이아웃 (사이드바 없음)
    index.php          # 주식 목록
    show.php           # 주식 상세
```

#### 규칙

- **레이아웃**: 섹션별 분리 — 각 섹션 폴더에 `layout.php` 존재
- **공통 partial**: `views/home/partials-{이름}.php` 명명 규칙 — 여러 레이아웃에서 include
- **새 partial 추가 시**: `views/home/partials-{이름}.php`로 생성
- **새 섹션 추가 시**: `views/{섹션}/layout.php` 생성 + `View::renderLayout()`에서 자동 해석 (`views/{$layout}/layout.php`)
- `renderLayout($layout, $view)` — `$layout`은 뷰 폴더명과 동일 (`'blog'`, `'admin'`, `'stock'`, `'home'`)
- 뷰 내 자동 주입 변수: `$session`, `$auth`, `$config`, `$view`
- **CSS 색상/변수**: `public/css/common.css`의 `:root`에서 일괄 정의 — 색상 추가·변경 시 반드시 이 파일에서 관리
- 섹션별 색상 오버라이드: `common.css` 내 CSS 스코프(예: `.auth-wrapper { --primary-color: ... }`)로 처리
- CSS 로드 순서: `common.css` → `blog.css` → 섹션별 CSS (`stocks.css`, `admin.css` 등)
- CSS 캐시 버스팅: `?v={filemtime}` 패턴
- 에디터: Quill (`public/vendor/quill/` 로컬 파일)

### 관리자 기능 (`/admin/*`)

- 사용자/카테고리/캐시/주식구독/WOL/IP 차단 관리
- `requireStockAdminAccess()` (level ≤ 1) 보호
- 모든 관리자 액션에 감사 로그 기록

### 페이지 추가 체크리스트

1. 컨트롤러: `src/Controllers/XxxController.php` — `BaseController` 상속, `renderLayout()` 호출
2. 라우트: `public/index.php`에 `$router->get('/xxx', [XxxController::class, 'method'])` 등록
3. 뷰: `views/xxx/method.php` — POST 폼에 `<?= $view->csrfToken(); ?>` 포함
4. 캐시: 데이터 조회 시 캐시 적용 여부 결정, 변경 시 패턴 무효화 구현

### 주의사항

- 검색 결과는 캐시하지 않음 (동적 쿼리)
- 방문자 카운터는 세션 + 주간 그룹 기반 — 세션 삭제 시 리셋됨
- `config/` 디렉토리는 `.gitignore` — `config.example/`을 템플릿으로 사용
- 테스트 디렉토리(`tests/`)는 아직 미생성 — PHPUnit 설정은 `composer.json`에 준비됨

---

### 보안 원칙 (코드 작성 시 필수)

#### 인증/인가
- 관리자 전용 컨트롤러: 생성자에서 `requireStockAdminAccess()` 호출 필수
- 권한 체크는 반드시 `exit` 포함 (Auth.php 패턴 따름)
- `user_level` 검증: `in_array($level, [0,1,2,3,4], true)` strict 모드
- 자기 자신 권한 변경 차단 로직 포함
- 비활성 데이터(`posting_state = 1`): 비관리자(level > 1)에게 목록/상세 모두에서 숨기기 필수

#### 입력 처리
- 모든 DB 쿼리: PDO Prepared Statement 필수
- 사용자 입력: `sanitizeInput()` (strip_tags + trim)
- 리치 콘텐츠: HTMLPurifier 사용
- 파라미터 수치: `(int)` 캐스팅 + 범위 검증
- `getParam()`은 GET 우선순위 → 보안 민감 값은 `$_POST` 직접 사용 고려
- 사용자 생성/수정 메서드에서 mass assignment 방지 (파라미터 명시적 나열)

#### CSRF/세션
- 모든 POST 핸들러: `validateCsrfToken()` 필수
- 뷰 폼에 `<?= $view->csrfToken(); ?>` 포함
- 민감한 작업 후 `$this->session->regenerate()` 호출
- 세션: HttpOnly=true, SameSite=Lax
- 세션 바인딩: 로그인 시 IP+UA 저장 → `isLoggedIn()`에서 매 요청 검증

#### 비밀번호 관리
- 신규 비밀번호 저장: `password_hash($pw, PASSWORD_ARGON2ID)` 필수
- 인증: `password_verify()` 사용 (레거시 SHA256 자동 마이그레이션 구현됨)
- 클라이언트 SHA256 해싱은 전송 계층 1차 보호로 유지

#### CSP / 스크립트 보안
- 모든 `<script>` 태그에 `nonce="<?= $view->getNonce() ?>"` 필수
- 새 뷰 추가 시 인라인 스크립트에 반드시 nonce 포함
- CSP 헤더는 `View::emitCspHeader()`에서 동적 nonce 발급
- `script-src-attr 'unsafe-inline'`으로 onclick 등 이벤트 핸들러 허용 (점진적 제거 예정)

#### HTTPS
- HTTP 접속 시 HTTPS로 301 리다이렉트 (개발환경 제외)
- 쿠키 Secure 플래그: HTTPS 감지 시 자동 설정

#### 감사 로깅 (Audit Logging)
- 데이터 상태 변경 메서드(enable, disable, delete 등)에 `auditPostAction()` / `auditAdminAction()` 필수
- `Logger::info()`만으로는 감사 추적 불충분 — 반드시 audit 전용 메서드 사용
- 성공/실패 모두 기록 (실패 시 status='error' 파라미터)

### 크롤링/봇 방어

#### 구현된 방어 계층
1. **Rate Limit**: 분당 60회 초과 시 IP 자동 차단 (config `request_threshold`)
2. **봇 UA 차단**: curl, wget, Python, Scrapy, Selenium 등 16패턴 → 7일 차단 (config `bot_user_agents`)
3. **Meta robots**: `noindex, nofollow` (`partials-head.php`)
4. **Pagination 보호**: 범위 초과 시 마지막 페이지로 정규화
5. **API Origin 검증**: `X-Requested-With` + Origin/Referer 이중 검증 (`BaseController::requireInternalRequest()`)
6. **검색 Rate Limit**: IP당 분당 20회, 초과 시 429 (`HomeController::search()`)
7. **Honeypot**: 로그인 폼 숨김 필드 `website_url` (`AuthController`)
8. **robots.txt**: `Crawl-delay: 10`, 민감 경로 Disallow
9. **의심 URL 패턴 18개**: `.env`, `.git`, `wp-admin` 등 1회 접근 시 즉시 7일 차단
10. **404 폭주**: 분당 5회 초과 시 자동 차단

#### 새 기능 작성 시 봇 방어 체크리스트
- 새 공개 라우트: pagination 상한 제한 적용
- 새 API: `requireInternalRequest()` 필수 (Origin/Referer 검증 포함)
- 프론트엔드 fetch 호출 시 반드시 `headers: { 'X-Requested-With': 'XMLHttpRequest' }` 포함
- 검색/필터: 별도 rate limiting (캐시 안 되는 쿼리 주의)
- 폼 추가: CSRF + honeypot 숨김 필드 고려
- 대량 데이터 API: limit에 `min()` 상한 적용
- 새 봇 UA 발견 시: config `bot_user_agents`에 추가
- `config.example/` 동기화 필수

### 개선 권장사항 (미수정)

1. AJAX GET API에 CSRF 미적용 (현재 읽기전용이라 낮은 위험)
2. CSP `script-src-attr 'unsafe-inline'` → 인라인 이벤트 핸들러를 addEventListener로 점진적 전환 필요
3. HSTS preload 추가 고려
