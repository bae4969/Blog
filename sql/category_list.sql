-- 카테고리 테이블
-- 참조: src/Models/Category.php, src/Controllers/AdminController.php
CREATE TABLE IF NOT EXISTS `category_list` (
    `category_index` TINYINT(3) UNSIGNED NOT NULL AUTO_INCREMENT,
    `category_name` TEXT NOT NULL COLLATE 'utf8mb4_general_ci',
    `category_order` TINYINT(3) UNSIGNED NOT NULL,
    `category_read_level` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0' COMMENT 'follow user_level',
    `category_write_level` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0' COMMENT 'follow user_level',
    PRIMARY KEY (`category_index`) USING BTREE,
    UNIQUE INDEX `category_order` (`category_order`) USING BTREE,
    UNIQUE INDEX `category_index` (`category_index`) USING BTREE,
    UNIQUE INDEX `category_name` (`category_name`) USING HASH,
    INDEX `category_read_level` (`category_read_level`) USING BTREE,
    INDEX `category_write_level` (`category_write_level`) USING BTREE
)
COLLATE='utf8mb4_general_ci'
ENGINE=InnoDB
;
