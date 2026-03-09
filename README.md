# PHP 블로그 애플리케이션

기존 PHP 블로그를 MVC 구조로 정리하고, 캐시/성능 모니터링 기반을 추가한 프로젝트입니다.

## 핵심 요약

- MVC + PSR-4 오토로딩 (`Blog\` -> `src/`)
- 단일 진입점: `public/index.php`
- 보안 기본기: PDO Prepared Statement, CSRF 토큰, 입력값 정리
- 캐시: 메모리 + 파일(`cache/data`) 다층 캐시
- 확장 기능: 주식 목록/상세/차트 API

## 현재 라우트 (실제 코드 기준)

### 블로그

- `GET /` -> `/blog`로 리다이렉트
- `GET /index.php` -> `/blog`로 리다이렉트
- `GET /blog` : 메인 목록
- `GET /blog/search` : 검색(JSON)
- `GET /search` : 검색(JSON, 호환 경로)

### 인증

- `GET /login.php`
- `POST /login.php`
- `GET /logout.php`
- `GET /get/login_verify`

### 게시글

- `GET /reader.php?posting_index={id}` : 상세
- `GET /writer.php` : 작성 폼
- `POST /writer.php` : 작성
- `GET /post/edit/{id}` : 수정 폼
- `POST /post/update/{id}` : 수정
- `POST /post/enable/{id}` : 활성화
- `POST /post/disable/{id}` : 비활성화

### 주식

- `GET /stocks`
- `GET /stocks/view?code={stockCode}`
- `GET /stocks/api/candle`
- `GET /stocks/api/executions`
- `GET /stocks/api/search`

## 디렉토리 구조

```text
blog/
├── config/
│   ├── cache.php
│   ├── config.php
│   ├── database.php
│   └── database_example.php
├── public/
│   ├── index.php
│   ├── entrance.php
│   ├── css/
│   ├── js/
│   ├── api/
│   ├── res/
│   └── vendor/
├── src/
│   ├── Controllers/
│   ├── Core/
│   ├── Database/
│   └── Models/
├── views/
│   ├── auth/
│   ├── home/
│   ├── layouts/
│   ├── posts/
│   ├── stocks/
│   └── market/
├── cache/
│   ├── data/
│   └── htmlpurifier/
├── composer.json
├── package.json
└── README.md
```

## 설치 및 실행

### 1) 백엔드 의존성

```bash
composer install
```

### 2) 프론트엔드 의존성 (선택)

```bash
npm install
```

참고:
- 에디터는 로컬 파일(`public/vendor/quill`)을 사용 중입니다.
- `package.json`에는 `quill`, `webpack`, `webpack-cli`가 정의되어 있습니다.

### 3) DB 설정

- `config/database.php`를 환경에 맞게 수정
- 샘플은 `config/database_example.php` 참고

### 4) 캐시 디렉토리 권한

```bash
mkdir -p cache/data
chmod 755 cache
chmod 755 cache/data
```

### 5) 개발 서버 실행

```bash
php -S localhost:8080 -t public
```

브라우저에서:
- `http://localhost:8080/` 또는
- `http://localhost:8080/blog`

## 캐시 시스템

구현 위치:
- `src/Core/Cache.php`
- `config/cache.php`

특징:
- 메모리 캐시 + 파일 캐시 동시 사용
- TTL 기반 만료
- 패턴 삭제(`deletePattern`) 지원
- 키 헬퍼(`Cache::key`) 지원

주요 TTL(기본 설정):
- `user`: 1800s
- `user_can_write`: 600s
- `user_posting_limit`: 300s
- `visitor_count`: 3600s
- `categories_read/write`: 3600s
- `posts_meta`: 600s
- `post_detail`: 1800s
- `post_count`: 600s

## 성능 모니터링

구현 위치:
- `src/Database/Database.php` (쿼리 로그/통계)
- `src/Controllers/PerformanceController.php`
- `src/Controllers/CacheController.php`

주의:
- 위 두 컨트롤러용 라우트는 현재 `public/index.php`에 등록되어 있지 않습니다.
- 엔드포인트를 노출하려면 라우트를 직접 추가해야 합니다.

예시(추가 시):

```php
$router->get('/cache/stats', [CacheController::class, 'stats']);
$router->post('/cache/clear', [CacheController::class, 'clear']);
$router->post('/cache/clear-pattern', [CacheController::class, 'clearPattern']);
$router->post('/cache/warmup', [CacheController::class, 'warmup']);

$router->get('/performance/query-stats', [PerformanceController::class, 'queryStats']);
$router->get('/performance/slow-queries', [PerformanceController::class, 'slowQueries']);
$router->get('/performance/duplicate-queries', [PerformanceController::class, 'duplicateQueries']);
$router->get('/performance/system-info', [PerformanceController::class, 'systemInfo']);
$router->get('/performance/recommendations', [PerformanceController::class, 'recommendations']);
```

## 보안 포인트

- SQL 인젝션 방지: PDO + 바인딩
- CSRF 검증: POST 요청 토큰 확인
- 입력값 정리: `sanitizeInput()` + 모델 단 HTML 정제
- 본문 정제: HTMLPurifier 사용 (`src/Models/Post.php`)

## 테스트

`composer.json`에는 테스트 스크립트가 정의되어 있습니다:

```bash
composer test
composer test-coverage
```

현재 워크스페이스에는 `tests/` 디렉토리가 없어, 테스트를 실행하려면 테스트 코드 추가가 필요합니다.

## 빠른 개발 체크리스트

- 라우트 추가 시 `public/index.php`에 등록
- POST 폼에는 CSRF 토큰 포함
- 데이터 변경 로직에는 연관 캐시 무효화 추가
- 사용자 레벨 권한 비교(`>=`) 규칙 유지

## 라이선스

MIT
