# 보안 원칙

## 인증/인가
- 관리자 전용 컨트롤러: 생성자에서 `requireStockAdminAccess()` 호출 필수
- 권한 체크는 반드시 `exit` 포함 (Auth.php 패턴 따름)
- `user_level` 검증: `in_array($level, [0,1,2,3,4], true)` strict 모드
- 자기 자신 권한 변경 차단 로직 포함
- 비활성 데이터(`posting_state = 1`): 비관리자(level > 1)에게 목록/상세 모두에서 숨기기 필수
- 낮은 `user_level` = 높은 권한 (0: 슈퍼관리자, 1: 관리자, 2: 편집자, 3: 작성자, 4: 구독자)

## 입력 처리
- 모든 DB 쿼리: PDO Prepared Statement 필수
- 사용자 입력: `sanitizeInput()` (strip_tags + trim)
- 리치 콘텐츠: HTMLPurifier 사용
- 파라미터 수치: `(int)` 캐스팅 + 범위 검증
- `getParam()`은 GET 우선순위 → 보안 민감 값은 `$_POST` 직접 사용 고려
- 사용자 생성/수정 메서드에서 mass assignment 방지 (파라미터 명시적 나열)

## CSRF/세션
- 모든 POST 핸들러: `validateCsrfToken()` 필수
- 뷰 폼에 `<?= $view->csrfToken(); ?>` 포함
- 민감한 작업 후 `$this->session->regenerate()` 호출
- 세션: HttpOnly=true, SameSite=Lax
- 세션 바인딩: 로그인 시 IP+UA 저장 → `isLoggedIn()`에서 매 요청 검증

## 비밀번호 관리
- 신규 비밀번호 저장: `password_hash($pw, PASSWORD_ARGON2ID)` 필수
- 인증: `password_verify()` 사용 (레거시 SHA256 자동 마이그레이션 구현됨)
- 클라이언트 SHA256 해싱은 전송 계층 1차 보호로 유지

## CSP / 스크립트 보안
- 모든 `<script>` 태그에 `nonce="<?= $view->getNonce() ?>"` 필수
- 새 뷰 추가 시 인라인 스크립트에 반드시 nonce 포함
- CSP 헤더는 `View::emitCspHeader()`에서 동적 nonce 발급
- `script-src-attr 'unsafe-inline'`으로 onclick 등 이벤트 핸들러 허용 (점진적 제거 예정)

## HTML 보안
- 리치 콘텐츠 (게시글 본문): `HtmlSanitizer` (HTMLPurifier) — `Post::create()` 참고
- 일반 텍스트 출력: `$view->escape()` (htmlspecialchars)
- CSRF 토큰: `$view->csrfToken()` — 검증 성공 시 자동 재생성 (재현 공격 방지)

## HTTPS
- HTTP 접속 시 HTTPS로 301 리다이렉트 (개발환경 제외)
- 쿠키 Secure 플래그: HTTPS 감지 시 자동 설정

## 감사 로깅
- 데이터 상태 변경 메서드(enable, disable, delete 등)에 `auditPostAction()` / `auditAdminAction()` 필수
- `Logger::info()`만으로는 감사 추적 불충분 — 반드시 audit 전용 메서드 사용
- 성공/실패 모두 기록 (실패 시 status='error' 파라미터)

## 개선 권장사항 (미수정)
1. AJAX GET API에 CSRF 미적용 (현재 읽기전용이라 낮은 위험)
2. CSP `script-src-attr 'unsafe-inline'` → 인라인 이벤트 핸들러를 addEventListener로 점진적 전환 필요
3. HSTS preload 추가 고려
