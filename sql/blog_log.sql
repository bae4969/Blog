-- 블로그 로그 테이블 (Log 데이터베이스)
-- 참조: src/Core/Logger.php (ensureBlogLogTableInnoDb)
-- 주의: 이 테이블은 Logger.php에서 런타임에 동적으로 생성되며, 연도별 파티셔닝이 자동 적용됨
-- 아래는 참조용 스키마이며, 실제 생성은 Logger.php가 처리함
-- 파티션의 연도(2026)는 예시이며, 실제로는 현재 연도 기준으로 동적 생성됨
CREATE TABLE IF NOT EXISTS Log.`blog_log` (
    `log_datetime` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '로그 기록 시각',
    `log_name` VARCHAR(255) DEFAULT NULL COMMENT '로그 이름',
    `log_type` CHAR(1) DEFAULT NULL COMMENT '로그 유형',
    `log_message` TEXT DEFAULT NULL COMMENT '로그 메시지',
    `log_function` VARCHAR(255) DEFAULT NULL COMMENT '함수명',
    `log_file` VARCHAR(255) DEFAULT NULL COMMENT '파일 경로',
    `log_line` INT DEFAULT NULL COMMENT '라인 번호'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
PARTITION BY RANGE (YEAR(log_datetime)) (
    PARTITION p2026_prev VALUES LESS THAN (2026),
    PARTITION p2026 VALUES LESS THAN (2027),
    PARTITION pmax VALUES LESS THAN MAXVALUE
);
