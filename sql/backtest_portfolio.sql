-- 백테스트 포트폴리오 랭킹 테이블
-- 참조: src/Models/BacktestPortfolio.php, src/Controllers/StockController.php
CREATE TABLE IF NOT EXISTS `backtest_portfolio` (
    `portfolio_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `portfolio_name` VARCHAR(100) NOT NULL,
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
    PRIMARY KEY (`portfolio_id`),
    UNIQUE INDEX `uq_ip_config` (`ip_address`, `config_hash`),
    INDEX `idx_ranking_score` (`ranking_score` DESC),
    INDEX `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
