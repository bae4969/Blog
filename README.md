# PHP 블로그 애플리케이션

MVC 구조 기반의 PHP 블로그 + 주식/암호화폐 대시보드 애플리케이션입니다.

## 주요 기능

- **블로그**: 게시글 CRUD, 카테고리 기반 분류, 권한별 접근 제어, Quill 리치 에디터
- **주식/시장**: KR·US·COIN 3개 시장 지원, 캔들 차트, 체결 내역, 종목 검색
- **관리자**: 사용자/카테고리/캐시/주식구독/WOL/IP 차단 관리, 감사 로그
- **보안**: PDO Prepared Statement, CSRF 토큰, HTMLPurifier, 로그인 레이트 리미팅, IP 자동 차단
- **캐시**: 메모리 + 파일 2계층 캐시, 패턴 기반 무효화

## 아키텍처

```
MVC + PSR-4 오토로딩 (Blog\ → src/)
단일 진입점: public/index.php
```

### 디렉토리 구조

```text
├── config/                # 런타임 설정 (.gitignore 대상)
├── config.example/        # 설정 템플릿
├── public/                # 웹 루트 (DocumentRoot)
│   ├── index.php          # 단일 진입점 — 라우트 등록 & 디스패치
│   ├── css/               # 스타일시트 (main, stocks, admin)
│   ├── js/                # 클라이언트 스크립트
│   └── vendor/            # 프론트엔드 라이브러리 (Quill, Chart.js)
├── src/
│   ├── Controllers/       # BaseController 상속, 뷰 렌더링 & 비즈니스 로직
│   ├── Core/              # 인프라 (Router, Auth, Session, Cache, View, Logger)
│   ├── Database/          # PDO 싱글턴 래퍼, 쿼리 로깅
│   └── Models/            # DB 접근 + 캐시 계층 (Post, User, Category, Stock, WolDevice, BlockedIp)
├── views/
│   ├── layouts/           # main.php (공용), auth.php (로그인)
│   ├── admin/             # 관리자 페이지
│   ├── home/              # 블로그 메인
│   ├── posts/             # 게시글 상세/에디터
│   └── stocks/            # 주식 목록/상세
├── cache/                 # 파일 캐시 (data/) + HTMLPurifier 캐시
├── composer.json          # PHP 의존성 (ezyang/htmlpurifier, phpunit)
├── package.json           # 프론트엔드 (quill, webpack)
└── Dockerfile             # PHP 8.2-Apache 컨테이너
```

## 설치 및 실행

### 로컬 개발

```bash
# 1. 의존성 설치
composer install
npm install                                # 선택 — Quill은 public/vendor/quill/ 로컬 사용

# 2. 설정 파일 복사 후 편집
cp config.example/* config/
# config/database.php — DB 호스트/인증 정보 설정
# config/config.php   — 앱 이름, URL, 타임존 등
# config/cache.php    — TTL 및 캐시 디렉토리

# 3. 캐시 디렉토리 권한
mkdir -p cache/data
chmod 755 cache cache/data

# 4. 개발 서버
php -S localhost:8080 -t public
```

브라우저: `http://localhost:8080/blog`

### Docker

```bash
# 프로덕션
docker build -t php-blog:latest .
```

- PHP 8.2-Apache, DocumentRoot: `/var/www/html/public`
- 확장: pdo_mysql, mbstring, gd, bcmath, sockets, opcache
- 헬스체크: `curl http://localhost/` (30초 간격)

### 테스트

```bash
composer test              # PHPUnit 실행
composer test-coverage     # HTML 커버리지 리포트
```

> `tests/` 디렉토리 미생성 상태 — PHPUnit 설정은 `composer.json`에 준비됨

## 라우트 맵

