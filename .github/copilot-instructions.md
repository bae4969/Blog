## PHP 블로그 – AI 코딩 가이드

AI 에이전트가 이 프로젝트에서 생산적으로 작업하기 위한 핵심 컨텍스트와 규칙을 제공합니다.

### 구조 개요

- MVC + PSR-4 오토로딩 (`Blog\` → `src/`)
- 단일 진입점: `public/index.php`
- 계층: `src/Core`, `src/Controllers`, `src/Models`, `src/Database`, `views/`
- 캐시: 메모리 + 파일(`cache/data`), 무효화 패턴 기반
- 보안: PDO 바인딩, CSRF 토큰, 입력 정리, HTMLPurifier

### 핵심 파일

- 라우터: `src/Core/Router.php` (`:id` 파라미터 지원, 핸들러 3번째 인자로 라우트 패턴 전달)
- 컨트롤러 베이스: `src/Controllers/BaseController.php` (`renderLayout`, `sanitizeInput`, CSRF, JSON/redirect, auth)
- 뷰: `src/Core/View.php` (`render`, `csrfToken()`, `escape()`)
- DB: `src/Database/Database.php` (`fetch`, `fetchAll`, `query`, 쿼리 로그 + 통계)
- 캐시: `src/Core/Cache.php` (`get/set/delete/deletePattern/clear`, `key()`, TTL은 `config/cache.php`)
- HTML 정제: `src/Core/HtmlSanitizer.php`, `src/Models/Post.php::create()` 참고

### 라우팅 규칙

- `public/index.php`에서 `$router->get()`/`post()`로 등록
- 경로 파라미터: `:id` 스타일, 추출 시 3번째 인자에 라우트 템플릿 전달
  - 예: `$router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);`
- 레거시 엔드포인트 유지: `/login.php`, `/reader.php`, `/writer.php`

### 컨트롤러 규칙

- `BaseController` 상속, `renderLayout('main', 'home/index', $data)` 사용
- POST 요청: CSRF 검증 필수 (`validateCsrfToken()`), 뷰에 `csrfToken` 전달
- 입력 정리: `sanitizeInput()`, 필수 필드는 `validateRequired($data, $fields)`
- 인증: `requireLogin()`, `requireWritePermission()`

### 모델 + 캐시 패턴

- DB는 `Database::getInstance()`로 획득
- 캐시 키: `Cache::key('prefix', ...)`
- 읽기 위주 쿼리는 캐시, 동적 검색은 캐시 제외
- 데이터 변경 시 관련 패턴 무효화:
  - 게시글: `deletePattern('posts_meta')`, `deletePattern('post_detail')`, `deletePattern('post_count')`
- TTL은 `config/cache.php`의 `cache_ttl` 참고

### HTML 보안

- 사용자 콘텐츠: HTMLPurifier로 정제 (`Post::create()` 참고)
- 일반 텍스트: `View::escape()` 사용

### DB 접근 & 성능

- 모든 쿼리는 `Database`를 통해 (Prepared Statement 강제)
- 느린 쿼리 임계값 100ms, 로그 기록
- 성능 API: `PerformanceController`, `CacheController` (라우트 등록 필요)

### 개발 환경

- PHP 7.4+, `composer install`
- 프론트엔드: `npm install` (선택, Quill은 `public/vendor/quill/` 로컬 사용)
- 개발 서버: `php -S localhost:8080 -t public`
- 테스트: `composer test`, `composer test-coverage` (`tests/` 필요)
- DB 설정: `config/database.php`
- 캐시 디렉토리: `cache/data` (생성 및 쓰기 권한 필요)

### 페이지 추가 예시

1. 컨트롤러: `src/Controllers/NewController.php` (`BaseController` 상속, `renderLayout` 호출)
2. 라우트: `public/index.php`에 `$router->get('/new', [NewController::class, 'index']);`
3. 뷰: `views/path/to/view.php` (POST 시 `<?= $view->csrfToken(); ?>` 포함)

### 주의사항

- 카테고리 권한: `>=` 비교 (낮은 `user_level`이 높은 권한)
- 검색 결과는 캐시 안 함, 목록/카운트는 캐시
- 읽기/방문자 카운터는 세션 키 기반 (세션 삭제 시 영향)
- 데이터 변경 시 관련 캐시 패턴 무효화 필수
