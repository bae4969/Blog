-- /func/analyze 분석 결과 영구 저장 테이블
-- 같은 ids 조합은 1개 record로 dedupe (ids_hash UNIQUE) → 새로고침 시 외부 API 재호출 회피
CREATE TABLE IF NOT EXISTS `func_analysis_list` (
    `analysis_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `share_token` CHAR(16) NULL COMMENT '공유 URL 토큰 (16자 hex, IDOR 방지)',
    `ids_hash` CHAR(40) NOT NULL COMMENT '정렬된 video ids의 sha1',
    `ids_csv` TEXT NOT NULL COMMENT '정렬된 video ids 콤마 구분',
    `video_count` INT UNSIGNED NOT NULL DEFAULT 0,
    `provider` VARCHAR(20) NOT NULL DEFAULT 'none' COMMENT 'none/gemini/openai',
    `payload` LONGTEXT NOT NULL COMMENT 'analysis + llmAnalysis JSON',
    `created_ip` VARCHAR(45) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`analysis_id`),
    UNIQUE KEY `uk_ids_hash` (`ids_hash`),
    UNIQUE KEY `uk_share_token` (`share_token`),
    KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='/func/analyze 분석 결과 영구 저장';
