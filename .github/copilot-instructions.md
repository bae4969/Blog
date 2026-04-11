## PHP 블로그 — AI 코딩 가이드

AI 에이전트가 이 프로젝트에서 즉시 생산적으로 작업하기 위한 핵심 컨텍스트입니다.

> **메모리 관리 규칙**: 프로젝트 관련 지식(코딩 규칙, 검증 결과, 학습한 패턴 등)은 `.github/memories/`에 주제별 md 파일로 분리 관리한다. `index.md`를 해시테이블로 유지하여 파일 목록과 설명을 관리한다. `.github/copilot-instructions.md`는 아키텍처·빌드 등 최소 컨텍스트만 유지한다.

### 아키텍처

- **MVC + PSR-4** 오토로딩 (`Blog\` → `src/`)
- **단일 진입점**: `public/index.php` — 모든 라우트 등록 및 디스패치
- **계층**: `src/Core/` (인프라), `src/Controllers/`, `src/Models/`, `src/Database/`, `views/`
- **캐시**: 메모리 + 파일(`cache/data`), 패턴 기반 무효화
- **보안**: PDO Prepared Statement, CSRF 토큰, 입력 정리, HTMLPurifier, IP 자동 차단

### 주의사항

- `config/` 디렉토리는 `.gitignore` — `config.example/`을 템플릿으로 사용
- 검색 결과는 캐시하지 않음 (동적 쿼리)

### 상세 규칙 → `.github/memories/`

코딩 시 아래 파일들을 참고:

| 파일 | 내용 |
|------|------|
| `security.md` | 보안 원칙 — 인증/인가, 입력 처리, CSRF, 비밀번호, CSP, 감사 로깅 |
| `bot-defense.md` | 크롤링/봇 방어 — 10개 방어 계층, IP 차단, 새 기능 체크리스트 |
| `controller-rules.md` | 컨트롤러 & 라우팅 — 페이지 추가 체크리스트 |
| `view-layer.md` | 뷰 레이어 — 레이아웃, partial, CSS 규칙 |
| `model-cache.md` | 모델 & 캐시 — DB 접근, 캐시 무효화 패턴, 주식/시장 기능 |
| `ui-rules.md` | UI 규칙 — 이모지 금지, 툴팁 패턴 |
| `backtest-reference.md` | 백테스트 기능 — 아키텍처, 점수 계산, DB 스키마 |
| `stock-subscription-criteria.md` | 주식 구독 추천 기준 |
