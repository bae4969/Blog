-- 사용자 테이블
-- 참조: app/core/blog_user.py
-- ⚠️ `user_pw` 는 2026-08-19 에 걷어냈다. PHP 로그인이 쓰던 컬럼인데 인증이 중앙
--    auth(`10.auth`)로 간 뒤로는 아무도 읽지 않는다. 운영 DB 에서는 이미 지워져 있었고
--    테스트 DB 만 남아 있어 맞췄다. 계정·비밀번호는 이 테이블이 아니라 `Auth.users` 다.
CREATE TABLE IF NOT EXISTS `user_list` (
    `user_index` INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` TINYTEXT NOT NULL COLLATE 'utf8mb4_general_ci',
    `user_level` TINYINT(3) UNSIGNED NOT NULL DEFAULT '4' COMMENT '0:root\n1:Admin\n2:poster\n3:member\n4:visitor',
    `user_state` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0' COMMENT '0:normal\n1:ban',
    `user_first_action_datetime` DATETIME NOT NULL DEFAULT current_timestamp(),
    `user_last_action_datetime` DATETIME NOT NULL DEFAULT current_timestamp(),
    `user_posting_count` MEDIUMINT(8) UNSIGNED NOT NULL DEFAULT '0',
    `user_posting_limit` MEDIUMINT(8) UNSIGNED NOT NULL DEFAULT '0',
    PRIMARY KEY (`user_index`) USING BTREE,
    UNIQUE INDEX `user_index` (`user_index`) USING BTREE,
    UNIQUE INDEX `user_id` (`user_id`) USING HASH
)
COLLATE='utf8mb4_general_ci'
ENGINE=InnoDB
;
