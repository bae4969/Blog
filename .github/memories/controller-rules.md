# 컨트롤러 & 라우팅 규칙

## 라우팅
- `public/index.php`에서 `$router->get()` / `$router->post()`로 등록
- 경로 파라미터: `:id` 스타일, 핸들러 배열 3번째 요소에 라우트 템플릿 전달
  ```php
  $router->get('/post/edit/:id', [PostController::class, 'editForm', '/post/edit/:id']);
  ```
- 레거시 엔드포인트 유지: `/login.php`, `/reader.php`, `/writer.php`
- 새 라우트 추가 시 반드시 `public/index.php`에 등록

## 컨트롤러
- 반드시 `BaseController` 상속
- 뷰 출력: `renderLayout('blog', 'home/index', $data)` — 레이아웃은 `blog`, `auth`, `stock`, `admin`, `home`
- POST 요청: `validateCsrfToken()` 필수, 뷰에 `csrfToken` 전달
- 입력 정리: `sanitizeInput()` (strip_tags + trim), 필수 필드 검증은 `validateRequired($data, $fields)`
- JSON 응답: `json($data)` 또는 `jsonResponse($data, $statusCode)`
- 리다이렉트: `redirect($url)` — 오픈 리다이렉트 방지 내장
- 인증 메서드:
  - `$this->auth->requireLogin()` — 미로그인 시 `/login.php`로 리다이렉트
  - `$this->auth->requireWritePermission()` — 글쓰기 권한 확인
  - `$this->auth->requireStockAdminAccess()` — 관리자(level ≤ 1) 전용
- 감사 로깅: `auditPostAction()`, `auditAdminAction()` 사용

## 페이지 추가 체크리스트
1. 컨트롤러: `src/Controllers/XxxController.php` — `BaseController` 상속, `renderLayout()` 호출
2. 라우트: `public/index.php`에 `$router->get('/xxx', [XxxController::class, 'method'])` 등록
3. 뷰: `views/xxx/method.php` — POST 폼에 `<?= $view->csrfToken(); ?>` 포함
4. 캐시: 데이터 조회 시 캐시 적용 여부 결정, 변경 시 패턴 무효화 구현
