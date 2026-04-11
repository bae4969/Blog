# 백테스트 기능 레퍼런스

## 아키텍처
- **클라이언트 MVVM**: 설정 UI → collectConfig() → 서버 API
- **서버 처리**: /stocks/api/backtest POST → PHP BacktestService → 결과 JSON
- **자동 저장**: 백테스트 결과 후 backtest_portfolio 테이블에 저장
- **프리셋**: 로그인 사용자 전용, backtest_preset 테이블 (최대 20개/사용자)

## 핵심 파일
- `src/Controllers/StockController.php` — apiBacktest(), 프리셋 CRUD API 4개, Top 포트폴리오 API
- `src/Services/BacktestService.php` — 백테스트 실행 엔진
- `src/Models/BacktestPortfolio.php` — 포트폴리오 자동 저장/조회 (IP 기반)
- `src/Models/BacktestPreset.php` — 사용자 프리셋 CRUD (로그인 기반, 20개 제한)
- `public/js/backtest.js` — 프론트엔드 전체 로직
- `views/stock/backtest.php` — 뷰 템플릿

## 점수 계산
- 6개 지표: CAGR, 연간수익률, 총수익률, MDD, 샤프, 소르티노
- 가중치: CAGR 20%, MDD 20%, Sharpe 20%, Sortino 20%, 연간 10%, 총수익 10%
- 정규화 범위: CAGR -10~15%, 연간 -10~20%, 총수익 -50~200%, MDD 45~10%(역전), Sharpe -0.5~1.8, Sortino -0.5~2.0
- 등급: 90+ A+, 80+ A, 70+ B+, 60+ B, 50+ C+, 40+ C, 30+ D, F

## DB 스키마

### backtest_portfolio
- portfolio_id (PK), portfolio_name, ip_address, config_hash (MD5), config_json, display_score/grade, ranking_score/grade, metrics_json, stock_summary, strategy, period_start/end, initial_capital, monthly_dca
- UNIQUE (ip_address, config_hash)

### backtest_preset
- preset_id (PK), user_index, preset_name, config_json, stock_summary, strategy, created_at, updated_at
- UNIQUE (user_index, preset_name), 최대 20개/사용자

## 보안/제한
- 백테스트 Rate limit: IP당 분당 5회
- 동시 실행: 파일 기반 세마포어 2 슬롯
- 종목 10개, 벤치마크 5개, 기간 30년 제한
- 비중 합계 100% ± 0.5%
- 포트폴리오 이름 수정: 생성 IP만 가능
- 프리셋: 로그인 사용자만, 소유자 검증 필수

## 캐시
- backtest_top:{limit} → 5분 TTL
- 저장/수정 시 deletePattern('backtest_top')
