CREATE TABLE IF NOT EXISTS `stock_split_events` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `stock_code` VARCHAR(20) NOT NULL COMMENT '종목 코드',
    `market` ENUM('KR', 'US', 'COIN') NOT NULL COMMENT '시장 구분',
    `event_date` DATE NOT NULL COMMENT '분할/병합 적용일',
    `ratio_from` INT UNSIGNED NOT NULL COMMENT '기존 주수 (예: 1)',
    `ratio_to` INT UNSIGNED NOT NULL COMMENT '변환 주수 (예: 5 → 1:5 분할)',
    `description` VARCHAR(200) DEFAULT NULL COMMENT '설명 (예: 1:5 액면분할)',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_stock_event` (`stock_code`, `market`, `event_date`),
    INDEX `idx_stock_market` (`stock_code`, `market`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='주식 액면분할/병합 이벤트';
