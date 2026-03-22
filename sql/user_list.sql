-- 사용자 테이블
-- 참조: src/Models/User.php, src/Controllers/AdminController.php, src/Controllers/AuthController.php
CREATE TABLE IF NOT EXISTS `user_list` (
    `user_index` INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` TINYTEXT NOT NULL COLLATE 'utf8mb4_general_ci',
    `user_pw` TEXT NOT NULL COMMENT 'sha256' COLLATE 'utf8mb4_general_ci',
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
