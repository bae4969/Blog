-- IP 차단 관리 테이블
CREATE TABLE IF NOT EXISTS `blocked_ip_list` (
    `blocked_ip_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `ip_address` VARCHAR(45) NOT NULL COMMENT 'IPv4/IPv6 주소',
    `reason` VARCHAR(500) DEFAULT NULL COMMENT '차단 사유',
    `block_type` ENUM('auto','manual') NOT NULL DEFAULT 'manual' COMMENT '차단 유형',
    `blocked_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '차단 시각',
    `expires_at` DATETIME DEFAULT NULL COMMENT '만료 시각 (NULL=영구차단)',
    `created_by` INT DEFAULT NULL COMMENT '수동 차단 시 관리자 user_index',
    PRIMARY KEY (`blocked_ip_id`),
    UNIQUE KEY `uk_ip_address` (`ip_address`),
    KEY `idx_expires_at` (`expires_at`),
    KEY `idx_block_type` (`block_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='IP 차단 목록';
