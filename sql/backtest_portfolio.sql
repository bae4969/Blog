-- 백테스트 포트폴리오 랭킹 테이블
-- 참조: app/ui/backtest.py
CREATE TABLE IF NOT EXISTS `backtest_portfolio` (
    `portfolio_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `portfolio_name` VARCHAR(100) NOT NULL,
    -- ⚠️ 소유권은 **계정**이다(2026-08-19). 그전에는 `ip_address` 로 갈랐는데 앞단(NPM)이
    --    진짜 클라이언트 IP 를 안 넘겨 외부 요청이 전부 게이트웨이 하나로 보였다 —
    --    즉 모두가 같은 주인이라 누구나 남의 것을 고칠 수 있었다.
    --    NULL = 비로그인이 돌린 것. 주인이 없으므로 아무도 못 고치고 공개로 고정된다.
    `user_index` INT(11) UNSIGNED NULL COMMENT '소유자. NULL 이면 비로그인',
    -- 백테스트는 **돌리기만 해도 저장**된다. 로그인 사용자의 것을 비공개로 두지 않으면
    -- 투자 조합이 본인도 모르게 랭킹(/stocks 사이드바)에 뜬다.
    `is_public` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '0:비공개 1:공개(랭킹 노출)',
    -- ⚠️ 이제 소유권 판정에 쓰지 않는다(위 user_index 참조). 옛 데이터로만 남아 있다.
    `ip_address` VARCHAR(45) NOT NULL,
    `config_hash` CHAR(32) NOT NULL COMMENT 'MD5(정렬된 종목코드+전략) — 동일 IP+조합 중복 방지',
    `config_json` JSON NOT NULL COMMENT '전체 백테스트 설정',
    `display_score` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '사용자 설정 기준 점수 (0-100)',
    `display_grade` VARCHAR(2) NOT NULL DEFAULT 'F',
    `ranking_score` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'TWR 정규화 점수 (0-100, 랭킹용)',
    `ranking_grade` VARCHAR(2) NOT NULL DEFAULT 'F',
    `metrics_json` JSON NOT NULL COMMENT '주요 지표 (cagr, mdd, sharpe, sortino, totalReturn, avgAnnual)',
    `stock_summary` VARCHAR(200) NOT NULL COMMENT '종목 요약 (예: "삼성전자 40% + AAPL 30%")',
    `strategy` VARCHAR(20) NOT NULL DEFAULT 'buyhold',
    `period_start` DATE NOT NULL,
    `period_end` DATE NOT NULL,
    `initial_capital` BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `monthly_dca` BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_public_rank` (`is_public`, `ranking_score`),
    PRIMARY KEY (`portfolio_id`),
    UNIQUE INDEX `uq_ip_config` (`ip_address`, `config_hash`),
    INDEX `idx_ranking_score` (`ranking_score` DESC),
    INDEX `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
