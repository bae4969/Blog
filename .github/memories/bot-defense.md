# 크롤링/봇 방어

## 구현된 방어 계층
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

## IP 자동 차단 시스템
- 위치: `public/index.php` (라우팅 전 즉시 차단), `Router::track404()`, `AuthController::checkLoginFailAutoBlock()`
- 모델: `src/Models/BlockedIp.php` — DB 테이블 `blocked_ip_list`, 캐시 `blocked_ip:{ip}`
- 위험도별 차단 기간: `config ip_block.block_duration` (low / medium / high)
- 의심 URL 패턴: `config ip_block.suspicious_url_patterns` 정규식 배열
- 캐시 TTL: 남은 차단 시간과 config `cache_ttl` 중 작은 값 사용
- 관리자 UI: `/admin/ip-blocks`
- 캐시 무효화: `deletePattern('blocked_ip')`

## 새 기능 작성 시 체크리스트
- 새 공개 라우트: pagination 상한 제한 적용
- 새 API: `requireInternalRequest()` 필수 (Origin/Referer 검증 포함)
- 프론트엔드 fetch 호출 시 반드시 `headers: { 'X-Requested-With': 'XMLHttpRequest' }` 포함
- 검색/필터: 별도 rate limiting (캐시 안 되는 쿼리 주의)
- 폼 추가: CSRF + honeypot 숨김 필드 고려
- 대량 데이터 API: limit에 `min()` 상한 적용
- 새 봇 UA 발견 시: config `bot_user_agents`에 추가
- `config.example/` 동기화 필수
