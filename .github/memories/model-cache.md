# 모델 & 캐시 패턴

## DB 접근
- `Database::getInstance()` 싱글턴
- 모든 쿼리는 `Database` 클래스 경유 (Prepared Statement 강제)
- 느린 쿼리 임계값 100ms, 자동 로그 기록
- 주식 테이블명 동적 해석: `information_schema.TABLES` 조회 후 정규식 검증 (`/^[A-Za-z0-9_]+$/`)

## 캐시 패턴
- 캐시 키: `Cache::key('prefix', $arg1, $arg2, ...)`
- 읽기 위주 → 캐시, 동적 검색 → 캐시 제외
- TTL 설정: `config/cache.php`의 `cache_ttl` 섹션 참고

## 데이터 변경 시 캐시 무효화 (필수)
- 게시글: `deletePattern('posts_meta')`, `deletePattern('post_detail')`, `deletePattern('post_count')`
- 카테고리: `deletePattern('categories_')`
- 사용자: `deletePattern('user')`
- IP 차단: `deletePattern('blocked_ip')`
- 백테스트 포트폴리오: `deletePattern('backtest_top')`

## 주식/시장 기능
- 3개 시장: KR (한국), US (미국), COIN (암호화폐)
- 기본 시장 자동 선택: 평일 08–18시 KST → KR, 그 외 → US
- 캔들/체결 데이터: `candle`/`tick` 스키마 테이블, 접두사 `s` (주식) / `c` (코인)
- 코인 판별: `Bithumb.coin_info` 테이블 캐시 (30분)
- API: `/stocks/api/candle`, `/stocks/api/executions`, `/stocks/api/search`
