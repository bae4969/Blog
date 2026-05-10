-- /func/analyze 결과에 대한 좋아요/싫어요 반응
-- voter_token: 익명 쿠키 sha1 (한 분석당 한 사람 1표, 반대 누르면 vote 변경, 같은 거 다시 누르면 행 삭제로 취소)
CREATE TABLE IF NOT EXISTS `func_analysis_reaction_list` (
    `reaction_id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `analysis_id` INT UNSIGNED NOT NULL,
    `voter_token` CHAR(40) NOT NULL COMMENT '쿠키 기반 익명 토큰 sha1',
    `vote` ENUM('like','dislike') NOT NULL,
    `voter_ip` VARCHAR(45) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`reaction_id`),
    UNIQUE KEY `uk_analysis_voter` (`analysis_id`, `voter_token`),
    KEY `idx_analysis` (`analysis_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='/func/analyze 좋아요/싫어요';
