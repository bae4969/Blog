-- 주간 방문자 통계 테이블
-- 참조: src/Models/User.php (getVisitorCount, updateVisitorCount)
-- 사용 패턴: INSERT INTO weekly_visitors VALUES (?, 1) ON DUPLICATE KEY UPDATE visit_count = visit_count + 1
CREATE TABLE IF NOT EXISTS `weekly_visitors` (
    `year_week` INT(10) UNSIGNED NOT NULL,
    `visit_count` INT(10) UNSIGNED NOT NULL,
    PRIMARY KEY (`year_week`) USING BTREE
)
COLLATE='utf8mb4_general_ci'
ENGINE=InnoDB
;
