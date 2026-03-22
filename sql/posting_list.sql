-- 게시글 테이블
-- 참조: src/Models/Post.php, src/Controllers/PostController.php
CREATE TABLE IF NOT EXISTS `posting_list` (
    `posting_index` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_index` INT(10) UNSIGNED NOT NULL DEFAULT '0',
    `category_index` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0',
    `posting_state` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0' COMMENT '0:normal\n1:disabled',
    `posting_first_post_datetime` DATETIME NOT NULL DEFAULT current_timestamp(),
    `posting_last_edit_datetime` DATETIME NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
    `posting_read_cnt` INT(10) UNSIGNED NOT NULL DEFAULT '0',
    `posting_title` TINYTEXT NOT NULL DEFAULT '' COLLATE 'utf8mb4_general_ci',
    `posting_thumbnail` MEDIUMTEXT NOT NULL DEFAULT '' COLLATE 'utf8mb4_general_ci',
    `posting_summary` TEXT NOT NULL DEFAULT '' COLLATE 'utf8mb4_general_ci',
    `posting_content` MEDIUMTEXT NOT NULL DEFAULT '' COLLATE 'utf8mb4_general_ci',
    PRIMARY KEY (`posting_index`) USING BTREE,
    UNIQUE INDEX `posting_index` (`posting_index`) USING BTREE,
    INDEX `FK__user_list` (`user_index`) USING BTREE,
    INDEX `posting_title` (`posting_title`(255)) USING BTREE,
    INDEX `FK__category_list` (`category_index`) USING BTREE,
    CONSTRAINT `FK__user_list` FOREIGN KEY (`user_index`) REFERENCES `user_list` (`user_index`) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT `FK_category_list` FOREIGN KEY (`category_index`) REFERENCES `category_list` (`category_index`) ON UPDATE CASCADE ON DELETE CASCADE
)
COLLATE='utf8mb4_general_ci'
ENGINE=InnoDB
;