### 블로그

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/` | → `/blog` 리다이렉트 |
| GET | `/blog` | HomeController::index |
| GET | `/blog/search` | HomeController::search (JSON) |
| GET | `/search` | HomeController::search (호환) |

### 인증

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET/POST | `/login.php` | AuthController::loginForm / login |
| GET/POST | `/logout.php` | AuthController::logoutRedirect / logout |
| GET | `/get/login_verify` | AuthController::verify |

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

### 관리자 (`/admin/*` — level ≤ 1)

| 메서드 | 경로 | 기능 |
|--------|------|------|
| GET | `/admin` | 관리자 메인 |
| GET/POST | `/admin/users`, `/admin/users/create`, `/admin/users/update` | 사용자 관리 |
| GET/POST | `/admin/categories`, `/admin/categories/create|update|delete|reorder` | 카테고리 관리 |
| GET/POST | `/admin/cache`, `/admin/cache/clear|clear-expired|clear-pattern|warmup` | 캐시 관리 |
| GET/POST | `/admin/stocks`, `/admin/stocks/subscriptions` | 주식 구독 관리 |
| GET/POST | `/admin/wol`, `/admin/wol/execute|create|update|delete` | WOL 장치 관리 |
| GET/POST | `/admin/ip-blocks`, `/admin/ip-blocks/add|remove|clean` | IP 차단 관리 |

### 주식

| 메서드 | 경로 | 핸들러 |
|--------|------|--------|
| GET | `/stocks` | StockController::index |
| GET | `/stocks/view?code={stockCode}` | StockController::show |
| GET | `/stocks/api/candle` | StockController::apiCandleData (JSON) |
| GET | `/stocks/api/executions` | StockController::apiRecentExecutions (JSON) |
| GET | `/stocks/api/search` | StockController::apiSearch (JSON) |

## 설정

### config/database.php

```php
return [
    'host' => 'localhost',
    'dbname' => 'dbname',
    'username' => 'username',
    'password' => 'password',
    'charset' => 'utf8mb4',
];
```

### config/config.php 주요 항목

| 키 | 기본값 | 설명 |
|----|--------|------|
| `app_name` | Developer Blog | 사이트 이름 |
| `timezone` | Asia/Seoul | 타임존 |
| `session_lifetime` | 3600 | 세션 만료 (초) |
| `posts_per_page` | 10 | 페이지당 게시글 수 |
| `max_file_size` | 5MB | 업로드 최대 크기 |
| `login_rate_limit` | 설정 파일 참고 | 로그인 시도 제한 |
| `ip_block` | 설정 파일 참고 | IP 자동 차단 (위험도별 차단 기간, 의심 URL 패턴) |

### config/cache.php 주요 TTL

| 캐시 키 | TTL | 비고 |
|---------|-----|------|
| `posts_meta` | 600s | 게시글 목록 |
| `post_detail` | 1800s | 게시글 상세 |
| `post_count` | 600s | 게시글 수 |
| `categories_read/write` | 3600s | 카테고리 목록 |
| `user` | 1800s | 사용자 정보 |
| `visitor_count` | 3600s | 방문자 수 |
| `coin_code_set` | 1800s | 코인 코드 |

## 권한 체계

**낮은 `user_level` = 높은 권한**

| 레벨 | 역할 | 주요 권한 |
|------|------|----------|
| 0 | 슈퍼관리자 | 전체 접근 |
| 1 | 관리자 | 관리자 패널, 주식 구독 관리 |
| 2 | 편집자 | 게시글 작성/편집 |
| 3 | 작성자 | 게시글 작성 |
| 4 | 구독자 | 읽기 전용 (미로그인 기본값) |

카테고리 접근 제어: `category_read_level >= user_level` → 해당 레벨 이상이면 접근 가능

## 보안

- **SQL 인젝션 방지**: PDO Prepared Statement 강제
- **CSRF**: 모든 POST 폼에 `$view->csrfToken()`, 검증 후 자동 재생성
- **입력 정리**: `sanitizeInput()` (strip_tags + trim) + `$view->escape()` (htmlspecialchars)
- **리치 콘텐츠**: HTMLPurifier로 허용 태그만 통과
- **인증**: HttpOnly + SameSite=Lax 쿠키, 세션 활동 시간 기반 만료
- **레이트 리미팅**: 로그인 시도 IP/사용자별 제한, 타이밍 공격 완화 딜레이
- **IP 자동 차단**: 위험도 기반 자동 차단 (과다 요청, 404 반복, 로그인 실패, 의심 URL 패턴), 관리자 UI 수동 차단/해제
- **리다이렉트**: 오픈 리다이렉트 방지 (`redirect()` 메서드)
- **테이블명 검증**: 동적 테이블 조회 시 정규식 `/^[A-Za-z0-9_]+$/`

## 라이선스

MIT
